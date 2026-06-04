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
MIIEowIBAAKCAQEAvn0eG7YGR3kxrLbp9ur8vp+jDFipmxQVEhsJ8kU0ve0tGS/e
O67vzBwF/SAJETXjkWuTzf4Q1NugUB9iBvxkyDhAzx38zMcIzMC0jdta/DhNI5hC
6cusDAJS2vGpMLdhR9bNSS5AhU+2XxwlLEsCjQ3RTry20xR9q4oK+RrM/UFJYBvR
UQQ09qCSwt/Kcj9eWrzTVP6ZTDdu1OOxVPIOVEtBX+Yk3cEvW6Mzy4EpMfTxZ2WW
ad85r0apNnqmv2vegNjGZEOXzmFeJnfwOOrvbudgLNDeOCW72rYIMGkSKILu2xZo
Mi+YSc2Z/vB9JUOv3VjhTEGrn3WJmR3hzVD6hwIDAQABAoIBAFKGEc0fhojgUEzq
0WFPXD+ZGSH4J0Iv6RD29dAneznszmTi//wLRYe/fDi08Dish/IwENBlCRWuMD2F
2wn7vg2fkTQpYaO1dnJ96bqrFTe/jGunQxXWTqrFNu/zUcDxMQvWWwkhKIKYjgGW
R+RweqJxIgRibTH05pyyKR7SJYxxRBTh83/SbF7eLaRA/t3x7TfobZTO+LMQ8fXJ
BHxZkEYKd/8mO9X2+nSCBgvTKOSlS4ukEPh6aofkLouACeLUiLZo7clZIUcgqgAs
lgqsU76QZ7ovrH5w1sy3AEUrvvZq8dXQJL3OFXvd45uCIQGmVnZhG2g9I7RxfT6M
/RnLjUECgYEA8moLZVL+lmqcg9KvCTEXNuNG7PGeY9BnltoDYwVk9p0pLBkpux1p
1tJoNlGRJSN1gEdzZZxEoSIZ0tRkgEicOu70yjojeToZQUOnsmXF1/jNFBMUSnjL
SpgKdp/Gp8wAorthyBIFgPS60TygG325x4bLqGCr4WIzthh5+6PueesCgYEAySoW
+4Vct9qeKnibMe+ROTHfmPE4afpj9aNaHjjGUxWaRj1yYLJk5y8GF/fxany7vkx0
ozy69Nxjh0GRO5K9pVi/FlQLZMMmj5HkmV5EoMbIOa7pvooSMKa9DU69pPxpHuO+
xfEbtP9ZVcQ1uUMQN9u2iddiCPsQeNS6J73UHtUCgYEAojUdTP6dBm9uLbMzlpX3
r62jDveagbW5KzLUo1S/u1lsbGqmBuPmp22BeB9aXRx+ColFCU/oiF22I+IlIcX0
bGbq+8qtY/fhYE9yDiiVmy+LoowlvrNXbKGSFtBQ8ITMRBfYlTSh5ClePJYxmFOn
lYB4FEIjoRvB+G4maaDG+WMCgYBsi8SY9a5BGrsLycZcXJutFAdF/KtnLA/yBLHk
6tfBD0AOtKtaGAiwYkRUfJqMzj90AMdTKbrr01v1KOEYFycz6D476x+2wEK3Z47F
XwODCaAS2BoSkWgdTmtmmd1lADosy9Et99rugHaQ++3NSK2gpnLJ0Cl7FRYfTRIh
zaF+/QKBgADWjd+RZPf6OtC38rkfIkDvV/jPJLdT2bBU8VsvTXZpsjrmgW+P0NoT
ZuKMh4WZb9Ed5lmXs34UFoo4ehSK5dpE2RpVazgDxZ4FLCQ2YEQv2ENlD8Gg9wp8
uDYY9E6tQd2OjP7cEqlnq4Ss8qYeye4fKnapy6SuT3D3tTzR4/rf
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