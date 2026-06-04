#!/bin/bash

# ============================================================
# Cognito Auth Test Script
# Tests both human user (ID token) and M2M (access token) flows
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

API_URL="https://6at4q1i7og.execute-api.us-east-1.amazonaws.com/prod/devices"
STACK_NAME="DeviceTelemetrySaasStack"
REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_CALLER="$SCRIPT_DIR/api_caller.py"

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║     Cognito Auth Test — Device Telemetry     ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Fetch stack outputs ───────────────────────────────
echo -e "${BLUE}[1/6] Fetching CDK stack outputs...${NC}"

STACK_OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output json 2>/dev/null)

if [ -z "$STACK_OUTPUTS" ] || [ "$STACK_OUTPUTS" == "null" ]; then
  echo -e "${RED}✗ Could not find stack '$STACK_NAME'. Is it deployed?${NC}"
  exit 1
fi

get_output() {
  echo "$STACK_OUTPUTS" | python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == '$1':
        print(o['OutputValue'])
        sys.exit(0)
print('')
"
}

USER_POOL_ID=$(get_output "UserPoolId")
USER_POOL_CLIENT_ID=$(get_output "UserPoolClientId")
DEVICE_CLIENT_ID=$(get_output "DeviceClientId")
COGNITO_DOMAIN=$(get_output "CognitoDomain")

if [ -z "$USER_POOL_ID" ]; then
  echo -e "${RED}✗ UserPoolId not found in stack outputs.${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Stack outputs fetched${NC}"
echo -e "  User Pool ID       : ${YELLOW}$USER_POOL_ID${NC}"
echo -e "  User Client ID     : ${YELLOW}$USER_POOL_CLIENT_ID${NC}"
echo -e "  Device Client ID   : ${YELLOW}$DEVICE_CLIENT_ID${NC}"
echo -e "  Cognito Domain     : ${YELLOW}$COGNITO_DOMAIN${NC}"
echo ""

# ── Step 2: Fetch device client secret ───────────────────────
echo -e "${BLUE}[2/6] Fetching device client secret...${NC}"

DEVICE_CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$DEVICE_CLIENT_ID" \
  --region "$REGION" \
  --query 'UserPoolClient.ClientSecret' \
  --output text 2>/dev/null)

if [ -z "$DEVICE_CLIENT_SECRET" ]; then
  echo -e "${RED}✗ Could not retrieve device client secret.${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Device client secret retrieved${NC}"
echo ""

# ── Step 3: Create test user ──────────────────────────────────
echo -e "${BLUE}[3/6] Setting up test user...${NC}"

TEST_EMAIL="testdevice@example.com"
TEST_PASSWORD="TestPass123!"

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$TEST_EMAIL" \
  --temporary-password "TempPass1!" \
  --message-action SUPPRESS \
  --region "$REGION" > /dev/null 2>&1 || true

aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$TEST_EMAIL" \
  --password "$TEST_PASSWORD" \
  --permanent \
  --region "$REGION" > /dev/null 2>&1 || true

echo -e "${GREEN}✓ Test user ready${NC}"
echo -e "  Email    : ${YELLOW}$TEST_EMAIL${NC}"
echo -e "  Password : ${YELLOW}$TEST_PASSWORD${NC}"
echo ""

# ── Step 4: Human user auth ───────────────────────────────────
echo -e "${BLUE}[4/6] Testing human user authentication...${NC}"

USER_AUTH_JSON=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$USER_POOL_CLIENT_ID" \
  --auth-parameters "USERNAME=$TEST_EMAIL,PASSWORD=$TEST_PASSWORD" \
  --region "$REGION" \
  --output json 2>&1)

ID_TOKEN=$(echo "$USER_AUTH_JSON" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d['AuthenticationResult']['IdToken'])
except:
    print('')
")

if [ -n "$ID_TOKEN" ]; then
  echo -e "${GREEN}✓ Human user authenticated${NC}"
  echo -e "  ID Token : ${YELLOW}${ID_TOKEN:0:40}...${NC}"
else
  echo -e "${RED}✗ Human user auth failed${NC}"
  echo "$USER_AUTH_JSON"
fi
echo ""

# ── Step 5: M2M auth ──────────────────────────────────────────
echo -e "${BLUE}[5/6] Testing M2M device authentication...${NC}"

M2M_JSON=$(curl -s -X POST "${COGNITO_DOMAIN}/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "${DEVICE_CLIENT_ID}:${DEVICE_CLIENT_SECRET}" \
  -d "grant_type=client_credentials&scope=telemetry-api/write")

M2M_TOKEN=$(echo "$M2M_JSON" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d['access_token'])
except:
    print('')
")

if [ -n "$M2M_TOKEN" ]; then
  echo -e "${GREEN}✓ M2M device authenticated${NC}"
  echo -e "  Access Token : ${YELLOW}${M2M_TOKEN:0:40}...${NC}"
else
  echo -e "${RED}✗ M2M auth failed${NC}"
  echo "$M2M_JSON"
fi
echo ""

# ── Step 6: API calls ─────────────────────────────────────────
echo -e "${BLUE}[6/6] Testing API calls...${NC}"
echo ""

call_and_report() {
  local label="$1"
  local token="$2"
  local device="$3"

  RESULT=$(python3 "$PY_CALLER" call "$API_URL" "$token" "$device")
  STATUS=$(echo "$RESULT" | cut -d' ' -f1)
  BODY=$(echo "$RESULT" | cut -d' ' -f2-)

  if [ "$STATUS" == "202" ]; then
    echo -e "  ${GREEN}✓ $label → $STATUS $BODY${NC}"
  elif [ "$RESULT" == "SKIP" ]; then
    echo -e "  ${YELLOW}⚠ $label → skipped (no token)${NC}"
  else
    echo -e "  ${RED}✗ $label → $STATUS $BODY${NC}"
  fi
}

call_and_report "Human user (ID token)    " "$ID_TOKEN"  "DEV-HUMAN-01"
call_and_report "M2M device (access token)" "$M2M_TOKEN" "DEV-M2M-01"

# Unauthenticated test
echo ""
echo -e "  Testing unauthenticated request (expect 401)..."
UNAUTH=$(python3 "$PY_CALLER" unauth "$API_URL")
UNAUTH_STATUS=$(echo "$UNAUTH" | cut -d' ' -f1)

if [ "$UNAUTH_STATUS" == "401" ]; then
  echo -e "  ${GREEN}✓ Unauthenticated request correctly rejected → 401${NC}"
else
  echo -e "  ${RED}✗ Expected 401, got → $UNAUTH${NC}"
fi

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║                  Summary                    ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  User Pool ID     : ${YELLOW}$USER_POOL_ID${NC}"
echo -e "  User Client ID   : ${YELLOW}$USER_POOL_CLIENT_ID${NC}"
echo -e "  Device Client ID : ${YELLOW}$DEVICE_CLIENT_ID${NC}"
echo -e "  Cognito Domain   : ${YELLOW}$COGNITO_DOMAIN${NC}"
echo ""
echo -e "${GREEN}Done.${NC}"