# Device Telemetry SaaS Platform

**Architecture, Deployment & Testing Guide**

**AWS Cloud & Platform Engineering**  
Version 1.0 | June 2026

---

## Technology Stack

| Layer              | Technology                          | Purpose |
|--------------------|-------------------------------------|---------|
| Ingestion (IoT)    | AWS IoT Core + X.509                | Device MQTT connectivity |
| Ingestion (API)    | API Gateway + Cognito               | Human & M2M REST ingestion |
| Auth               | Cognito + Lambda Authorizer         | JWT validation for all API calls |
| Processing         | Lambda + SQS                        | Async event processing |
| Metadata Store     | DynamoDB                            | Device events & processing status |
| Time-Series Store  | Amazon Timestream                   | Metric trends & analytics |
| Frontend           | S3 + CloudFront                     | Custom React dashboard |
| Monitoring         | Grafana on EC2 + ALB                | Production dashboards |
| Networking         | VPC + Private Subnets + Endpoints   | Zero-NAT secure serverless architecture |
| IaC                | AWS CDK (TypeScript)                | Full stack as code |

---

## 1. Architecture Overview

The Device Telemetry SaaS Platform is a fully serverless, event-driven architecture built on AWS. It supports two ingestion paths — a REST API for human users and M2M clients, and an MQTT path for IoT devices — both converging on a shared processing pipeline that writes to DynamoDB and Timestream.

### 1.1 Ingestion Paths

| Path            | Protocol     | Auth                              | Target |
|-----------------|--------------|-----------------------------------|--------|
| Human Users     | HTTPS REST   | Cognito ID Token (JWT)            | `POST /devices` |
| M2M Clients     | HTTPS REST   | Cognito Access Token (OAuth2)     | `POST /devices` |
| IoT Devices     | MQTT over TLS| X.509 Certificate                 | `devices/{deviceId}/telemetry` |

### 1.2 Data Flow

**IoT Device (MQTT/X.509)**
```
IoT Device → IoT Core → Topic Rule → IoT Lambda
                    ├── DynamoDB (raw event)
                    ├── SQS → Processor Lambda → DynamoDB (processed)
                    └── Timestream (metrics)
```

**Human/M2M (JWT/HTTPS)**
```
Client → API Gateway → Lambda Authorizer → API Lambda
                    ├── DynamoDB (raw event)
                    ├── SQS → Processor Lambda → DynamoDB (processed)
                    └── Timestream (metrics)
```

**Visualization**
- Custom Dashboard (S3 + CloudFront)
- Grafana (EC2 in private subnet + ALB)

### 1.3 Networking

All compute runs inside a VPC with private isolated subnets. AWS service calls use VPC endpoints to eliminate NAT Gateway costs.

### 1.4 Security Layers

| Layer   | Control                     | Detail |
|---------|-----------------------------|--------|
| Edge    | WAF + Managed Rules         | CommonRuleSet + rate limiting |
| API     | API Gateway throttling      | 100 req/s stage, 50 req/s POST |
| Auth    | Lambda Authorizer           | Validates ID & Access tokens |
| IoT     | X.509 certificates          | Per-device scoped policies |
| Network | Private subnets             | No public IPs on compute |
| Access  | SSM Session Manager         | No SSH, no bastion hosts |

---

## 2. Prerequisites

### 2.1 Local Tools

| Tool       | Version   | Link |
|------------|-----------|------|
| Node.js    | 20.x+     | [nodejs.org](https://nodejs.org) |
| AWS CDK    | 2.x+      | `npm install -g aws-cdk` |
| AWS CLI    | 2.x+      | [aws.amazon.com/cli](https://aws.amazon.com/cli) |
| Python     | 3.9+      | [python.org](https://python.org) |

### 2.2 AWS Account Requirements

- AWS account with programmatic access
- IAM user/role with `AdministratorAccess`
- CDK bootstrapped:
  ```bash
  cdk bootstrap aws://ACCOUNT_ID/us-east-1
  ```

---

## 3. Repository Structure

```bash
device-telemetry-saas/
├── bin/
│   └── device-telemetry-saas.ts
├── lib/
│   └── device-telemetry-saas-stack.ts
├── lambda/
│   ├── api/
│   ├── processor/
│   ├── iot/
│   ├── authorizer/
│   └── query/
├── frontend/
├── grafana-artifacts/
├── scripts/
│   ├── provision-grafana.py
│   ├── test-auth.sh
│   ├── test-iot.py
│   └── ...
├── package.json
└── cdk.json
```

---

## 4. Deployment Guide

### Step 1: Clone and Install
```bash
git clone <repo-url>
cd device-telemetry-saas
npm install
```

### Step 2: Configure AWS Credentials
```bash
aws configure
aws sts get-caller-identity
```

### Step 3: Bootstrap CDK
```bash
cdk bootstrap
```

### Step 4: Deploy
```bash
cdk synth
cdk deploy
```

### Step 5: Deploy Frontend
```bash
chmod +x scripts/deploy-frontend.sh
./scripts/deploy-frontend.sh
```

### Step 6: Provision Grafana Dashboard
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
python3 scripts/provision-grafana.py
```

**Grafana Login**:  
URL: `http://<ALB-DNS>`  
Credentials: `admin` / `TelemetryOS2026!`

---

## 5. Testing Guide

### 5.1 Authentication Test
```bash
chmod +x scripts/test-auth.sh
./scripts/test-auth.sh
```

### 5.2 IoT MQTT Test
```bash
pip install awsiotsdk
python3 scripts/test-iot.py
```

### 5.3 Throttling Test
```bash
python3 scripts/test-throttle.py
```

### 5.4 Verify Data in Timestream
```bash
aws timestream-query query \
  --query-string "SELECT * FROM \"telemetry_ts\".\"metrics\" WHERE time > ago(1h) ORDER BY time DESC LIMIT 20"
```

---

## 6. Stack Outputs

Key outputs include:
- `TelemetryApiEndpoint`
- `UserPoolId`, `UserPoolClientId`, `DeviceClientId`
- `GrafanaAlbUrl`
- `DashboardUrl`

---

## 7. Dashboards

### 7.1 Custom Dashboard (S3 + CloudFront)
Single-page React app with real-time metrics, trends, and alerts.

### 7.2 Grafana Dashboard

| Panel                    | Type        | Description |
|--------------------------|-------------|-----------|
| Avg Temperature          | Stat        | Last value with thresholds |
| Avg Humidity             | Stat        | Last value with thresholds |
| Active Devices           | Stat        | Count in last 5 minutes |
| Temperature Alerts       | Stat        | Count > 28°C in last 1h |
| Temperature by Device    | Time Series | 1m bins per device |
| Humidity by Device       | Time Series | 1m bins per device |
| Device Registry          | Table       | Last known state |
| Breach History           | Time Series | Temperature > 28°C events |

---

## 8. Teardown

```bash
cdk destroy
```

> **Warning**: This will permanently delete all data including DynamoDB tables and Timestream databases.

---

**Made with ❤️ for AWS IoT + Telemetry SaaS**
