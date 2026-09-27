#!/bin/bash
# Deploy Beans API to AWS ECS with Auto-scaling.
set -euo pipefail

# Use credentials from the environment, an AWS profile, or an IAM role.
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export AWS_PAGER=""
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO=beans-api
CLUSTER=beans-api-cluster
SERVICE=beans-api-service
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPO}:latest"

# Create the ECR repository if it does not already exist.
REPOSITORY=$(aws ecr describe-repositories \
  --query "repositories[?repositoryName=='$ECR_REPO'].repositoryName | [0]" --output text)
if [ "$REPOSITORY" = "None" ]; then
  aws ecr create-repository --repository-name "$ECR_REPO"
fi

# Authenticate Docker to ECR, then build and publish the image.
aws ecr get-login-password --region "$AWS_REGION" | \
docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker build --platform linux/amd64 -t "$ECR_REPO:latest" "$SCRIPT_DIR"
docker tag "$ECR_REPO:latest" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws ecs create-cluster --cluster-name "$CLUSTER"

# Create the execution role if needed, and ensure it has the required policy.
ROLE_NAME=$(aws iam list-roles \
  --query "Roles[?RoleName=='ecsTaskExecutionRole'].RoleName | [0]" --output text)
if [ "$ROLE_NAME" = "None" ]; then
  aws iam create-role \
    --role-name ecsTaskExecutionRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
fi
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam wait role-exists --role-name ecsTaskExecutionRole

LOG_GROUP=$(aws logs describe-log-groups --log-group-name-prefix /ecs/beans-api \
  --query "logGroups[?logGroupName=='/ecs/beans-api'].logGroupName | [0]" --output text)
if [ "$LOG_GROUP" = "None" ]; then
  aws logs create-log-group --log-group-name /ecs/beans-api
fi

# Render a temporary copy, preserving the reusable task-definition template.
RENDERED_TASK=$(mktemp)
trap 'rm -f -- "$RENDERED_TASK"' EXIT
sed -e "s/\${AWS_ACCOUNT_ID}/${AWS_ACCOUNT_ID}/g" \
    -e "s/\${AWS_REGION}/${AWS_REGION}/g" \
    -e "s/\"awslogs-region\": \"us-east-1\"/\"awslogs-region\": \"${AWS_REGION}\"/g" \
    "$SCRIPT_DIR/task-definition.json" > "$RENDERED_TASK"
TASK_DEFINITION_ARN=$(aws ecs register-task-definition \
  --cli-input-json "file://$RENDERED_TASK" \
  --query taskDefinition.taskDefinitionArn --output text)

# Use a public subnet in the default VPC.
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
  --query 'Vpcs[0].VpcId' --output text)
if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
  echo "No default VPC exists in $AWS_REGION." >&2
  exit 1
fi
SUBNET_ID=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=default-for-az,Values=true" \
  --query 'Subnets[0].SubnetId' --output text)
if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "None" ]; then
  echo "No default subnet exists in $VPC_ID." >&2
  exit 1
fi

SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=beans-api-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG_ID" = "None" ]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name beans-api-sg \
    --description "Security group for Beans API ECS service" \
    --vpc-id "$VPC_ID" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0
fi

echo "Using SG: $SG_ID  Subnet: $SUBNET_ID"
NETWORK_CONFIGURATION="awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=ENABLED}"
SERVICE_STATUS=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].status' --output text)
if [ "$SERVICE_STATUS" = "ACTIVE" ]; then
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
    --task-definition "$TASK_DEFINITION_ARN" \
    --network-configuration "$NETWORK_CONFIGURATION" --force-new-deployment
elif [ "$SERVICE_STATUS" = "None" ] || [ "$SERVICE_STATUS" = "INACTIVE" ]; then
  aws ecs create-service --cluster "$CLUSTER" --service-name "$SERVICE" \
    --task-definition "$TASK_DEFINITION_ARN" --launch-type FARGATE \
    --desired-count 1 --network-configuration "$NETWORK_CONFIGURATION"
else
  echo "Cannot deploy while service status is $SERVICE_STATUS." >&2
  exit 1
fi

# Scale by one task at a time, with a longer scale-in cooldown.
RESOURCE_ID="service/$CLUSTER/$SERVICE"
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
  --resource-id "$RESOURCE_ID" --min-capacity 1 --max-capacity 4
SCALE_OUT_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
  --resource-id "$RESOURCE_ID" --policy-name beans-api-scale-out \
  --policy-type StepScaling \
  --step-scaling-policy-configuration '{"AdjustmentType":"ChangeInCapacity","StepAdjustments":[{"MetricIntervalLowerBound":0,"ScalingAdjustment":1}],"Cooldown":60,"MetricAggregationType":"Average"}' \
  --query PolicyARN --output text)
SCALE_IN_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
  --resource-id "$RESOURCE_ID" --policy-name beans-api-scale-in \
  --policy-type StepScaling \
  --step-scaling-policy-configuration '{"AdjustmentType":"ChangeInCapacity","StepAdjustments":[{"MetricIntervalUpperBound":0,"ScalingAdjustment":-1}],"Cooldown":300,"MetricAggregationType":"Average"}' \
  --query PolicyARN --output text)

aws cloudwatch put-metric-alarm --alarm-name beans-api-cpu-high \
  --namespace AWS/ECS --metric-name CPUUtilization --statistic Average \
  --dimensions "Name=ClusterName,Value=$CLUSTER" "Name=ServiceName,Value=$SERVICE" \
  --period 60 --evaluation-periods 1 --datapoints-to-alarm 1 \
  --threshold 70 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching --alarm-actions "$SCALE_OUT_ARN"
aws cloudwatch put-metric-alarm --alarm-name beans-api-cpu-low \
  --namespace AWS/ECS --metric-name CPUUtilization --statistic Average \
  --dimensions "Name=ClusterName,Value=$CLUSTER" "Name=ServiceName,Value=$SERVICE" \
  --period 60 --evaluation-periods 5 --datapoints-to-alarm 5 \
  --threshold 10 --comparison-operator LessThanThreshold \
  --treat-missing-data notBreaching --alarm-actions "$SCALE_IN_ARN"

aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
echo "Deployment complete: $CLUSTER/$SERVICE in $AWS_REGION."
