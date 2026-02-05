#!/usr/bin/env python3
"""
AaltoHub v2 - Crawler Auto Monitoring Script
Monitors crawler service status and logs to database
"""

import requests
import json
import time
import subprocess
from datetime import datetime

# Configuration
EC2_REMOTE_API = "http://63.180.156.219:9000/run"
SQL_PROXY_API = "http://63.180.156.219:9001"
AUTH_TOKEN = "Bearer manus-control-2026"
CHECK_INTERVAL = 60  # seconds

def check_crawler_status():
    """Check crawler service status via remote API"""
    try:
        response = requests.post(
            EC2_REMOTE_API,
            headers={
                "Content-Type": "application/json",
                "Authorization": AUTH_TOKEN
            },
            json={"cmd": "systemctl is-active aaltohub-crawler"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            status = data.get("stdout", "").strip()
            return {
                "status": status,
                "is_active": status == "active",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "error",
                "is_active": False,
                "error": f"HTTP {response.status_code}",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        return {
            "status": "error",
            "is_active": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def get_crawler_logs():
    """Get recent crawler logs"""
    try:
        response = requests.post(
            EC2_REMOTE_API,
            headers={
                "Content-Type": "application/json",
                "Authorization": AUTH_TOKEN
            },
            json={"cmd": "journalctl -u aaltohub-crawler -n 10 --no-pager"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("stdout", "")
        else:
            return f"Error: HTTP {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

def log_to_database(status_data):
    """Log crawler status to database"""
    try:
        sql = f"""
        INSERT INTO crawler_status (
            service_name,
            status,
            is_active,
            error_message,
            checked_at
        ) VALUES (
            'aaltohub-crawler',
            '{status_data['status']}',
            {status_data['is_active']},
            {f"'{status_data.get('error', '')}'" if status_data.get('error') else 'NULL'},
            NOW()
        );
        """
        
        response = requests.post(
            f"{SQL_PROXY_API}/execute",
            headers={"Content-Type": "application/json"},
            json={"sql": sql},
            timeout=10
        )
        
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to log to database: {e}")
        return False

def restart_crawler_if_failed(status_data):
    """Restart crawler if it's not active"""
    if not status_data['is_active']:
        print(f"⚠️  Crawler is {status_data['status']}, attempting restart...")
        
        try:
            response = requests.post(
                EC2_REMOTE_API,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": AUTH_TOKEN
                },
                json={"cmd": "sudo systemctl restart aaltohub-crawler"},
                timeout=30
            )
            
            if response.status_code == 200:
                print("✅ Crawler restart command sent")
                time.sleep(5)  # Wait for restart
                
                # Check status again
                new_status = check_crawler_status()
                print(f"   New status: {new_status['status']}")
                return new_status['is_active']
            else:
                print(f"❌ Restart failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Restart error: {e}")
            return False
    
    return True

def monitor_loop():
    """Main monitoring loop"""
    print("🔍 AaltoHub v2 Crawler Monitoring Started")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print("-" * 60)
    
    iteration = 0
    
    while True:
        iteration += 1
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Check #{iteration}")
        
        # Check status
        status = check_crawler_status()
        print(f"   Status: {status['status']}")
        print(f"   Active: {'✅' if status['is_active'] else '❌'}")
        
        # Log to database
        if log_to_database(status):
            print("   Logged to database: ✅")
        else:
            print("   Logged to database: ❌")
        
        # Auto-restart if failed
        if not status['is_active']:
            restart_crawler_if_failed(status)
        
        # Show recent logs if error
        if status['status'] in ['failed', 'error']:
            print("\n   Recent logs:")
            logs = get_crawler_logs()
            for line in logs.split('\n')[-5:]:
                if line.strip():
                    print(f"     {line}")
        
        # Wait for next check
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
