**Device Telemetry SaaS Platform**

Architecture, Deployment & Testing Guide

*AWS Cloud & Platform Engineering*

Version 1.0 \| June 2026

| **Layer** | **Technology** | **Purpose** |
|----|----|----|
| Ingestion (IoT) | AWS IoT Core + X.509 | Device MQTT connectivity |
| Ingestion (API) | API Gateway + Cognito | Human & M2M REST ingestion |
| Auth | Cognito + Lambda Authorizer | JWT validation for all API calls |
| Processing | Lambda + SQS | Async event processing |
| Metadata Store | DynamoDB | Device events & processing status |
| Time-Series Store | Amazon Timestream | Metric trends & analytics |
| Frontend | S3 + CloudFront | Custom React dashboard |
| Monitoring | Grafana on EC2 + ALB | Production dashboards |
| Networking | VPC + Private Subnets + Endpoints | Zero-NAT secure server less architecture. Only Grafana on EC2 uses NAT securely to fetch binaries during bootstrap |
| IaC | AWS CDK (TypeScript) | Full stack as code |

# **1. Architecture Overview** {#architecture-overview}

The Device Telemetry SaaS Platform is a fully serverless, event-driven architecture built on AWS. It supports two ingestion paths --- a REST API for human users and M2M clients, and an MQTT path for IoT devices --- both converging on a shared processing pipeline that writes to DynamoDB and Timestream.

## **1.1 Ingestion Paths** {#ingestion-paths}

| **Path** | **Protocol** | **Auth** | **Target** |
|----|----|----|----|
| Human Users | HTTPS REST | Cognito ID Token (JWT) | POST /devices |
| M2M Clients | HTTPS REST | Cognito Access Token (OAuth2 client credentials) | POST /devices |
| IoT Devices | MQTT over TLS | X.509 Certificate | devices/{deviceId}/telemetry |

## **1.2 Data Flow** {#data-flow}

> IoT Device (MQTT/X.509)
>
> \|
>
> +\-- IoT Core \--\> Topic Rule \--\> IoT Lambda
>
> \|
>
> +\-- DynamoDB (raw event)
>
> +\-- SQS \--\> Processor Lambda
>
> \| \|
>
> \| +\-- DynamoDB (processed)
>
> +\-- Timestream (metrics)
>
> Human/M2M (JWT/HTTPS)
>
> \|
>
> +\-- API Gateway \--\> Lambda Authorizer \--\> API Lambda
>
> \|
>
> +\-- DynamoDB (raw event)
>
> +\-- SQS \--\> Processor Lambda
>
> \| \|
>
> \| +\-- DynamoDB (processed)
>
> +\-- Timestream (metrics)
>
> Visualisation
>
> +\-- Custom Dashboard (S3 + CloudFront)
>
> +\-- Grafana (EC2 private subnet + ALB)

## **1.3 Networking** {#networking}

All compute runs inside a VPC with private isolated subnets. AWS service calls use VPC endpoints to eliminate NAT Gateway costs and remove the internet as a failure point.

| **Endpoint** | **Type** | **Service** |
|----|----|----|
| DynamoDB | Gateway (free) | DynamoDB reads/writes |
| S3 | Gateway (free) | S3 reads/writes |
| SQS | Interface | Queue operations |
| Timestream Ingest | Interface | Write metrics |
| Timestream Query | Interface | Read metrics for dashboard |
| CloudWatch Logs | Interface | Lambda log delivery |
| SSM / SSM Messages / EC2 Messages | Interface | Session Manager access |

## **1.4 Security Layers** {#security-layers}

| **Layer** | **Control** | **Detail** |
|----|----|----|
| Edge | WAF + Managed Rules | AWSManagedRulesCommonRuleSet + IP rate limit 300 req/5min |
| API | API Gateway throttling | 100 req/s stage limit, 50 req/s on POST /devices |
| Auth | Lambda Authorizer | Validates both ID tokens (users) and access tokens (M2M) |
| IoT | X.509 certificates | Per-device certs, scoped IoT policy |
| Network | Private subnets | No public IPs on Lambda or EC2 |
| Access | SSM Session Manager | No SSH, no bastion, no keypairs |

# **2. Prerequisites** {#prerequisites}

## **2.1 Local Tools** {#local-tools}

| **Tool** | **Version** | **Install**                |
|----------|-------------|----------------------------|
| Node.js  | 20.x+       | https://nodejs.org         |
| AWS CDK  | 2.x+        | npm install -g aws-cdk     |
| AWS CLI  | 2.x+        | https://aws.amazon.com/cli |
| Python   | 3.9+        | https://python.org         |
|          |             |                            |

## **2.2 AWS Account Requirements** {#aws-account-requirements}

- AWS account with programmatic access configured

- IAM user or role with AdministratorAccess (or equivalent CDK deploy permissions)

- CDK bootstrapped in target region:

> cdk bootstrap aws://ACCOUNT_ID/us-east-1

# **3. Repository Structure** {#repository-structure}

> device-telemetry-saas/
>
> \|\-- bin/
>
> \| +\-- device-telemetry-saas.ts \# CDK app entry point
>
> \|\-- lib/
>
> \| +\-- device-telemetry-saas-stack.ts \# Full CDK stack
>
> \|\-- lambda/
>
> \| \|\-- api/index.js \# POST /devices ingest
>
> \| \|\-- processor/index.js \# SQS processor
>
> \| \|\-- iot/index.js \# IoT Core ingest
>
> \| \|\-- authorizer/index.js \# JWT Lambda authorizer
>
> \| +\-- query/index.js \# GET /metrics Timestream query
>
> \|\-- frontend/
>
> \| +\-- index.html \# Custom dashboard SPA
>
> \|\-- grafana-artifacts/
>
> \| \|\-- grafana-11.1.0-1.x86_64.rpm \# Grafana installer
>
> \| +\-- plugins/ \# Timestream plugin
>
> \|\-- scripts/
>
> \| \|\-- test-auth.sh \# Auth test script
>
> \| \|\-- test-iot.py \# IoT MQTT test
>
> \| \|\-- test-throttle.py \# Throttle test
>
> \| \|\-- deploy-frontend.sh \# Frontend deploy
>
> \| +\-- provision-grafana.py \# Grafana dashboard provisioner
>
> \|\-- package.json
>
> +\-- cdk.json

# **4. Step-by-Step Deployment Guide** {#step-by-step-deployment-guide}

## **Step 1 --- Clone and Install** {#step-1-clone-and-install}

> git clone \<repo-url\>
>
> cd device-telemetry-saas
>
> npm install

## **Step 2 --- Configure AWS Credentials** {#step-2-configure-aws-credentials}

> aws configure
>
> \# Enter: Access Key ID, Secret Access Key, Region (us-east-1), Output (json)
>
> \# Verify
>
> aws sts get-caller-identity

## **Step 3 --- Bootstrap CDK** {#step-3-bootstrap-cdk}

> cdk bootstrap

## **Step 4 --- Prepare Grafana Artifacts** {#step-4-prepare-grafana-artifacts}

Follow the steps in Section 2.3 to download and prepare the Grafana RPM and Timestream plugin before deploying.

## **Step 5 --- Synthesise and Deploy** {#step-5-synthesise-and-deploy}

> \# Synthesise CloudFormation template
>
> cdk synth
>
> \# Deploy full stack
>
> cdk deploy
>
> \# Deployment takes approximately 15-20 minutes
>
> \# Note the Outputs section at the end

## **Step 6 --- Note Stack Outputs** {#step-6-note-stack-outputs}

| **Output Key**       | **Description**                     |
|----------------------|-------------------------------------|
| TelemetryApiEndpoint | API Gateway base URL                |
| UserPoolId           | Cognito User Pool ID                |
| UserPoolClientId     | Cognito app client ID (human users) |
| DeviceClientId       | Cognito M2M client ID               |
| CognitoDomain        | Cognito hosted UI domain            |
| IotThingName         | IoT Thing name (demo-device-001)    |
| IotCertificatePem    | Device X.509 certificate            |
| IotPrivateKey        | Device private key                  |
| MetricsApiEndpoint   | Timestream query endpoint           |
| DashboardUrl         | CloudFront dashboard URL            |
| GrafanaAlbUrl        | Grafana ALB URL                     |
| GrafanaInstanceId    | EC2 instance ID for SSM access      |

## **Step 7 --- Deploy Frontend Dashboard** {#step-7-deploy-frontend-dashboard}

> chmod +x scripts/deploy-frontend.sh
>
> ./scripts/deploy-frontend.sh
>
> \# The script will:
>
> \# 1. Fetch stack outputs automatically
>
> \# 2. Upload index.html to S3
>
> \# 3. Set CloudFront default root object
>
> \# 4. Invalidate CloudFront cache

## **Step 8 --- Provision Grafana Dashboard** {#step-8-provision-grafana-dashboard}

> \# Create Python virtual environment
>
> python3 -m venv .venv
>
> source .venv/bin/activate
>
> pip install requests
>
> \# Provision datasource and dashboard
>
> python3 scripts/provision-grafana.py
>
> **[NOTE]{.mark}** *Grafana is accessible via the ALB URL on port 80. Default credentials: admin / TelemetryOS2026!*

# **5. Testing Guide** {#testing-guide}

## **5.1 Authentication Test** {#authentication-test}

Tests all three authentication flows: human user (ID token), M2M device (access token), and unauthenticated rejection.

> chmod +x scripts/test-auth.sh
>
> ./scripts/test-auth.sh

Expected output:

> \[4/6\] Testing human user authentication\...
>
> ✓ Human user authenticated
>
> \[5/6\] Testing M2M device authentication\...
>
> ✓ M2M device authenticated
>
> \[6/6\] Testing API calls\...
>
> ✓ Human user (ID token) -\> 202 {\"message\":\"Telemetry accepted\"}
>
> ✓ M2M device (access token) -\> 202 {\"message\":\"Telemetry accepted\"}
>
> ✓ Unauthenticated request correctly rejected -\> 401

## **5.2 IoT Core MQTT Test** {#iot-core-mqtt-test}

Simulates a physical device publishing telemetry via MQTT over TLS using X.509 certificate authentication.

> source .venv/bin/activate
>
> pip install awsiotsdk
>
> python3 scripts/test-iot.py

Expected output:

> \[3/4\] Fetching IoT endpoint\...
>
> ✓ Endpoint: xxxxxx-ats.iot.us-east-1.amazonaws.com
>
> \[4/4\] Publishing telemetry\...
>
> ✓ Connected to IoT Core
>
> ✓ Message 1/3 published -\> devices/demo-device-001/telemetry
>
> ✓ Message 2/3 published -\> devices/demo-device-001/telemetry
>
> ✓ Message 3/3 published -\> devices/demo-device-001/telemetry
>
> ✓ Disconnected cleanly

## **5.3 API Throttle Test** {#api-throttle-test}

Fires 50 concurrent requests to verify WAF rate limiting and API Gateway throttling are active.

> source .venv/bin/activate
>
> python3 scripts/test-throttle.py

Expected output shows a mix of 202 (accepted) and 429 (throttled) responses:

> 202 ✓ Accepted 38 requests (76.0%) ████████████████████████
>
> 429 ⚠ Throttled 12 requests (24.0%) ████████
>
> ✓ Throttling is ACTIVE

## **5.4 Timestream Data Verification** {#timestream-data-verification}

Verify data is flowing into Timestream from both ingestion paths.

> \# All data in last hour
>
> aws timestream-query query \\
>
> \--region us-east-1 \\
>
> \--query-string \"SELECT \* FROM \\telemetry_ts\\.\\metrics\\ WHERE time \> ago(1h) ORDER BY time DESC LIMIT 20\"
>
> \# Per-device summary
>
> aws timestream-query query \\
>
> \--region us-east-1 \\
>
> \--query-string \"SELECT deviceId, MAX(CASE WHEN measure_name = \'temperature\' THEN measure_value::double END) AS last_temp, MAX(time) AS last_seen FROM \\telemetry_ts\\.\\metrics\\ WHERE time \> ago(24h) GROUP BY deviceId ORDER BY last_seen DESC\"

## **5.5 DynamoDB Verification** {#dynamodb-verification}

> \# Get a specific device record
>
> aws dynamodb get-item \\
>
> \--table-name \<TABLE_NAME\> \\
>
> \--key \'{\"deviceId\":{\"S\":\"DEV-001\"},\"timestamp\":{\"S\":\"\<TIMESTAMP\"}}\'
>
> \# Scan for IoT-sourced records
>
> aws dynamodb scan \\
>
> \--table-name \<TABLE_NAME\> \\
>
> \--filter-expression \'#s = :src\' \\
>
> \--expression-attribute-names \'{\"#s\": \"source\"}\' \\
>
> \--expression-attribute-values \'{\":src\": {\"S\": \"iot-core\"}}\' \\
>
> \--query \'Count\'

## **5.6 SSM Access to Grafana EC2** {#ssm-access-to-grafana-ec2}

Access the private EC2 instance without SSH, keypair, or bastion host.

> aws ssm start-session \\
>
> \--target \$(aws cloudformation describe-stacks \\
>
> \--stack-name DeviceTelemetrySaasStack \\
>
> \--query \"Stacks\[0\].Outputs\[?OutputKey==\'GrafanaInstanceId\'\].OutputValue\" \\
>
> \--output text) \\
>
> \--region us-east-1
>
> \# Verify Grafana and plugin status inside the session
>
> sudo systemctl status grafana-server
>
> ls /var/lib/grafana/plugins/

# **6. Lambda Functions Reference** {#lambda-functions-reference}

| **Function** | **Trigger** | **Responsibilities** |
|----|----|----|
| ApiHandler | API Gateway POST /devices, GET /metrics, SQS | Ingest telemetry, query Timestream, process SQS batch |
| IotIngestHandler | IoT Core Topic Rule | Ingest MQTT telemetry from IoT devices |
| AuthorizerHandler | API Gateway TOKEN authorizer | Validate Cognito ID tokens and M2M access tokens |
| SqsProcessor | SQS event source | Update DynamoDB with processed status, write Timestream |
| QueryHandler | API Gateway GET /metrics | Execute Timestream queries for dashboard |

> **[NOTE]{.mark}** *All Lambdas run in private isolated subnets. AWS SDK calls route via VPC endpoints.*

# **7. Dashboards** {#dashboards}

## **7.1 Custom Dashboard (S3 + CloudFront)** {#custom-dashboard-s3-cloudfront}

A single-page React application served via CloudFront. Authenticates directly against Cognito using USER_PASSWORD_AUTH flow.

| **Panel** | **Description** |
|----|----|
| Stat Cards | Total devices, online count, avg temperature, active alerts |
| Metric Trends | Line chart with 1H/24H/7D toggle --- temperature and humidity per device |
| Device Registry | Table with last-seen status, metric chips colour-coded by threshold |
| Alert Log | CRITICAL/WARN entries for temperature \> 28 C or humidity \> 70% |

## **7.2 Grafana Dashboard (EC2 + ALB)** {#grafana-dashboard-ec2-alb}

Self-hosted Grafana running on a private EC2 instance behind an Application Load Balancer. Uses the grafana-timestream-datasource plugin.

| **Panel** | **Type** | **Query** |
|----|----|----|
| Avg Temperature | Stat | Last value from Timestream, threshold colour coding |
| Avg Humidity | Stat | Last value from Timestream, threshold colour coding |
| Active Devices | Stat | COUNT DISTINCT deviceId in last 5 minutes |
| Temperature Alerts | Stat | COUNT where temperature \> 28 C in last 1 hour |
| Temperature by Device | Time Series | AVG per device binned by 1 minute |
| Humidity by Device | Time Series | AVG per device binned by 1 minute |
| Device Registry | Table | Last known temperature, humidity and last seen per device |
| Breach History | Time Series | All readings where temperature exceeded 28 C |

# **8. Alert Thresholds** {#alert-thresholds}

| **Metric**     | **Warning**           | **Critical**              |
|----------------|-----------------------|---------------------------|
| Temperature    | \> 25 C               | \> 28 C                   |
| Humidity       | \> 60%                | \> 70%                    |
| Device offline | Not seen in 5 minutes | Not seen in 15 minutes    |
| Lambda errors  | 5 errors in 2 periods | CloudWatch Alarm triggers |

# **9. Scaling for Production** {#scaling-for-production}

## **9.1 Ingestion Layer** {#ingestion-layer}

- API Gateway scales automatically --- supports hundreds of thousands of requests per second

- Lambda scales horizontally with zero configuration

- IoT Core handles millions of concurrent device connections natively

- SQS acts as a buffer --- absorbs traffic spikes and prevents backpressure on ingestion

## **9.2 Data Layer** {#data-layer}

- DynamoDB PAY_PER_REQUEST --- scales horizontally without capacity planning

- Timestream is purpose-built for high-throughput metric ingestion from large device fleets

- For global deployments: DynamoDB Global Tables + Route 53 latency routing

## **9.3 Multi-Tenancy** {#multi-tenancy}

- API Gateway usage plans provide isolated quotas per customer or device fleet

- WAF rate rules prevent noisy tenants from impacting others

- Cognito User Pool resource servers scope M2M tokens per client

## **9.4 IoT Device Onboarding at Scale** {#iot-device-onboarding-at-scale}

- AWS IoT Fleet Provisioning for zero-touch certificate issuance

- IoT Device Defender for fleet-wide anomaly detection

- IoT Jobs for over-the-air firmware updates

# **10. Teardown** {#teardown}

> **[NOTE]{.mark}** *Running cdk destroy will delete all resources including DynamoDB data and Timestream metrics. This is irreversible.*
>
> \# Destroy full stack
>
> cdk destroy
>
> \# Clean up orphaned resources if needed
>
> aws ec2 describe-vpcs \--filters Name=tag:Name,Values=DeviceTelemetrySaasStack/AppVpc
>
> aws ec2 delete-vpc \--vpc-id \<VPC_ID\>
