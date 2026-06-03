#!/bin/bash

# ============================================================
# Frontend Deployment Script
# Uploads index.html to S3, sets CloudFront default root,
# and invalidates the cache
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

STACK_NAME="DeviceTelemetrySaasStack"
REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_FILE="$SCRIPT_DIR/index.html"

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║     Frontend Deployment — TelemetryOS       ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Preflight check ───────────────────────────────────────────
if [ ! -f "$FRONTEND_FILE" ]; then
  echo -e "${RED}✗ index.html not found at: $FRONTEND_FILE${NC}"
  echo -e "  Place index.html in the same folder as this script."
  exit 1
fi

echo -e "${BLUE}[1/5] Fetching stack outputs...${NC}"

STACK_OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output json 2>/dev/null)

if [ -z "$STACK_OUTPUTS" ] || [ "$STACK_OUTPUTS" == "null" ]; then
  echo -e "${RED}✗ Stack '$STACK_NAME' not found. Is it deployed?${NC}"
  exit 1
fi

DASHBOARD_URL=$(echo "$STACK_OUTPUTS" | python3 -c "
import json, sys
for o in json.load(sys.stdin):
    if o['OutputKey'] == 'DashboardUrl':
        print(o['OutputValue'])
        sys.exit(0)
print('')
")

echo -e "${GREEN}✓ Stack outputs fetched${NC}"
echo -e "  Dashboard URL : ${YELLOW}$DASHBOARD_URL${NC}"
echo ""

# ── Find S3 bucket ────────────────────────────────────────────
echo -e "${BLUE}[2/5] Locating S3 asset bucket...${NC}"

# Get bucket directly from stack resources — avoids matching CDK bootstrap bucket
BUCKET=$(aws cloudformation list-stack-resources \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "StackResourceSummaries[?ResourceType=='AWS::S3::Bucket'].PhysicalResourceId" \
  --output text 2>/dev/null | awk '{print $1}')

if [ -z "$BUCKET" ]; then
  echo -e "${RED}✗ Could not find S3 bucket in stack '$STACK_NAME'.${NC}"
  echo -e "  Run: aws cloudformation list-stack-resources --stack-name $STACK_NAME"
  exit 1
fi

echo -e "${GREEN}✓ Bucket found: ${YELLOW}$BUCKET${NC}"
echo ""

# ── Upload index.html ─────────────────────────────────────────
echo -e "${BLUE}[3/5] Uploading index.html to S3...${NC}"

aws s3 cp "$FRONTEND_FILE" "s3://$BUCKET/index.html" \
  --content-type "text/html" \
  --cache-control "no-cache, no-store, must-revalidate" \
  --region "$REGION"

echo -e "${GREEN}✓ index.html uploaded${NC}"
echo ""

# ── Find CloudFront distribution ──────────────────────────────
echo -e "${BLUE}[4/5] Configuring CloudFront distribution...${NC}"

DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, '${BUCKET}')].Id" \
  --output text 2>/dev/null)

# Fallback — get first distribution
if [ -z "$DIST_ID" ]; then
  DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[0].Id" \
    --output text 2>/dev/null)
fi

if [ -z "$DIST_ID" ] || [ "$DIST_ID" == "None" ]; then
  echo -e "${RED}✗ Could not find CloudFront distribution.${NC}"
  exit 1
fi

echo -e "  Distribution ID : ${YELLOW}$DIST_ID${NC}"

# Set default root object to index.html
ETAG=$(aws cloudfront get-distribution-config \
  --id "$DIST_ID" \
  --query 'ETag' \
  --output text)

aws cloudfront get-distribution-config \
  --id "$DIST_ID" \
  --query 'DistributionConfig' \
  --output json > /tmp/dist-config.json

# Update DefaultRootObject
python3 -c "
import json
with open('/tmp/dist-config.json') as f:
    config = json.load(f)
if config.get('DefaultRootObject') != 'index.html':
    config['DefaultRootObject'] = 'index.html'
    with open('/tmp/dist-config.json', 'w') as f:
        json.dump(config, f)
    print('UPDATED')
else:
    print('UNCHANGED')
" > /tmp/root-result.txt

ROOT_RESULT=$(cat /tmp/root-result.txt)

if [ "$ROOT_RESULT" == "UPDATED" ]; then
  aws cloudfront update-distribution \
    --id "$DIST_ID" \
    --distribution-config file:///tmp/dist-config.json \
    --if-match "$ETAG" > /dev/null
  echo -e "${GREEN}✓ Default root object set to index.html${NC}"
else
  echo -e "${GREEN}✓ Default root object already set${NC}"
fi
echo ""

# ── Invalidate cache ──────────────────────────────────────────
echo -e "${BLUE}[5/5] Invalidating CloudFront cache...${NC}"

INVALIDATION=$(aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/*" \
  --output json)

INVALIDATION_ID=$(echo "$INVALIDATION" | python3 -c "
import json, sys
print(json.load(sys.stdin)['Invalidation']['Id'])
")

echo -e "${GREEN}✓ Invalidation created: ${YELLOW}$INVALIDATION_ID${NC}"
echo ""

# ── Summary ───────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║                  Summary                    ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Bucket          : ${YELLOW}$BUCKET${NC}"
echo -e "  Distribution    : ${YELLOW}$DIST_ID${NC}"
echo -e "  Invalidation    : ${YELLOW}$INVALIDATION_ID${NC}"
echo -e "  Dashboard URL   : ${YELLOW}${DASHBOARD_URL}${NC}"
echo ""
echo -e "  ${GREEN}CloudFront propagation takes 1-2 minutes.${NC}"
echo -e "  Then open the dashboard URL above."
echo ""

# ── Optional: wait for invalidation ──────────────────────────
read -p "$(echo -e "${BLUE}Wait for CloudFront invalidation to complete? [y/N]: ${NC}")" WAIT
if [[ "$WAIT" =~ ^[Yy]$ ]]; then
  echo -e "${BLUE}Waiting for invalidation $INVALIDATION_ID...${NC}"
  aws cloudfront wait invalidation-completed \
    --distribution-id "$DIST_ID" \
    --id "$INVALIDATION_ID"
  echo -e "${GREEN}✓ Invalidation complete — dashboard is live!${NC}"
  echo ""
fi

echo -e "${GREEN}Done.${NC}"
echo ""