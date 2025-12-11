"""
JSON-Based WebSocket Handler
Receives entire batch as single JSON payload
"""
import asyncio
import json
import logging
import base64
from fastapi import WebSocket, WebSocketDisconnect
import io
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

class JSONImageBatchHandler:
    """Handles batch image uploads via JSON"""
    
    def __init__(self, websocket: WebSocket, config: dict):
        self.ws = websocket
        self.config = config
        self.processing_batches = set()
        
        logger.info(f"[WS] JSONImageBatchHandler initialized")
    
    async def handle_message(self, text_data: str):
        """Handle JSON messages"""
        try:
            msg = json.loads(text_data)
            msg_type = msg.get('type')
            
            if msg_type == 'batch_images':
                await self._handle_batch_images(msg)
            elif msg_type == 'close':
                logger.info("[WS] Close signal received")
                
        except Exception as e:
            logger.error(f"[WS] Error handling message: {e}", exc_info=True)
            await self.ws.send_json({
                'type': 'error',
                'error': str(e)
            })
    
    async def _handle_batch_images(self, msg: dict):
        """Process batch of images sent as JSON"""
        batch_id = msg.get('batchId', 0)
        batch_size = msg.get('batchSize', 0)
        images_data = msg.get('images', [])
        
        print(f"[WS] Handle Batch Images: {batch_id} with {len(images_data)} images")
        # print(f"[WS] Images Data: {images_data}")
        if batch_id in self.processing_batches:
            logger.warning(f"[WS] Batch {batch_id} already processing")
            return
        
        self.processing_batches.add(batch_id)
        logger.info(f"[WS] 📦 Received batch {batch_id} with {len(images_data)} images")
        
        # Send acknowledgment IMMEDIATELY (before any processing)
        try:
            await self.ws.send_json({
                'type': 'batch_queued',
                'batchId': batch_id,
                'timestamp': asyncio.get_event_loop().time()
            })
            logger.info(f"[WS] ✅ Sent batch_queued for batch {batch_id}")
        except Exception as e:
            logger.error(f"[WS] ❌ Error sending batch_queued for batch {batch_id}: {e}")
            self.processing_batches.remove(batch_id)
            return
        
        # # Process batch in background task so message loop can continue
        # asyncio.create_task(self._process_batch_background(batch_id, batch_size, images_data))
        await self._process_batch_background(batch_id, batch_size, images_data)
    
    async def _process_batch_background(self, batch_id: int, batch_size: int, images_data: list):
        """Process batch in background (decoding and GPU processing)"""
        try:
            # Convert base64 to PIL Images (run in thread pool to avoid blocking)
            batch_images = {}
            
            def decode_image(img_info):
                """Decode a single image (runs in thread pool)"""
                task_id = img_info.get('taskId')
                filename = img_info.get('filename')
                base64_data = img_info.get('data')
                
                try:
                    # Decode base64
                    image_bytes = base64.b64decode(base64_data)
                    
                    # Convert to PIL Image
                    image_buffer = io.BytesIO(image_bytes)
                    pil_image = Image.open(image_buffer)
                    
                    return {
                        'task_id': task_id,
                        'image': pil_image,
                        'filename': filename,
                        'batch_id': batch_id
                    }
                except Exception as e:
                    logger.error(f"[WS] ❌ Error loading task {task_id}: {e}")
                    return None
            
            # Decode images in parallel using thread pool
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=min(10, len(images_data))) as executor:
                results = await asyncio.gather(*[
                    loop.run_in_executor(executor, decode_image, img_info)
                    for img_info in images_data
                ])
            
            print(f"[WS] Len of Results: {len(results)}")
            # Build batch_images dict
            for result in results:
                if result:
                    task_id = result['task_id']
                    filename = result['filename']
                    pil_image = result['image']
                    # Get image size for verification
                    img_byte_arr = io.BytesIO()
                    pil_image.save(img_byte_arr, format='PNG')
                    img_size = len(img_byte_arr.getvalue())
                    
                    batch_images[task_id] = {
                        'image': pil_image,
                        'filename': filename,
                        'task_id': task_id,
                        'batch_id': result['batch_id']
                    }
                    # logger.info(f"[WS] ✅ Loaded task {task_id}: {filename} (image size: {img_size} bytes, mode: {pil_image.mode}, size: {pil_image.size})")
            
            # Define callback to send results
            async def send_result_callback(result):
                """Send processing results back to client"""
                # print(f"[WS] batchId: {result.get('batch_id')}")
                # print(f"[WS] taskId: {result.get('task_id')}")
                # print(f"[WS] downloadUrl: {result.get('downloadUrl')}")
                # print(f"[WS] imageId: {result.get('imageId')}")
                # print(f"[WS] filename: {result.get('filename')}")
                # print(f"[WS] success: {result.get('success', True)}")
                await self.ws.send_json({
                    'type': 'image_processed',
                    'batchId': result.get('batch_id'),
                    'taskId': result.get('task_id'),
                    'downloadUrl': result.get('downloadUrl'),
                    'imageId': result.get('imageId'),
                    'filename': result.get('filename'),
                    'success': result.get('success', True)
                })
            
            # Process batch
            from workers import process_batch_parallel
            
            try:
                results = await process_batch_parallel(
                    batch_images=batch_images,
                    batch_id=batch_id,
                    config=self.config,
                    callback=send_result_callback
                )
                
                if results is None:
                    logger.error(f"[WS] Batch {batch_id} returned None results")
                    results = []
                
                # Send completion
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
        except Exception as e:
            logger.error(f"[WS] Error in background processing for batch {batch_id}: {e}", exc_info=True)
            self.processing_batches.remove(batch_id)
            await self.ws.send_json({
                'type': 'batch_error',
                'batchId': batch_id,
                'error': str(e)
            })


async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint - JSON VERSION"""
    await websocket.accept()
    logger.info("[WS] ✅ WebSocket connection accepted")
    
    try:
        # Wait for configuration
        config_data = await websocket.receive_text()
        config = json.loads(config_data)
        
        # print(f"[WS] Configuration received: {config}")
        logger.info(f"[WS] Configuration received: {config}")
        
        # Send acknowledgment
        await websocket.send_json({
            'type': 'config_ack',
            'config': config
        })
        
        # Create handler
        handler = JSONImageBatchHandler(websocket, config)
        
        # Message loop - process messages sequentially to maintain order
        while True:
            message = await websocket.receive_text()
            # print(f"[WS] Message received: {message}")
            # Handle message (this will send batch_queued immediately, then process async)
            await handler.handle_message(message)
                
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] WebSocket error: {e}", exc_info=True)
    finally:
        logger.info("[WS] Connection closed")