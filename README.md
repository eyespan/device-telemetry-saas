
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

