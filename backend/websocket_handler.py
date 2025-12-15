"""
JSON-Based WebSocket Handler
Processes entire batch as JSON
"""
import asyncio
import json
import logging
import base64
import uuid
from fastapi import WebSocket, WebSocketDisconnect
import io
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class JSONImageBatchHandler:
    def __init__(self, websocket: WebSocket, config: dict):
        self.ws = websocket
        self.config = config
        self.processing_batches = set()
        self.completed_batches = set()
        self.total_batches = None  # Will be set when we know total batch count
        self.running_tasks = {}  # Track running batch processing tasks
        self.websocket_closed = False  # Track if websocket is closed

    async def handle_message(self, text_data: str):
        msg = json.loads(text_data)
        msg_type = msg.get("type")

        if msg_type == "batch_images":
            await self._handle_batch_images(msg)

    async def _handle_batch_images(self, msg: dict):
        batch_id = msg.get("batchId", 0)
        images_data = msg.get("images", [])

        await self.ws.send_json({"type": "batch_queued", "batchId": batch_id})

        # Process batches concurrently - don't wait for previous batch to finish
        task = asyncio.create_task(self._process_batch_background(batch_id, len(images_data), images_data))
        self.running_tasks[batch_id] = task
        
        # Clean up task when done
        def cleanup_task(t, bid=batch_id):
            self.running_tasks.pop(bid, None)
        task.add_done_callback(lambda t: cleanup_task(t, batch_id))

    async def _process_batch_background(self, batch_id: int, batch_size: int, images_data: list):
        try:
            # Decode base64 → PIL
            batch_images = {}
            loop = asyncio.get_event_loop()

            def decode(img_info):
                try:
                    data = base64.b64decode(img_info["data"])
                    return {
                        "task_id": img_info["taskId"],
                        "filename": img_info["filename"],
                        "image": Image.open(io.BytesIO(data)),
                    }
                except:
                    return None

            with ThreadPoolExecutor(max_workers=min(10, len(images_data))) as pool:
                decoded = await asyncio.gather(
                    *[loop.run_in_executor(pool, decode, x) for x in images_data]
                )

            for d in decoded:
                if d:
                    batch_images[d["task_id"]] = {
                        "image": d["image"],
                        "filename": d["filename"]
                    }

            # GPU processing
            from workers import process_batch_parallel
            session_id = self.config.get("sessionId")
            results = await process_batch_parallel(
                batch_images=batch_images,
                batch_id=batch_id,
                config=self.config,
                callback=self._send_result,
                session_id=session_id,
            )

            # Notify completion
            success_count = len([r for r in results if r.get("success")])
            self.completed_batches.add(batch_id)
            
            if self.websocket_closed:
                logger.warning(f"WebSocket closed, skipping batch_complete for batch {batch_id}")
                return
            
            try:
                await self.ws.send_json({
                    "type": "batch_complete",
                    "batchId": batch_id,
                    "successCount": success_count,
                    "totalCount": len(results)
                })
            except (RuntimeError, Exception) as e:
                self.websocket_closed = True
                logger.warning(f"Could not send batch_complete for batch {batch_id}: {e}")
                return  # WebSocket closed, stop processing

            # NOTE: ZIP creation is now handled by frontend when ALL batches are complete
            # We don't create ZIP per batch anymore

        except Exception as e:
            # Only send error if WebSocket is still open
            try:
                await self.ws.send_json({"type": "batch_error", "batchId": batch_id, "error": str(e)})
            except (RuntimeError, Exception) as send_error:
                # WebSocket is already closed, just log the error
                logger.error(f"Error in batch {batch_id}: {e}. Could not send error message (WebSocket closed): {send_error}")

    async def _send_result(self, result):
        if self.websocket_closed:
            return
        try:
            await self.ws.send_json({
                "type": "image_processed",
                "batchId": result["batch_id"],
                "taskId": result["task_id"],
                "downloadUrl": result["downloadUrl"],
                "imageId": result["imageId"],
                "filename": result["filename"],
                "success": True
            })
        except (RuntimeError, Exception) as e:
            self.websocket_closed = True
            # WebSocket is closed, skip sending
            logger.warning(f"Could not send result for batch {result['batch_id']}: {e}")


async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    config_data = await websocket.receive_text()
    config = json.loads(config_data)
    # Ensure every websocket session has a unique sessionId
    config.setdefault("sessionId", f"ws_{uuid.uuid4().hex}")
    await websocket.send_json({"type": "config_ack", "config": config})

    handler = JSONImageBatchHandler(websocket, config)
    websocket_closed = False

    async def message_loop():
        nonlocal websocket_closed
        try:
            while True:
                msg = await websocket.receive_text()
                await handler.handle_message(msg)
        except WebSocketDisconnect:
            websocket_closed = True
            handler.websocket_closed = True
            logger.info("WebSocket disconnected by client")
        except Exception as e:
            logger.error(f"Error in message loop: {e}", exc_info=True)
            websocket_closed = True
            handler.websocket_closed = True

    message_task = asyncio.create_task(message_loop())

    try:
        await message_task
    except Exception as e:
        logger.error(f"Error in websocket endpoint: {e}", exc_info=True)
    finally:
        if handler.running_tasks:
            logger.info(f"Waiting for {len(handler.running_tasks)} batch(es) to complete before closing...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*handler.running_tasks.values(), return_exceptions=True),
                    timeout=300
                )
                logger.info("All batches completed")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for batches to complete")
            except Exception as e:
                logger.error(f"Error waiting for batches: {e}", exc_info=True)
