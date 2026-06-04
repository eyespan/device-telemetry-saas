#!/usr/bin/env python3
"""
IoT Core MQTT Test Script
Simulates a device publishing telemetry via MQTT over TLS (X.509 cert auth)
"""

import subprocess
import sys
import os
import json
import time

# ── Install dependencies ──────────────────────────────────────
def install(pkg):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

try:
    from awscrt import mqtt
    from awsiot import mqtt_connection_builder
except ImportError:
    print("Installing awsiotsdk...")
    install("awsiotsdk")
    from awscrt import mqtt
    from awsiot import mqtt_connection_builder

try:
    import requests
except ImportError:
    install("requests")
    import requests

# ── Config ────────────────────────────────────────────────────
THING_NAME   = "demo-device-001"
TOPIC        = f"devices/{THING_NAME}/telemetry"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CERT_FILE    = os.path.join(SCRIPT_DIR, "device.pem")
KEY_FILE     = os.path.join(SCRIPT_DIR, "device.key")
CA_FILE      = os.path.join(SCRIPT_DIR, "AmazonRootCA1.pem")

# ── Write cert files ──────────────────────────────────────────
CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDWTCCAkGgAwIBAgIUTC4PHPl7akBuX7M6Ktv2mPG2yVkwDQYJKoZIhvcNAQEL
BQAwTTFLMEkGA1UECwxCQW1hem9uIFdlYiBTZXJ2aWNlcyBPPUFtYXpvbi5jb20g
SW5jLiBMPVNlYXR0bGUgU1Q9V2FzaGluZ3RvbiBDPVVTMB4XDTI2MDYwNDA4MzMz
NVoXDTQ5MTIzMTIzNTk1OVowHjEcMBoGA1UEAwwTQVdTIElvVCBDZXJ0aWZpY2F0
ZTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAL59Hhu2Bkd5May26fbq
/L6fowxYqZsUFRIbCfJFNL3tLRkv3juu78wcBf0gCRE145Frk83+ENTboFAfYgb8
ZMg4QM8d/MzHCMzAtI3bWvw4TSOYQunLrAwCUtrxqTC3YUfWzUkuQIVPtl8cJSxL
Ao0N0U68ttMUfauKCvkazP1BSWAb0VEENPagksLfynI/Xlq801T+mUw3btTjsVTy
DlRLQV/mJN3BL1ujM8uBKTH08WdllmnfOa9GqTZ6pr9r3oDYxmRDl85hXiZ38Djq
727nYCzQ3jglu9q2CDBpEiiC7tsWaDIvmEnNmf7wfSVDr91Y4UxBq591iZkd4c1Q
+ocCAwEAAaNgMF4wHwYDVR0jBBgwFoAUVvUsQrWV3PjsOEsJMEjAsJwlr+MwHQYD
VR0OBBYEFGc8T7rR0f5lqpm3yiuYdkRDHnk3MAwGA1UdEwEB/wQCMAAwDgYDVR0P
AQH/BAQDAgeAMA0GCSqGSIb3DQEBCwUAA4IBAQCSh+z6fsCogcb5SVBXJO0Yn5M8
OrUn/6NREcmW+D8TWEpmxgQ+stJNKmL4XT4wwBlNGAKTZ5FFNnnOdX78f32K2T+c
79i7o/nwQv7mwv2KnC00D8q73291K7njemV5BhfXoBVuvd/lZEYOCZBk4voRZp52
j4nQQCsCbVQX0nCZJnIiCmt8ZbCLK5PigABJ4WT1sR3pDzESxycIavzhiv/8lEHQ
G6hR6tfy2zmRluNR/BD+9bFFEEjqbGjtbu1LmRYf5cd4cguOoPaTcwp+6b5QdXAN
uQELeApSqakBv/5A8jIocTsP8SxH81zRv8pmX+SLRGHNlhyNEPGelTspwJDK
-----END CERTIFICATE-----"""

PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEogIBAAKCAQEA6Rf/+vaKJhne5gQLMnuGIjruyu9XQFR0aJOhngWk5/JMBsfF
gVnHS4KYiiqDwiRKRaPkKaykqBqxbDwPv7l2jEbBtNwMyY1KeGtpyg8wBxu7p0wn
oMvX9/Du5FcC8bTotR1wjpbTp04S81MXtZq9v8F2itrUvUGyA0Y1VVH7XqaOdRZg
qd7XowJYo0VpZBYhKob90CWt24TW5A9tTD1/DVqYIFeobCBpZ1fLH5hwGomjONp5
Zd0rJqKNoqMD/qZKOXdnJ6pKl891k4dYdhDW70kTkKXjee8zDHcskc5HjBk6Hy95
3X+Ucbdtj5qddnRwrGmx1fcfk6q/6HJPnkC+JQIDAQABAoIBAGGBl6RM85dipRqF
QIXapE63ZmLf4hjX+2Yvs6Dd7ZDVi7YeZWFpw/OzasoJZNqWwbcGCxDf1nU3zVZg
fZoPJCckBi35CyRZBXkAPd23orimgkZGliEuhGaEk/pS57limyIAcbBEKb/H6id9
b+KZG50Wedc2GV4eGDBEc1UAmW2K5JdYBFoZfcfN44t3CAcgbz8mXu2o0Hpp55Zm
Db8HQmDHJGZAtvUPNk4mlCGnW/eWGFLWdigGH3q2p+bie4S/KnM9ODSzH0USfF8B
tntee9cbNWBt/5gncPQxC83zUjCuBcHKCc+S+zdVK4JeegqCrlui2oZshe4xTi+G
BNUWpcECgYEA9FhbGJrNNbyppkfm9FroW749Df4iHzU+jg7BZgkkep9wk32Z8ySZ
1qr2PtJtz1DTM2izMHpT3IcDyUin4zuV6NLH4Cqdf/o0JFLtfbGwMTWeulRKZTsy
imQUVeN9hCVsokTB+Jmw5wP+h+7vNJXx2nGjYefRGsvF89/QJLAroNECgYEA9DZB
f6y0T15CGt0uCQgXXa6l29/MkvYl2C1kn/cDFCKsYs4m8eTn7WKk9ydJhYWJIT6C
6xGwSdNJK2jQvT7JFVb2sAxXrDzLB7rj2nCDgQWGyP7rZAqViocReh+HFLKBd2fV
lIX6XyeqUmjk4+n7PAM9aDALxpVYXow9nQBe/RUCgYAEjHCFsLwJOA3gbo46Fkcl
DhGM5SI1eoRDmLq474qiTb2GwVvQTuoeOOiEmt44ccS8vEI5sM1G2ayUXqnhbQaJ
YwMdhS2RaFL4KiMJp/kjsV/XECKiZ8u1D8/hGW8Iurme+7CwtAu7ATQHy8bgL7pk
2qCz/eDCovB4bb4uMKlfQQKBgH8GzbEEe1GhXM8uZyipfcXr9zfUREvZHzw/+ExA
puhNVM+cHaPLBlxy6A3q8JI0MG0LX/u32rO75B5hSdp2ExA3iN9vvBbKFG1z59sS
lUSCRGa+OmByJPDGau/UAGZip3cdmnnD6sSeFDkDeLOYXGcN5F4SR73Gpw2e8tl8
fOw1AoGAA4taX7rGJnlKFJOD1J/VdTNcQ5QLTNwHqbyE6G7tLNx9Mg7WHBSRloWT
/8JhhWt0YxOF/f0tqmPsvEWa/mdx1knBBw8jqah6pSEz4mV+UqNj8EtIrgFXvvA9
Ka9iUbKeW1Y6LuEJKNmDD1mKTbJWTpgZOIKpFOMZZ3zffI1CLHA=
-----END RSA PRIVATE KEY-----"""

def write_certs():
    with open(CERT_FILE, 'w') as f:
        f.write(CERT_PEM.strip())
    with open(KEY_FILE, 'w') as f:
        f.write(PRIVATE_KEY.strip())
    os.chmod(KEY_FILE, 0o600)
    print(f"  ✓ device.pem written")
    print(f"  ✓ device.key written")

def download_root_ca():
    if os.path.exists(CA_FILE):
        print(f"  ✓ AmazonRootCA1.pem already exists")
        return
    print("  Downloading Amazon Root CA...")
    r = requests.get("https://www.amazontrust.com/repository/AmazonRootCA1.pem")
    with open(CA_FILE, 'w') as f:
        f.write(r.text)
    print(f"  ✓ AmazonRootCA1.pem downloaded")

def get_iot_endpoint():
    result = subprocess.run(
        ['aws', 'iot', 'describe-endpoint',
         '--endpoint-type', 'iot:Data-ATS',
         '--query', 'endpointAddress',
         '--output', 'text'],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def publish_telemetry(endpoint, num_messages=3):
    print(f"\n  Connecting to {endpoint}...")

    connected = False
    connection = mqtt_connection_builder.mtls_from_path(
        endpoint=endpoint,
        cert_filepath=CERT_FILE,
        pri_key_filepath=KEY_FILE,
        ca_filepath=CA_FILE,
        client_id=THING_NAME,
        clean_session=True,
        keep_alive_secs=30,
    )

    connect_future = connection.connect()
    connect_future.result(timeout=10)
    print(f"  ✓ Connected to IoT Core")

    for i in range(num_messages):
        payload = {
            "timestamp": int(time.time() * 1000),
            "userId":    "iot-device",
            "metrics": {
                "temperature": round(20 + (i * 2.5), 1),
                "humidity":    round(50 + (i * 1.5), 1),
                "location":    "Factory-B"
            }
        }

        pub_future, _ = connection.publish(
            topic=TOPIC,
            payload=json.dumps(payload),
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )
        pub_future.result(timeout=10)

        print(f"  ✓ Message {i+1}/{num_messages} published → {TOPIC}")
        print(f"    temp={payload['metrics']['temperature']}°C  "
              f"humidity={payload['metrics']['humidity']}%")
        time.sleep(1)

    connection.disconnect().result()
    print(f"\n  ✓ Disconnected cleanly")

def verify_dynamodb():
    print("\n  Checking DynamoDB for IoT records...")
    result = subprocess.run([
        'aws', 'dynamodb', 'scan',
        '--table-name', 'DeviceTelemetrySaasStack-TelemetryTableB87F4322-1D4N3BRGPO7ZE',
        '--filter-expression', '#s = :src',
        '--expression-attribute-names', '{"#s": "source"}',
        '--expression-attribute-values', '{":src": {"S": "iot-core"}}',
        '--query', 'Count',
        '--output', 'text'
    ], capture_output=True, text=True)

    count = result.stdout.strip()
    if count and int(count) > 0:
        print(f"  ✓ Found {count} IoT record(s) in DynamoDB")
    else:
        print(f"  ⚠ No IoT records found yet — Lambda may still be processing")
        print(f"    Check CloudWatch: /aws/lambda/DeviceTelemetrySaasStack-IotIngestHandler*")

# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║     IoT Core MQTT Test — Device Telemetry   ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print("[1/4] Writing certificate files...")
    write_certs()

    print("\n[2/4] Downloading Amazon Root CA...")
    download_root_ca()

    print("\n[3/4] Fetching IoT endpoint...")
    endpoint = get_iot_endpoint()
    print(f"  ✓ Endpoint: {endpoint}")

    print(f"\n[4/4] Publishing telemetry to topic: devices/{THING_NAME}/telemetry")
    publish_telemetry(endpoint, num_messages=3)

    print("\n[Verification] Checking pipeline...")
    time.sleep(3)  # give Lambda time to process

    print("\n  Querying Timestream for IoT data...")
    subprocess.run([
        'aws', 'timestream-query', 'query',
        '--region', 'us-east-1',
        '--query-string',
        'SELECT deviceId, measure_name, measure_value::double, time '
        'FROM "telemetry_ts"."metrics" '
        'WHERE time > ago(5m) '
        'ORDER BY time DESC'
    ])

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║                  Summary                    ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"  Thing Name : demo-device-001")
    print(f"  Topic      : devices/demo-device-001/telemetry")
    print(f"  Endpoint   : {endpoint}")
    print(f"  Messages   : 3 published")
    print()
    print("  Check CloudWatch for Lambda logs:")
    print("  /aws/lambda/DeviceTelemetrySaasStack-IotIngestHandler*")
    print()