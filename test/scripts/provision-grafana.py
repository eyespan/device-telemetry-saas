#!/usr/bin/env python3
"""
Grafana Dashboard Provisioning Script
Provisions Timestream datasource and full telemetry dashboard
"""

import json
import urllib.request
import urllib.error
import sys

# ── Config ────────────────────────────────────────────────────
GRAFANA_URL   = "http://device-grafa-oc8l2ioyvysj-1884467095.us-east-1.elb.amazonaws.com"
GRAFANA_USER  = "admin"
GRAFANA_PASS  = "TelemetryOS2026!"
REGION        = "us-east-1"
TS_DATABASE   = "telemetry_ts"
TS_TABLE      = "metrics"

def api(method, path, data=None):
    url     = f"{GRAFANA_URL}{path}"
    body    = json.dumps(data).encode() if data else None
    headers = {
        "Content-Type":  "application/json",
        "Authorization": "Basic " + __import__('base64').b64encode(
            f"{GRAFANA_USER}:{GRAFANA_PASS}".encode()
        ).decode(),
    }
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req, timeout=10)
        return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP {e.code}: {e.read().decode()[:200]}")
        return None

print()
print("╔══════════════════════════════════════════════╗")
print("║   Grafana Dashboard Provisioner              ║")
print("╚══════════════════════════════════════════════╝")
print()

# ── Step 1: Verify connectivity ───────────────────────────────
print("[1/4] Connecting to Grafana...")
health = api("GET", "/api/health")
if not health:
    print(f"  ✗ Cannot connect to Grafana at {GRAFANA_URL}")
    sys.exit(1)
print(f"  ✓ Grafana {health.get('version','unknown')} is healthy")

# ── Step 2: Datasource ────────────────────────────────────────
print()
print("[2/4] Configuring Timestream datasource...")
existing = api("GET", "/api/datasources/name/Timestream")
if existing and existing.get("id"):
    ds_uid = existing["uid"]
    print(f"  ✓ Datasource exists (uid: {ds_uid})")
else:
    result = api("POST", "/api/datasources", {
        "name":      "Timestream",
        "type":      "grafana-timestream-datasource",
        "access":    "proxy",
        "isDefault": True,
        "jsonData":  {
            "defaultRegion":   REGION,
            "defaultDatabase": TS_DATABASE,
            "defaultTable":    TS_TABLE,
        }
    })
    if not result:
        print("  ✗ Failed to create datasource")
        sys.exit(1)
    ds_uid = result.get("datasource", {}).get("uid") or result.get("uid", "timestream")
    print(f"  ✓ Datasource created (uid: {ds_uid})")

def ds():
    return {"type": "grafana-timestream-datasource", "uid": ds_uid}

# ── Step 3: Build dashboard ───────────────────────────────────
print()
print("[3/4] Building dashboard...")

# Stat panel — last value
def stat_query(measure):
    return (
        f'SELECT measure_value::double AS {measure}, time '
        f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
        f'WHERE measure_name = \'{measure}\' '
        f'AND $__timeFilter '
        f'ORDER BY time DESC '
        f'LIMIT 1'
    )

# Time series — FIXED: Correct column order + Grafana macros
def timeseries_query(measure, interval="$__interval"):
    return (
        f'SELECT '
        f'  bin(time, {interval}) AS time, '
        f'  deviceId, '
        f'  AVG(measure_value::double) AS {measure} '
        f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
        f'WHERE measure_name = \'{measure}\' '
        f'  AND $__timeFilter '
        f'GROUP BY deviceId, bin(time, {interval}) '
        f'ORDER BY time ASC'
    )

dashboard = {
    "title":         "TelemetryOS — Device Intelligence",
    "tags":          ["telemetry", "iot"],
    "timezone":      "browser",
    "refresh":       "30s",
    "time":          {"from": "now-1h", "to": "now"},
    "schemaVersion": 38,
    "panels": [

        # Stat: Avg Temperature
        {
            "id": 1, "type": "stat",
            "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
            "title": "Avg Temperature",
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
            "targets": [{"datasource": ds(), "rawQuery": stat_query("temperature"), "refId": "A"}],
            "fieldConfig": {
                "defaults": {
                    "unit": "celsius", "decimals": 1,
                    "color": {"mode": "thresholds"},
                    "thresholds": {"mode": "absolute", "steps": [
                        {"color": "blue",   "value": None},
                        {"color": "green",  "value": 15},
                        {"color": "orange", "value": 25},
                        {"color": "red",    "value": 28},
                    ]}
                }
            }
        },

        # Stat: Avg Humidity
        {
            "id": 2, "type": "stat",
            "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
            "title": "Avg Humidity",
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
            "targets": [{"datasource": ds(), "rawQuery": stat_query("humidity"), "refId": "A"}],
            "fieldConfig": {
                "defaults": {
                    "unit": "percent", "decimals": 1,
                    "color": {"mode": "thresholds"},
                    "thresholds": {"mode": "absolute", "steps": [
                        {"color": "green",  "value": None},
                        {"color": "orange", "value": 60},
                        {"color": "red",    "value": 70},
                    ]}
                }
            }
        },

        # Stat: Active Devices
        {
            "id": 3, "type": "stat",
            "gridPos": {"x": 12, "y": 0, "w": 6, "h": 4},
            "title": "Active Devices (last 5m)",
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
            "targets": [{
                "datasource": ds(),
                "rawQuery": (
                    f'SELECT COUNT(DISTINCT deviceId) AS active_devices '
                    f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
                    f'WHERE $__timeFilter'
                ),
                "refId": "A",
            }],
            "fieldConfig": {"defaults": {"unit": "short"}}
        },

        # Stat: Temperature Alerts
        {
            "id": 4, "type": "stat",
            "gridPos": {"x": 18, "y": 0, "w": 6, "h": 4},
            "title": "Temp Alerts (last 1h)",
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
            "targets": [{
                "datasource": ds(),
                "rawQuery": (
                    f'SELECT COUNT(*) AS alerts '
                    f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
                    f'WHERE measure_name = \'temperature\' '
                    f'  AND measure_value::double > 28 '
                    f'  AND $__timeFilter'
                ),
                "refId": "A",
            }],
            "fieldConfig": {
                "defaults": {
                    "unit": "short",
                    "color": {"mode": "thresholds"},
                    "thresholds": {"mode": "absolute", "steps": [
                        {"color": "green", "value": None},
                        {"color": "red",   "value": 1},
                    ]}
                }
            }
        },

        # Time series: Temperature (FIXED)
        {
            "id": 5, "type": "timeseries",
            "gridPos": {"x": 0, "y": 4, "w": 12, "h": 9},
            "title": "Temperature by Device",
            "options": {
                "tooltip": {"mode": "multi"},
                "legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max", "min"]},
            },
            "targets": [{"datasource": ds(), "rawQuery": timeseries_query("temperature"), "refId": "A"}],
            "fieldConfig": {
                "defaults": {
                    "unit": "celsius",
                    "color": {"mode": "palette-classic"},
                    "custom": {"lineWidth": 2, "fillOpacity": 10, "spanNulls": True}
                }
            }
        },

        # Time series: Humidity (FIXED)
        {
            "id": 6, "type": "timeseries",
            "gridPos": {"x": 12, "y": 4, "w": 12, "h": 9},
            "title": "Humidity by Device",
            "options": {
                "tooltip": {"mode": "multi"},
                "legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max", "min"]},
            },
            "targets": [{"datasource": ds(), "rawQuery": timeseries_query("humidity"), "refId": "A"}],
            "fieldConfig": {
                "defaults": {
                    "unit": "percent",
                    "color": {"mode": "palette-classic"},
                    "custom": {"lineWidth": 2, "fillOpacity": 10, "spanNulls": True}
                }
            }
        },

        # Table: Device Registry
        {
            "id": 7, "type": "table",
            "gridPos": {"x": 0, "y": 13, "w": 24, "h": 8},
            "title": "Device Registry — Last Known State",
            "options": {"sortBy": [{"displayName": "Last Seen", "desc": True}]},
            "targets": [{
                "datasource": ds(),
                "rawQuery": (
                    f'SELECT deviceId, location, '
                    f'MAX(CASE WHEN measure_name = \'temperature\' THEN measure_value::double END) AS "Temperature (°C)", '
                    f'MAX(CASE WHEN measure_name = \'humidity\'    THEN measure_value::double END) AS "Humidity (%)", '
                    f'MAX(time) AS "Last Seen" '
                    f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
                    f'WHERE $__timeFilter '
                    f'GROUP BY deviceId, location '
                    f'ORDER BY "Last Seen" DESC'
                ),
                "refId": "A",
            }],
            "fieldConfig": { "defaults": {"custom": {"align": "left"} } }
        },

        # Breach History
        {
            "id": 8, "type": "timeseries",
            "gridPos": {"x": 0, "y": 21, "w": 24, "h": 8},
            "title": "Threshold Breach History — Temperature > 28°C",
            "options": {
                "tooltip": {"mode": "multi"},
                "legend": {"displayMode": "table", "placement": "right"},
            },
            "targets": [{
                "datasource": ds(),
                "rawQuery": (
                    f'SELECT time, measure_value::double AS temperature, deviceId '
                    f'FROM "{TS_DATABASE}"."{TS_TABLE}" '
                    f'WHERE measure_name = \'temperature\' '
                    f'  AND measure_value::double > 28 '
                    f'  AND $__timeFilter '
                    f'ORDER BY time ASC'
                ),
                "refId": "A",
            }],
            "fieldConfig": {
                "defaults": {
                    "unit": "celsius",
                    "color": {"fixedColor": "red", "mode": "fixed"},
                    "custom": {"lineWidth": 2, "fillOpacity": 20}
                }
            }
        },
    ]
}

print("  ✓ Dashboard JSON built — 8 panels")

# ── Step 4: Push dashboard ────────────────────────────────────
print()
print("[4/4] Pushing dashboard to Grafana...")

result = api("POST", "/api/dashboards/db", {
    "dashboard": dashboard,
    "folderId":  0,
    "overwrite": True,
    "message":   "Provisioned by deploy script",
})

if not result or result.get("status") != "success":
    print(f"  ✗ Failed: {result}")
    sys.exit(1)

dashboard_url = f"{GRAFANA_URL}{result.get('url', '')}"

print()
print("✅ Dashboard successfully provisioned!")
print(f"   Dashboard URL : {dashboard_url}")