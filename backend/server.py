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

def log_callback(message):
    """
    Callback passed to the worker.
    Receives either a string (log line) or a dict (status update).
    This is a SYNCHRONOUS function because worker.py calls it without await.
    Async operations are dispatched via asyncio.create_task.
    """
    if isinstance(message, dict):
        # Status update dict
        log_msg = (
            f"[{message.get('total_sent', 0)} sent | "
            f"{message.get('total_failed', 0)} failed] "
            f"Current: {message.get('current_endpoint', '')} -> "
            f"{message.get('last_result', '')}"
        )
        logger.info(log_msg)
        # Dispatch async WebSocket broadcast without awaiting
        asyncio.create_task(_broadcast_to_websockets({
            "type": "status",
            "data": message,
        }))
    else:
        # Plain log string
        logger.info(str(message))
        asyncio.create_task(_broadcast_to_websockets({
            "type": "log",
            "message": str(message),
        }))


async def _broadcast_to_websockets(data: dict):
    """Send a JSON message to all connected WebSocket clients and the log queue."""
    msg = json.dumps(data)
    # Remove dead clients while iterating
    dead_clients = []
    for ws in websocket_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead_clients.append(ws)
    for ws in dead_clients:
        websocket_clients.remove(ws)
    await log_queue.put(data)


# ═══════════════════════════════════════════════════════════════
# Worker Wrapper (runs scheduler_loop in an asyncio task)
# ═══════════════════════════════════════════════════════════════

async def run_worker_wrapper():
    """
    Wrapper that runs scheduler_loop with the current manager configuration.
    Managed as a single asyncio task so it can be cancelled on stop.
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
        logger.info("Scheduler task was cancelled")
    except Exception as e:
        logger.error(f"Scheduler task failed with error: {e}")
        manager.stop()
        asyncio.create_task(_broadcast_to_websockets({
            "type": "log",
            "message": f"[!] Scheduler error: {e}",
        }))
    finally:
        manager.stop()


# ═══════════════════════════════════════════════════════════════
# App Lifespan (startup / shutdown)
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Server starting up...")
    yield
    # Shutdown
    logger.info("Server shutting down...")
    if scheduler_task and not scheduler_task.done():
        manager.stop()
        scheduler_task.cancel()
        try:
            await asyncio.wait_for(scheduler_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass


# ═══════════════════════════════════════════════════════════════
# FastAPI Application
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="API Request Scheduler",
    version="1.0",
    lifespan=lifespan,
)

# CORS middleware
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
    """Service info."""
    return {
        "service": "API Request Scheduler",
        "version": "1.0",
        "docs": "/docs",
        "status": manager.state.value,
    }


@app.get("/status")
async def get_status():
    """Get current scheduler status."""
    return manager.get_status_dict()


@app.post("/start")
async def start_scheduler(req: StartRequest):
    """Start the scheduler with given target, attack type, and delay."""
    global scheduler_task

    if manager.state == SchedulerState.RUNNING:
        raise HTTPException(409, "Scheduler is already running. Stop it first.")

    manager.prepare_start(req.target, req.attack_type, req.delay)
    manager.start()
    scheduler_task = asyncio.create_task(run_worker_wrapper())

    return {
        "message": "Scheduler started",
        "status": manager.get_status_dict(),
    }


@app.post("/stop")
async def stop_scheduler():
    """Stop the scheduler."""
    if manager.state not in (SchedulerState.RUNNING, SchedulerState.PAUSED):
        raise HTTPException(409, "Scheduler is not running.")

    manager.stop()
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()

    return {
        "message": "Scheduler stopped",
        "status": manager.get_status_dict(),
    }


@app.post("/pause")
async def pause_scheduler():
    """Pause the scheduler."""
    if manager.state != SchedulerState.RUNNING:
        raise HTTPException(409, "Scheduler is not running.")

    manager.pause()
    return {
        "message": "Scheduler paused",
        "status": manager.get_status_dict(),
    }


@app.post("/resume")
async def resume_scheduler():
    """Resume a paused scheduler."""
    if manager.state != SchedulerState.PAUSED:
        raise HTTPException(409, "Scheduler is not paused.")

    manager.resume()
    return {
        "message": "Scheduler resumed",
        "status": manager.get_status_dict(),
    }


@app.post("/config")
async def update_config(update: ConfigUpdateRequest):
    """Update scheduler configuration without restarting."""
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
        raise HTTPException(
            409, "Cannot reset counters while scheduler is running. Stop first."
        )

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
    await websocket.send_text(
        json.dumps({
            "type": "status",
            "data": manager.get_status_dict(),
        })
    )

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
                    await websocket.send_text(
                        json.dumps({
                            "type": "status",
                            "data": manager.get_status_dict(),
                        })
                    )

                elif action == "start":
                    target = cmd.get("target", "")
                    attack_type = cmd.get("attack_type", "sms")
                    delay = float(cmd.get("delay", 2.0))

                    if not target:
                        await websocket.send_text(
                            json.dumps({
                                "type": "error",
                                "message": "target is required",
                            })
                        )
                        continue

                    global scheduler_task
                    if manager.state == SchedulerState.RUNNING:
                        await websocket.send_text(
                            json.dumps({
                                "type": "error",
                                "message": "Already running",
                            })
                        )
                        continue

                    manager.prepare_start(target, attack_type, delay)
                    manager.start()
                    scheduler_task = asyncio.create_task(run_worker_wrapper())

                    await websocket.send_text(
                        json.dumps({
                            "type": "status",
                            "data": manager.get_status_dict(),
                        })
                    )

                elif action == "stop":
                    manager.stop()
                    await websocket.send_text(
                        json.dumps({
                            "type": "status",
                            "data": manager.get_status_dict(),
                        })
                    )

                elif action == "pause":
                    if manager.state == SchedulerState.RUNNING:
                        manager.pause()
                    await websocket.send_text(
                        json.dumps({
                            "type": "status",
                            "data": manager.get_status_dict(),
                        })
                    )

                elif action == "resume":
                    if manager.state == SchedulerState.PAUSED:
                        manager.resume()
                    await websocket.send_text(
                        json.dumps({
                            "type": "status",
                            "data": manager.get_status_dict(),
                        })
                    )

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)
        logger.info(
            f"WebSocket client disconnected (total: {len(websocket_clients)})"
        )


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