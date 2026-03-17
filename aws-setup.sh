#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  AI Receptionist — AWS Production Infrastructure Setup
#  Run this in AWS CloudShell (us-east-1)
# ═══════════════════════════════════════════════════════════

set -e

ACCOUNT_ID="041659741481"
REGION="us-east-1"
APP="med-receptionist-ai"
DB_PASSWORD=$(openssl rand -base64 24 | tr -d '+=/' | cut -c1-24)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " AI Receptionist — AWS Setup"
echo " Account: $ACCOUNT_ID | Region: $REGION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. ECR Repository ──────────────────────────────────────
echo ""
echo "1/7  Creating ECR repository..."
aws ecr create-repository \
  --repository-name "$APP-backend" \
  --region $REGION \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256 \
  --output text --query 'repository.repositoryUri' 2>/dev/null \
  || echo "     (already exists, skipping)"

ECR_URI=$(aws ecr describe-repositories \
  --repository-names "$APP-backend" \
  --region $REGION \
  --query 'repositories[0].repositoryUri' \
  --output text)
echo "     ✅ ECR: $ECR_URI"

# ── 2. S3 Bucket ───────────────────────────────────────────
echo ""
echo "2/7  Creating S3 bucket..."
aws s3api create-bucket \
  --bucket "$APP-frontend-prod" \
  --region $REGION 2>/dev/null || echo "     (already exists)"

aws s3api put-public-access-block \
  --bucket "$APP-frontend-prod" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,\
BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "     ✅ S3: $APP-frontend-prod"

# ── 3. RDS Security Group ──────────────────────────────────
echo ""
echo "3/7  Setting up networking..."
VPC_ID=$(aws ec2 describe-vpcs \
  --filters Name=isDefault,Values=true \
  --region $REGION \
  --query 'Vpcs[0].VpcId' --output text)

VPC_CIDR=$(aws ec2 describe-vpcs \
  --vpc-ids $VPC_ID --region $REGION \
  --query 'Vpcs[0].CidrBlock' --output text)

SG_ID=$(aws ec2 create-security-group \
  --group-name "med-receptionist-rds-sg" \
  --description "RDS - AI Receptionist" \
  --vpc-id $VPC_ID --region $REGION \
  --query 'GroupId' --output text 2>/dev/null) \
  || SG_ID=$(aws ec2 describe-security-groups \
       --filters Name=group-name,Values=med-receptionist-rds-sg \
       --region $REGION --query 'SecurityGroups[0].GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp --port 5432 \
  --cidr $VPC_CIDR \
  --region $REGION 2>/dev/null || true

echo "     ✅ VPC: $VPC_ID | SG: $SG_ID"

# ── 4. RDS Subnet Group ────────────────────────────────────
echo ""
echo "4/7  Creating RDS subnet group..."
SUBNETS=$(aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=$VPC_ID \
  --region $REGION \
  --query 'Subnets[*].SubnetId' \
  --output text)

aws rds create-db-subnet-group \
  --db-subnet-group-name "med-receptionist-subnet-group" \
  --db-subnet-group-description "AI Receptionist RDS" \
  --subnet-ids $SUBNETS \
  --region $REGION 2>/dev/null || echo "     (already exists)"

echo "     ✅ Subnet group ready"

# ── 5. RDS PostgreSQL ──────────────────────────────────────
echo ""
echo "5/7  Creating RDS PostgreSQL t3.micro (takes ~5 mins)..."
echo "     DB Password: $DB_PASSWORD  ← SAVE THIS NOW"

aws rds create-db-instance \
  --db-instance-identifier "med-receptionist-prod" \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --engine-version "16.3" \
  --master-username medadmin \
  --master-user-password "$DB_PASSWORD" \
  --allocated-storage 20 \
  --storage-type gp3 \
  --storage-encrypted \
  --vpc-security-group-ids $SG_ID \
  --db-subnet-group-name "med-receptionist-subnet-group" \
  --db-name "medreceptionist_prod" \
  --backup-retention-period 7 \
  --no-multi-az \
  --no-publicly-accessible \
  --deletion-protection \
  --region $REGION \
  --output text --query 'DBInstance.DBInstanceIdentifier' 2>/dev/null \
  || echo "     (already exists)"

echo "     ✅ RDS creation started (check status in ~5 mins)"
echo "     ⚠️  Save password: $DB_PASSWORD"

# ── 6. IAM User for GitHub Actions ────────────────────────
echo ""
echo "6/7  Creating GitHub Actions IAM user..."
aws iam create-user --user-name github-actions-deployer \
  --output text 2>/dev/null || echo "     (already exists)"

cat > /tmp/deploy-policy.json << POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken"],
      "Resource": "*"
    },
    {
      "Sid": "ECRPush",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:DescribeRepositories",
        "ecr:ListImages"
      ],
      "Resource": "arn:aws:ecr:$REGION:$ACCOUNT_ID:repository/$APP-backend"
    },
    {
      "Sid": "AppRunner",
      "Effect": "Allow",
      "Action": [
        "apprunner:UpdateService",
        "apprunner:DescribeService",
        "apprunner:ListServices",
        "apprunner:CreateService",
        "apprunner:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3Deploy",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObjectAcl"
      ],
      "Resource": [
        "arn:aws:s3:::$APP-frontend-prod",
        "arn:aws:s3:::$APP-frontend-prod/*"
      ]
    },
    {
      "Sid": "CloudFront",
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation"],
      "Resource": "*"
    }
  ]
}
POLICY

aws iam put-user-policy \
  --user-name github-actions-deployer \
  --policy-name GitHubActionsDeployPolicy \
  --policy-document file:///tmp/deploy-policy.json

echo "     ✅ IAM user created with deploy policy"

# ── 7. Access Keys ─────────────────────────────────────────
echo ""
echo "7/7  Generating access keys for GitHub Actions..."
KEYS=$(aws iam create-access-key \
  --user-name github-actions-deployer \
  --output json)

ACCESS_KEY=$(echo $KEYS | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AccessKey']['AccessKeyId'])")
SECRET_KEY=$(echo $KEYS | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AccessKey']['SecretAccessKey'])")

# ── Summary ────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅  SETUP COMPLETE — ADD THESE TO GITHUB SECRETS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo " AWS_ACCESS_KEY_ID     = $ACCESS_KEY"
echo " AWS_SECRET_ACCESS_KEY = $SECRET_KEY"
echo " AWS_ACCOUNT_ID        = $ACCOUNT_ID"
echo ""
echo " ECR_URI               = $ECR_URI"
echo " S3_BUCKET             = $APP-frontend-prod"
echo " DB_PASSWORD           = $DB_PASSWORD"
echo ""
echo " Next steps:"
echo "  1. Wait ~5 mins for RDS to become available"
echo "  2. Get RDS endpoint:  aws rds describe-db-instances --db-instance-identifier med-receptionist-prod --query 'DBInstances[0].Endpoint.Address' --output text"
echo "  3. Create App Runner service (run part 2 script)"
echo "  4. Create CloudFront distribution (run part 2 script)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
