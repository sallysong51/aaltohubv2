#!/usr/bin/env python3
"""
AaltoHub v2 - Telegram Login Auto Monitoring Script
Monitors telegram login API endpoint and logs performance metrics
"""

import requests
import json
import time
from datetime import datetime
import statistics

# Configuration
FRONTEND_URL = "https://www.aaltohub.com"
API_PROXY_URL = f"{FRONTEND_URL}/api"
SQL_PROXY_API = "http://63.180.156.219:9001"
CHECK_INTERVAL = 30  # seconds

# Test endpoints
ENDPOINTS = [
    {"name": "Health Check", "path": "/health", "method": "GET"},
    {"name": "API Root", "path": "/", "method": "GET"},
]

def test_endpoint(endpoint):
    """Test a single API endpoint"""
    url = f"{API_PROXY_URL}{endpoint['path']}"
    method = endpoint['method']
    
    try:
        start_time = time.time()
        
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=endpoint.get('data', {}), timeout=10)
        
        response_time = (time.time() - start_time) * 1000  # ms
        
        return {
            "name": endpoint['name'],
            "url": url,
            "status_code": response.status_code,
            "response_time_ms": round(response_time, 2),
            "success": 200 <= response.status_code < 300,
            "timestamp": datetime.now().isoformat(),
            "error": None
        }
    except requests.exceptions.Timeout:
        return {
            "name": endpoint['name'],
            "url": url,
            "status_code": 0,
            "response_time_ms": 10000,
            "success": False,
            "timestamp": datetime.now().isoformat(),
            "error": "Timeout"
        }
    except Exception as e:
        return {
            "name": endpoint['name'],
            "url": url,
            "status_code": 0,
            "response_time_ms": 0,
            "success": False,
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

def test_frontend_load():
    """Test frontend page load time"""
    try:
        start_time = time.time()
        response = requests.get(FRONTEND_URL, timeout=10)
        load_time = (time.time() - start_time) * 1000  # ms
        
        return {
            "name": "Frontend Load",
            "url": FRONTEND_URL,
            "status_code": response.status_code,
            "response_time_ms": round(load_time, 2),
            "success": response.status_code == 200,
            "timestamp": datetime.now().isoformat(),
            "error": None
        }
    except Exception as e:
        return {
            "name": "Frontend Load",
            "url": FRONTEND_URL,
            "status_code": 0,
            "response_time_ms": 0,
            "success": False,
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

def log_to_database(result):
    """Log monitoring result to database"""
    try:
        error_msg = result.get('error', '')
        if error_msg:
            error_msg = error_msg.replace("'", "''")  # Escape single quotes
        
        sql = f"""
        INSERT INTO error_logs (
            service_name,
            error_type,
            error_message,
            request_url,
            response_time_ms,
            created_at
        ) VALUES (
            'telegram_login_monitor',
            '{result['name']}',
            '{error_msg if error_msg else 'Success'}',
            '{result['url']}',
            {result['response_time_ms']},
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

def calculate_stats(results):
    """Calculate statistics from results"""
    response_times = [r['response_time_ms'] for r in results if r['success']]
    
    if not response_times:
        return {
            "avg_response_time": 0,
            "min_response_time": 0,
            "max_response_time": 0,
            "success_rate": 0
        }
    
    success_count = sum(1 for r in results if r['success'])
    
    return {
        "avg_response_time": round(statistics.mean(response_times), 2),
        "min_response_time": round(min(response_times), 2),
        "max_response_time": round(max(response_times), 2),
        "success_rate": round((success_count / len(results)) * 100, 2)
    }

def monitor_loop():
    """Main monitoring loop"""
    print("🔍 AaltoHub v2 Telegram Login Monitoring Started")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Frontend: {FRONTEND_URL}")
    print(f"   API Proxy: {API_PROXY_URL}")
    print("-" * 60)
    
    iteration = 0
    all_results = []
    
    while True:
        iteration += 1
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Check #{iteration}")
        
        # Test frontend
        frontend_result = test_frontend_load()
        print(f"   Frontend: {frontend_result['response_time_ms']}ms - {'✅' if frontend_result['success'] else '❌'}")
        all_results.append(frontend_result)
        
        # Test API endpoints
        for endpoint in ENDPOINTS:
            result = test_endpoint(endpoint)
            status_icon = '✅' if result['success'] else '❌'
            print(f"   {result['name']}: {result['response_time_ms']}ms - {status_icon}")
            all_results.append(result)
            
            # Log to database if error
            if not result['success']:
                log_to_database(result)
        
        # Calculate and show stats every 10 iterations
        if iteration % 10 == 0:
            recent_results = all_results[-30:]  # Last 30 results
            stats = calculate_stats(recent_results)
            print(f"\n   📊 Stats (last 30 checks):")
            print(f"      Avg Response: {stats['avg_response_time']}ms")
            print(f"      Min/Max: {stats['min_response_time']}ms / {stats['max_response_time']}ms")
            print(f"      Success Rate: {stats['success_rate']}%")
        
        # Wait for next check
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
