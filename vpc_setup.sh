#!/bin/bash
set -e

VPC=vpc-0d1fd0ba90c2b9a31
AR_ARN="arn:aws:apprunner:us-east-1:041659741481:service/med-receptionist-backend/7e834f3e0e5749c4a9573d1817a213d0"
REGION=us-east-1

echo "=== Step 1: Get subnets ==="
SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC" \
  --region $REGION \
  --query "Subnets[*].SubnetId" \
  --output text)
echo "Subnets: $SUBNETS"

echo "=== Step 2: Create/get security group ==="
SG=$(aws ec2 create-security-group \
  --group-name ar-connector-sg \
  --description "App Runner VPC connector SG" \
  --vpc-id $VPC \
  --region $REGION \
  --query GroupId \
  --output text 2>/dev/null) || true

if [ -z "$SG" ] || [[ "$SG" == *"error"* ]]; then
  SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=ar-connector-sg" "Name=vpc-id,Values=$VPC" \
    --region $REGION \
    --query "SecurityGroups[0].GroupId" \
    --output text)
fi
echo "Security Group: $SG"

echo "=== Step 3: Create VPC Connector ==="
VC_ARN=$(aws apprunner create-vpc-connector \
  --vpc-connector-name med-receptionist-vpc \
  --subnets $SUBNETS \
  --security-groups $SG \
  --region $REGION \
  --query "VpcConnector.VpcConnectorArn" \
  --output text)
echo "VPC Connector ARN: $VC_ARN"

echo "=== Step 4: Update App Runner service with VPC connector ==="
aws apprunner update-service \
  --service-arn "$AR_ARN" \
  --network-configuration "{\"EgressConfiguration\":{\"EgressType\":\"VPC\",\"VpcConnectorArn\":\"$VC_ARN\"}}" \
  --region $REGION \
  --query "Service.Status" \
  --output text

echo "=== Done! App Runner is updating. Wait ~2 minutes for it to restart ==="
