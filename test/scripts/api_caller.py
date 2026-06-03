import urllib.request
import urllib.error
import json
import sys
import time

def call_api(url, token, device_id):
    if not token:
        print(f"SKIP")
        return

    timestamp = int(time.time() * 1000)
    data = json.dumps({
        "deviceId": device_id,
        "timestamp": timestamp,
        "metrics": {
            "temperature": 22.5,
            "humidity": 55.0,
            "location": "Factory-A"
        }
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token
        },
        method="POST"
    )

    try:
        res = urllib.request.urlopen(req)
        print(f"{res.status} {res.read().decode()}")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {e.read().decode()}")
    except Exception as e:
        print(f"ERROR {str(e)}")

def test_unauth(url):
    data = json.dumps({
        "deviceId": "DEV-UNAUTH",
        "timestamp": int(time.time() * 1000),
        "metrics": {}
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        res = urllib.request.urlopen(req)
        print(f"{res.status}")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {e.read().decode()}")
    except Exception as e:
        print(f"ERROR {str(e)}")

if __name__ == "__main__":
    mode    = sys.argv[1]
    url     = sys.argv[2]
    token   = sys.argv[3] if len(sys.argv) > 3 else ""
    device  = sys.argv[4] if len(sys.argv) > 4 else "DEV-001"

    if mode == "call":
        call_api(url, token, device)
    elif mode == "unauth":
        test_unauth(url)