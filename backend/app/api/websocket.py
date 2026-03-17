import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.schemas import ARIAState, WebSocketMessage

logger = structlog.get_logger()

ws_router = APIRouter()

connected_clients: list[WebSocket] = []


async def broadcast_state(state: ARIAState) -> None:
    message = state.model_dump_json()
    disconnected: list[WebSocket] = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)


async def state_broadcast_loop(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(0.1)
        state = ARIAState()
        try:
            await websocket.send_text(state.model_dump_json())
        except Exception:
            break


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info("WebSocket client connected", clients=len(connected_clients))

    broadcast_task = asyncio.create_task(state_broadcast_loop(websocket))

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg = WebSocketMessage(**data)
            logger.debug("Received WebSocket message", type=msg.type)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
    finally:
        broadcast_task.cancel()
        if websocket in connected_clients:
            connected_clients.remove(websocket)
