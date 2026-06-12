#!/usr/bin/env python3
"""run.py — Launcher for the API Request Scheduler backend."""

import sys
import uvicorn


def print_banner():
    """Print a styled startup banner."""
    banner = r"""
╔══════════════════════════════════════════════════════════════╗
║              API Request Scheduler v1.0                      ║
║                                                              ║
║  REST API:     http://localhost:8000                         ║
║  Swagger Docs: http://localhost:8000/docs                    ║
║  WebSocket:    ws://localhost:8000/ws                        ║
║                                                              ║
║  Endpoints:                                                  ║
║    GET  /          - Service info                            ║
║    GET  /status    - Scheduler status                        ║
║    POST /start     - Start scheduler                         ║
║    POST /stop      - Stop scheduler                          ║
║    POST /pause     - Pause scheduler                         ║
║    POST /resume    - Resume scheduler                        ║
║    POST /config    - Update configuration                    ║
║    GET  /endpoints - List configured APIs                    ║
║    POST /reset     - Reset counters                          ║
║    WS   /ws        - Real-time logs & control                ║
║                                                              ║
║  Configuration: api_config.json (101 SMS + 4 Call + 3 Email) ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def get_user_config() -> dict:
    """
    Parse optional command-line arguments for host, port, and reload mode.
    
    Usage:
        python run.py                          -> default 0.0.0.0:8000 with reload
        python run.py --host 127.0.0.1         -> custom host
        python run.py --port 9000              -> custom port
        python run.py --no-reload              -> disable auto-reload
        python run.py --host 0.0.0.0 --port 8080 --no-reload
    """
    config = {
        "host": "0.0.0.0",
        "port": 8000,
        "reload": True,
    }

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            config["host"] = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            try:
                config["port"] = int(args[i + 1])
                if config["port"] < 1 or config["port"] > 65535:
                    print(f"[!] Invalid port: {args[i+1]}. Using default 8000.")
                    config["port"] = 8000
            except ValueError:
                print(f"[!] Invalid port: {args[i+1]}. Using default 8000.")
                config["port"] = 8000
            i += 2
        elif args[i] == "--no-reload":
            config["reload"] = False
            i += 1
        else:
            print(f"[!] Unknown argument: {args[i]}")
            i += 1

    return config


def validate_config():
    """Check that api_config.json exists and is valid JSON before starting."""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent / "api_config.json"

    if not config_path.exists():
        print(f"[!] ERROR: api_config.json not found at {config_path}")
        print("[!] Please ensure api_config.json is in the same directory as run.py")
        sys.exit(1)

    try:
        with open(config_path, "r") as f:
            data = json.load(f)

        targets = data.get("targets", {})

        sms_count = len(targets.get("phone", {}).get("sms", []))
        call_count = len(targets.get("phone", {}).get("call", []))
        email_count = len(targets.get("email", {}).get("email", []))

        print(f"[✓] Loaded api_config.json:")
        print(f"    - SMS endpoints:   {sms_count}")
        print(f"    - Call endpoints:  {call_count}")
        print(f"    - Email endpoints: {email_count}")
        print(f"    - Total:           {sms_count + call_count + email_count}")

        if sms_count == 0 and call_count == 0 and email_count == 0:
            print("[!] WARNING: No endpoints found in config. Nothing to schedule.")
            print("[!] Add API entries under targets.phone.sms, targets.phone.call, or targets.email.email")

    except json.JSONDecodeError as e:
        print(f"[!] ERROR: api_config.json is not valid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[!] ERROR: Failed to parse api_config.json: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    print_banner()

    # Validate config file before starting server
    validate_config()

    # Get user config from command-line args
    config = get_user_config()

    host = config["host"]
    port = config["port"]
    reload_mode = config["reload"]

    print(f"[*] Starting server on {host}:{port}")
    print(f"[*] Auto-reload: {'ON' if reload_mode else 'OFF'}")
    print(f"[*] Press Ctrl+C to stop the server\n")

    try:
        uvicorn.run(
            "server:app",
            host=host,
            port=port,
            reload=reload_mode,
            log_level="info",
            access_log=True,
            use_colors=True,
        )
    except KeyboardInterrupt:
        print("\n[*] Server stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"[!] Server failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()