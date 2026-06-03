#!/usr/bin/env python3
"""
API Gateway Throttle Test
Fires concurrent requests and reports 202 vs 429 distribution
"""

import urllib.request
import urllib.error
import json
import time
import threading
import sys
import subprocess

# ── Config ────────────────────────────────────────────────────
STACK_NAME   = "DeviceTelemetrySaasStack"
REGION       = "us-east-1"
NUM_THREADS  = 50  # concurrent requests to fire

# ── Fetch stack outputs ───────────────────────────────────────
def get_stack_output(key):
    result = subprocess.run([
        'aws', 'cloudformation', 'describe-stacks',
        '--stack-name', STACK_NAME,
        '--region', REGION,
        '--query', f'Stacks[0].Outputs[?contains(OutputKey, `{key}`)].OutputValue',
        '--output', 'text'
    ], capture_output=True, text=True)
    return result.stdout.strip()

def get_token(user_pool_id, client_id, email, password):
    result = subprocess.run([
        'aws', 'cognito-idp', 'initiate-auth',
        '--auth-flow', 'USER_PASSWORD_AUTH',
        '--client-id', client_id,
        '--auth-parameters', f'USERNAME={email},PASSWORD={password}',
        '--region', REGION,
        '--output', 'json'
    ], capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        return data['AuthenticationResult']['IdToken']
    except Exception:
        return None

# ── Main ──────────────────────────────────────────────────────
def main():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║     API Gateway Throttle Test                ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # ── Resolve API URL ───────────────────────────────────────
    print("[1/3] Fetching stack config...")
    api_url_base = get_stack_output("TelemetryApiEndpoint")
    if not api_url_base:
        print("✗ Could not find TelemetryApiEndpoint in stack outputs.")
        sys.exit(1)
    api_url = api_url_base.rstrip('/') + '/devices' if not api_url_base.endswith('devices') else api_url_base

    user_pool_id   = get_stack_output("UserPoolId")
    user_client_id = get_stack_output("UserPoolClientId")

    print(f"  ✓ API URL       : {api_url}")
    print(f"  ✓ User Pool ID  : {user_pool_id}")
    print()

    # ── Get token ─────────────────────────────────────────────
    print("[2/3] Authenticating test user...")
    token = get_token(user_pool_id, user_client_id, "testdevice@example.com", "TestPass123!")
    if not token:
        print("✗ Could not retrieve ID token. Is the test user created?")
        print("  Run test-auth.sh first to create the user.")
        sys.exit(1)
    print(f"  ✓ Token retrieved: {token[:40]}...")
    print()

    # ── Fire concurrent requests ──────────────────────────────
    print(f"[3/3] Firing {NUM_THREADS} concurrent requests...")
    print()

    results  = {}
    lock     = threading.Lock()
    timings  = []

    def send(thread_id):
        data = json.dumps({
            "deviceId":  f"DEV-THROTTLE-{thread_id:03d}",
            "timestamp": int(time.time() * 1000),
            "metrics": {
                "temperature": round(20.0 + thread_id * 0.1, 1),
                "humidity":    50.0,
                "location":    "ThrottleTest"
            }
        }).encode()

        req = urllib.request.Request(
            api_url,
            data=data,
            headers={
                "Content-Type":  "application/json",
                "Authorization": "Bearer " + token
            },
            method="POST"
        )

        start = time.time()
        try:
            res = urllib.request.urlopen(req, timeout=10)
            status = str(res.status)
        except urllib.error.HTTPError as e:
            status = str(e.code)
        except Exception as e:
            status = f"ERR({str(e)[:30]})"
        elapsed = time.time() - start

        with lock:
            results[status] = results.get(status, 0) + 1
            timings.append(elapsed)

    # Launch all threads simultaneously
    threads = [threading.Thread(target=send, args=(i,)) for i in range(NUM_THREADS)]
    start_all = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_time = time.time() - start_all

    # ── Report ────────────────────────────────────────────────
    print("  Results:")
    print(f"  {'─' * 40}")

    total = sum(results.values())
    for status in sorted(results.keys()):
        count = results[status]
        pct   = count / total * 100
        bar   = '█' * int(pct / 2)
        label = {
            '202': '✓ Accepted',
            '429': '⚠ Throttled',
            '401': '✗ Unauthorised',
            '500': '✗ Server Error',
        }.get(status, f'  Status {status}')
        print(f"  {status} {label:<20} {count:>4} requests  ({pct:5.1f}%)  {bar}")

    print(f"  {'─' * 40}")
    print(f"  Total requests  : {total}")
    print(f"  Total time      : {total_time:.2f}s")
    if timings:
        print(f"  Avg latency     : {sum(timings)/len(timings)*1000:.0f}ms")
        print(f"  Min latency     : {min(timings)*1000:.0f}ms")
        print(f"  Max latency     : {max(timings)*1000:.0f}ms")
    print()

    # ── Verdict ───────────────────────────────────────────────
    throttled = results.get('429', 0)
    accepted  = results.get('202', 0)

    if throttled > 0:
        print(f"  ✓ Throttling is ACTIVE — {throttled} request(s) were rate limited")
    else:
        print(f"  ⚠ No throttling observed — try increasing NUM_THREADS at top of script")
        print(f"    Current burst limit may be higher than {NUM_THREADS} concurrent requests")

    if accepted > 0:
        print(f"  ✓ {accepted} request(s) accepted normally")

    print()

if __name__ == "__main__":
    main()