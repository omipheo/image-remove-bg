"""
Parallel Upload WebSocket Handler
Handles out-of-order metadata and binary chunks
"""
import asyncio
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Optional
import io
from PIL import Image
from collections import defaultdict

logger = logging.getLogger(__name__)

class ParallelImageBatchHandler:
    """Handles parallel image uploads with proper buffering"""
    
    def __init__(self, websocket: WebSocket, config: dict):
        self.ws = websocket
        self.config = config
        
        # Buffering structures for parallel uploads
        self.pending_metadata: Dict[tuple, dict] = {}  # (batch_id, task_id) -> metadata
        self.pending_binary: Dict[tuple, bytearray] = {}  # (batch_id, task_id) -> binary data
        self.complete_images: Dict[tuple, dict] = {}  # (batch_id, task_id) -> complete image
        
        # Track batch completion
        self.batch_size = config.get('batchSize', 100)
        self.batch_end_received = set()  # Which batches got batch_end signal
        self.processing_batches = set()  # Currently processing batches
        
        logger.info(f"[WS] ParallelImageBatchHandler initialized (batch size: {self.batch_size})")
    
    async def handle_text_message(self, text_data: str):
        """Handle JSON text messages"""
        try:
            msg = json.loads(text_data)
            msg_type = msg.get('type')
            
            if msg_type == 'image_metadata':
                await self._handle_metadata(msg)
            elif msg_type == 'batch_end':
                await self._handle_batch_end(msg)
            elif msg_type == 'close':
                logger.info("[WS] Close signal received")
                
        except Exception as e:
            logger.error(f"[WS] Error handling text message: {e}", exc_info=True)
    
    async def handle_binary_message(self, binary_data: bytes):
        """Handle binary image data"""
        try:
            # Match binary to pending metadata by size
            matched = False
            
            # Sort by batch_id, task_id to process in order
            for key in sorted(self.pending_metadata.keys()):
                if key in self.complete_images:
                    continue  # Already complete
                
                metadata = self.pending_metadata[key]
                expected_size = metadata.get('size', 0)
                
                # Initialize buffer if needed
                if key not in self.pending_binary:
                    self.pending_binary[key] = bytearray()
                
                current_size = len(self.pending_binary[key])
                
                # Check if this binary chunk belongs to this image
                if current_size < expected_size:
                    # Append chunk
                    chunk_size = min(len(binary_data), expected_size - current_size)
                    self.pending_binary[key].extend(binary_data[:chunk_size])
                    
                    batch_id, task_id = key
                    new_size = len(self.pending_binary[key])
                    
                    logger.debug(f"[WS] Binary data for task {task_id} (batch {batch_id}): "
                               f"+{chunk_size} bytes (now {new_size}/{expected_size})")
                    
                    # Check if complete
                    if new_size >= expected_size:
                        await self._complete_image(key)
                    
                    matched = True
                    break
            
            if not matched:
                logger.warning(f"[WS] Received {len(binary_data)} bytes binary data with no matching metadata")
                
        except Exception as e:
            logger.error(f"[WS] Error handling binary message: {e}", exc_info=True)
    
    async def _handle_metadata(self, msg: dict):
        """Store metadata for incoming image"""
        batch_id = msg.get('batchId', 0)
        task_id = msg.get('taskId', 0)
        filename = msg.get('filename', 'unknown.jpg')
        size = msg.get('size', 0)
        
        key = (batch_id, task_id)
        self.pending_metadata[key] = {
            'filename': filename,
            'size': size,
            'batch_id': batch_id,
            'task_id': task_id
        }
        
        logger.debug(f"[WS] Metadata for task {task_id} (batch {batch_id}): {filename} ({size} bytes)")
        
        # Check if binary already arrived
        if key in self.pending_binary and len(self.pending_binary[key]) >= size:
            await self._complete_image(key)
    
    async def _complete_image(self, key: tuple):
        """Mark image as complete when both metadata and binary are ready"""
        batch_id, task_id = key
        
        if key not in self.pending_metadata:
            logger.warning(f"[WS] Cannot complete task {task_id} - no metadata")
            return
        
        if key not in self.pending_binary:
            logger.warning(f"[WS] Cannot complete task {task_id} - no binary data")
            return
        
        metadata = self.pending_metadata[key]
        binary_data = bytes(self.pending_binary[key])
        expected_size = metadata['size']
        
        # Validate size
        if len(binary_data) < expected_size:
            logger.warning(f"[WS] Task {task_id} incomplete: {len(binary_data)}/{expected_size} bytes")
            return
        
        # Trim excess if any
        if len(binary_data) > expected_size:
            binary_data = binary_data[:expected_size]
        
        # Store complete image
        self.complete_images[key] = {
            'metadata': metadata,
            'data': binary_data,
            'batch_id': batch_id,
            'task_id': task_id,
            'filename': metadata['filename']
        }
        
        logger.info(f"[WS] ✅ Task {task_id} (batch {batch_id}) complete: {metadata['filename']}")
        
        # Clean up
        del self.pending_metadata[key]
        del self.pending_binary[key]
    
    async def _handle_batch_end(self, msg: dict):
        """Handle batch_end signal - start processing when ready"""
        batch_id = msg.get('batchId', 0)
        batch_size = msg.get('batchSize', self.batch_size)
        
        logger.info(f"[WS] Received batch_end for batch {batch_id} (size: {batch_size})")
        self.batch_end_received.add(batch_id)
        
        # Wait longer for any in-flight data (INCREASED from 0.2s to 0.5s)
        await asyncio.sleep(0.5)
        
        # Check completion status
        complete_count = sum(1 for k in self.complete_images if k[0] == batch_id)
        logger.info(f"[WS] Batch {batch_id} status: {complete_count}/{batch_size} images complete")
        
        # Wait longer if close to complete (INCREASED from 0.5s to 1.0s)
        if complete_count >= batch_size * 0.9 and complete_count < batch_size:
            logger.info(f"[WS] Waiting for remaining images in batch {batch_id}...")
            await asyncio.sleep(1.0)
            complete_count = sum(1 for k in self.complete_images if k[0] == batch_id)
            logger.info(f"[WS] After wait: {complete_count}/{batch_size} complete")
        
        # Start processing
        await self._process_batch(batch_id, batch_size)
    
    async def _process_batch(self, batch_id: int, batch_size: int):
        """Process a batch of images"""
        if batch_id in self.processing_batches:
            logger.warning(f"[WS] Batch {batch_id} already processing, skipping")
            return
        
        self.processing_batches.add(batch_id)
        logger.info(f"[WS] 🚀 Starting processing for batch {batch_id}")
        
        # Send batch_queued notification
        await self.ws.send_json({
            'type': 'batch_queued',
            'batchId': batch_id,
            'timestamp': asyncio.get_event_loop().time()
        })
        
        # Collect complete images for this batch
        batch_images = {}
        for task_id in range(batch_size):
            key = (batch_id, task_id)
            if key in self.complete_images:
                img_data = self.complete_images[key]
                
                # Convert binary to PIL Image
                try:
                    image_bytes = io.BytesIO(img_data['data'])
                    pil_image = Image.open(image_bytes)
                    
                    batch_images[task_id] = {
                        'image': pil_image,
                        'filename': img_data['filename'],
                        'task_id': task_id,
                        'batch_id': batch_id
                    }
                except Exception as e:
                    logger.error(f"[WS] Error loading image {task_id}: {e}")
        
        logger.info(f"[WS] Processing {len(batch_images)}/{batch_size} images for batch {batch_id}")
        
        # Define callback to send results back to client
        async def send_result_callback(result):
            """Callback to send results back to client"""
            await self.ws.send_json({
                'type': 'image_processed',
                'batchId': result.get('batch_id'),
                'taskId': result.get('task_id'),
                'downloadUrl': result.get('downloadUrl'),
                'imageId': result.get('imageId'),
                'filename': result.get('filename'),
                'success': result.get('success', True)
            })
        
        # Import process_batch_parallel here to avoid circular import
        from workers import process_batch_parallel
        
        try:
            results = await process_batch_parallel(
                batch_images=batch_images,
                batch_id=batch_id,
                config=self.config,
                callback=send_result_callback
            )
            
            # CRITICAL: Add null check for results
            if results is None:
                logger.error(f"[WS] Batch {batch_id} returned None results")
                results = []
            
            # Clean up processed images
            for task_id in range(batch_size):
                key = (batch_id, task_id)
                if key in self.complete_images:
                    del self.complete_images[key]
            
            # Send batch_complete
            success_count = len([r for r in results if isinstance(r, dict) and r.get('success')])
            await self.ws.send_json({
                'type': 'batch_complete',
                'batchId': batch_id,
                'successCount': success_count,
                'totalCount': len(results)
            })
            
            logger.info(f"[WS] ✅ Batch {batch_id} complete ({success_count}/{len(results)} successful)")
            
        except Exception as e:
            logger.error(f"[WS] Error processing batch {batch_id}: {e}", exc_info=True)
            await self.ws.send_json({
                'type': 'batch_error',
                'batchId': batch_id,
                'error': str(e)
            })
        finally:
            self.processing_batches.remove(batch_id)


async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint - PARALLEL UPLOAD VERSION"""
    await websocket.accept()
    logger.info("[WS] ✅ WebSocket connection accepted")
    
    try:
        # Wait for configuration
        config_data = await websocket.receive_text()
        config = json.loads(config_data)
        
        logger.info(f"[WS] Configuration received: {config}")
        
        # Send acknowledgment
        await websocket.send_json({
            'type': 'config_ack',
            'config': config
        })
        
        # Create parallel handler
        handler = ParallelImageBatchHandler(websocket, config)
        
        # Message loop
        while True:
            data = await websocket.receive()
            
            if 'text' in data:
                await handler.handle_text_message(data['text'])
            elif 'bytes' in data:
                await handler.handle_binary_message(data['bytes'])
            else:
                logger.warning(f"[WS] Unknown data type: {data}")
                
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] WebSocket error: {e}", exc_info=True)
    finally:
        logger.info("[WS] Connection closed")