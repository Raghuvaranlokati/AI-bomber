"""server.py — FastAPI server for controlling the API request scheduler."""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from task_manager import TaskManager, SchedulerState
from worker import load_config, scheduler_loop

# ── Logging Setup ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("server")

# ── Global Instances ──────────────────────────────────────────
manager = TaskManager()
scheduler_task: Optional[asyncio.Task] = None
websocket_clients: list[WebSocket] = []
log_queue: asyncio.Queue = asyncio.Queue()


# ═══════════════════════════════════════════════════════════════
# Request / Response Schemas
# ═══════════════════════════════════════════════════════════════

class StartRequest(BaseModel):
    target: str = Field(..., min_length=1, description="Target phone number or email")
    attack_type: str = Field(default="sms", pattern=r"^(sms|call|email)$")
    delay: float = Field(default=2.0, ge=0.1, le=30.0)


class ConfigUpdateRequest(BaseModel):
    target: Optional[str] = None
    attack_type: Optional[str] = Field(default=None, pattern=r"^(sms|call|email)$")
    delay: Optional[float] = Field(default=None, ge=0.1, le=30.0)


# ═══════════════════════════════════════════════════════════════
# Log Callback (feeds both logger and WebSocket queue)
# ═══════════════════════════════════════════════════════════════

async def log_callback(message):
    """
    Callback passed to the worker.
    Receives either a string (log line) or a dict (status update).
    """
    if isinstance(message, dict):
        # Status update dict
        log_msg = (
            f"[{message.get('total_sent', 0)} sent | "
            f"{message.get('total_failed', 0)} failed] "
            f"{message.get('current_endpoint', '')} -> "
            f"{message.get('last_result', '')}"
        )
        logger.info(log_msg)
        await log_queue.put(json.dumps({
            "type": "status",
            "data": message,
        }))
    else:
        # Plain log string
        logger.info(message)
        await log_queue.put(json.dumps({
            "type": "log",
            "message": str(message),
        }))


# ═══════════════════════════════════════════════════════════════
# Background Tasks
# ═══════════════════════════════════════════════════════════════

async def broadcast_logs():
    """
    Background coroutine that reads from log_queue and
    broadcasts to all connected WebSocket clients.
    """
    while True:
        try:
            msg = await asyncio.wait_for(log_queue.get(), timeout=1.0)
            dead_clients = []
            for ws in websocket_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead_clients.append(ws)
            for dead in dead_clients:
                websocket_clients.remove(dead)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Broadcast error: {e}")


async def run_worker_wrapper():
    """
    Wrapper that runs scheduler_loop and handles cleanup.
    This is the actual asyncio task that gets launched.
    """
    try:
        await scheduler_loop(
            attack_type=manager.attack_type,
            target=manager.target,
            delay=manager.delay,
            cancel_event=manager.cancel_event,
            pause_event=manager.pause_event,
            status_callback=log_callback,
        )
    except asyncio.CancelledError:
        logger.info("Worker task cancelled")
    except Exception as e:
        logger.exception(f"Worker task crashed: {e}")
        await log_callback(f"[ERROR] Worker crashed: {e}")
    finally:
        manager._state = SchedulerState.IDLE
        await log_callback("[IDLE] Worker stopped")


# ═══════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background broadcaster on startup, clean up on shutdown."""
    global scheduler_task

    broadcast_task = asyncio.create_task(broadcast_logs())
    logger.info("Server starting up...")

    yield

    # Shutdown
    logger.info("Server shutting down...")
    broadcast_task.cancel()

    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

    # Close all WebSocket connections
    for ws in websocket_clients[:]:
        try:
            await ws.close()
        except Exception:
            pass
    websocket_clients.clear()

    logger.info("Server shut down complete")


# ═══════════════════════════════════════════════════════════════
# App Initialization
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="API Request Scheduler",
    description="Round-robin HTTP request scheduler for rate-limit testing",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# REST Endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "API Request Scheduler",
        "version": "1.0.0",
        "status": manager.state.value,
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/status")
async def get_status():
    """Get the current scheduler status."""
    return manager.get_status_dict()


@app.post("/start")
async def start(req: StartRequest):
    """
    Start the scheduler.
    - target: phone number or email to send requests to
    - attack_type: 'sms', 'call', or 'email'
    - delay: seconds between requests (0.1 - 30.0)
    """
    global scheduler_task

    if manager.state == SchedulerState.RUNNING:
        raise HTTPException(409, "Scheduler is already running. Stop it first.")

    if manager.state == SchedulerState.PAUSED:
        raise HTTPException(409, "Scheduler is paused. Use /resume to continue.")

    # Configure the manager
    manager.prepare_start(
        target=req.target,
        attack_type=req.attack_type,
        delay=req.delay,
    )

    # Transition to running
    manager.start()

    # Launch the worker in background
    scheduler_task = asyncio.create_task(run_worker_wrapper())

    logger.info(
        f"Started: target={req.target}, type={req.attack_type}, delay={req.delay}s"
    )

    return {
        "message": "Scheduler started",
        "status": manager.get_status_dict(),
    }


@app.post("/stop")
async def stop():
    """Stop the scheduler immediately."""
    global scheduler_task

    if manager.state == SchedulerState.IDLE:
        return {"message": "Scheduler is not running", "status": manager.get_status_dict()}

    # Send stop signal
    manager.stop()

    # Cancel the background task if still running
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        scheduler_task = None

    logger.info("Scheduler stopped")

    return {
        "message": "Scheduler stopped",
        "status": manager.get_status_dict(),
    }


@app.post("/pause")
async def pause():
    """Pause the scheduler. Current request completes, then pauses."""
    if manager.state != SchedulerState.RUNNING:
        raise HTTPException(409, "Scheduler is not running (use /start first)")

    manager.pause()

    return {
        "message": "Scheduler paused",
        "status": manager.get_status_dict(),
    }


@app.post("/resume")
async def resume():
    """Resume the scheduler from paused state."""
    if manager.state != SchedulerState.PAUSED:
        raise HTTPException(409, "Scheduler is not paused (use /pause first)")

    manager.resume()

    return {
        "message": "Scheduler resumed",
        "status": manager.get_status_dict(),
    }


@app.post("/config")
async def update_config(update: ConfigUpdateRequest):
    """
    Update configuration without restarting.
    Changes take effect on the next request cycle.
    """
    if update.target is not None:
        manager.target = update.target
    if update.attack_type is not None:
        manager.attack_type = update.attack_type
    if update.delay is not None:
        manager.delay = update.delay

    return {
        "message": "Configuration updated",
        "status": manager.get_status_dict(),
    }


@app.get("/endpoints")
async def list_endpoints():
    """List all available API endpoints from the config file."""
    try:
        config = load_config()
        result = {}

        targets = config.get("targets", {})

        # SMS
        sms_apis = targets.get("phone", {}).get("sms", [])
        result["sms"] = {
            "count": len(sms_apis),
            "endpoints": [a.get("name", "unknown") for a in sms_apis],
        }

        # Call
        call_apis = targets.get("phone", {}).get("call", [])
        result["call"] = {
            "count": len(call_apis),
            "endpoints": [a.get("name", "unknown") for a in call_apis],
        }

        # Email
        email_apis = targets.get("email", {}).get("email", [])
        result["email"] = {
            "count": len(email_apis),
            "endpoints": [a.get("name", "unknown") for a in email_apis],
        }

        return result

    except FileNotFoundError:
        raise HTTPException(500, "api_config.json not found")
    except json.JSONDecodeError:
        raise HTTPException(500, "api_config.json is invalid JSON")


@app.post("/reset")
async def reset_counters():
    """Reset sent/failed counters to zero."""
    if manager.state == SchedulerState.RUNNING:
        raise HTTPException(409, "Cannot reset counters while scheduler is running. Stop first.")

    manager.reset_counters()

    return {
        "message": "Counters reset",
        "status": manager.get_status_dict(),
    }


@app.get("/config")
async def get_config():
    """Get current scheduler configuration."""
    return {
        "target": manager.target,
        "attack_type": manager.attack_type,
        "delay": manager.delay,
    }


# ═══════════════════════════════════════════════════════════════
# WebSocket Endpoint
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket for real-time log and status streaming.
    Sends JSON messages:
      - {"type": "log", "message": "..."}
      - {"type": "status", "data": {...}}

    Receives commands:
      - {"action": "ping"} -> {"type": "pong"}
      - {"action": "get_status"} -> {"type": "status", "data": {...}}
    """
    await websocket.accept()
    websocket_clients.append(websocket)

    # Send initial status immediately on connect
    await websocket.send_text(json.dumps({
        "type": "status",
        "data": manager.get_status_dict(),
    }))

    logger.info(f"WebSocket client connected (total: {len(websocket_clients)})")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                action = cmd.get("action", "")

                if action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

                elif action == "get_status":
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": manager.get_status_dict(),
                    }))

                elif action == "start":
                    # Handle start via WebSocket
                    target = cmd.get("target", "")
                    attack_type = cmd.get("attack_type", "sms")
                    delay = float(cmd.get("delay", 2.0))

                    if not target:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "target is required",
                        }))
                        continue

                    global scheduler_task
                    if manager.state == SchedulerState.RUNNING:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "Already running",
                        }))
                        continue

                    manager.prepare_start(target, attack_type, delay)
                    manager.start()
                    scheduler_task = asyncio.create_task(run_worker_wrapper())

                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": manager.get_status_dict(),
                    }))

                elif action == "stop":
                    manager.stop()
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": manager.get_status_dict(),
                    }))

                elif action == "pause":
                    if manager.state == SchedulerState.RUNNING:
                        manager.pause()
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": manager.get_status_dict(),
                    }))

                elif action == "resume":
                    if manager.state == SchedulerState.PAUSED:
                        manager.resume()
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "data": manager.get_status_dict(),
                    }))

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected (total: {len(websocket_clients)})")


# ═══════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    print("╔══════════════════════════════════════════════════════╗")
    print("║        API Request Scheduler v1.0                    ║")
    print("║                                                      ║")
    print("║  REST API:     http://localhost:8000                 ║")
    print("║  Swagger Docs: http://localhost:8000/docs            ║")
    print("║  WebSocket:    ws://localhost:8000/ws                ║")
    print("║                                                      ║")
    print("║  Endpoints:                                          ║")
    print("║    GET  /         - Service info                     ║")
    print("║    GET  /status   - Scheduler status                 ║")
    print("║    POST /start    - Start scheduler                  ║")
    print("║    POST /stop     - Stop scheduler                   ║")
    print("║    POST /pause    - Pause scheduler                  ║")
    print("║    POST /resume   - Resume scheduler                 ║")
    print("║    POST /config   - Update configuration             ║")
    print("║    GET  /endpoints - List configured APIs            ║")
    print("║    POST /reset    - Reset counters                   ║")
    print("║    WS   /ws       - Real-time logs & control         ║")
    print("╚══════════════════════════════════════════════════════╝")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )