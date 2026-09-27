#!/bin/bash
# Verify the Beans API endpoint

# AWS credentials
export AWS_ACCESS_KEY_ID="<YOUR_ACCESS_KEY_ID>"
export AWS_SECRET_ACCESS_KEY="<YOUR_SECRET_ACCESS_KEY>"
export AWS_SESSION_TOKEN="<YOUR_SESSION_TOKEN>"

AWS_REGION=us-east-1
CLUSTER=beans-api-cluster
SERVICE=beans-api-service

# Get public IP of the running task
TASK_ARN=$(aws ecs list-tasks \
  --cluster $CLUSTER --service-name $SERVICE \
  --query taskArns[0] --output text --region $AWS_REGION)

ENI_ID=$(aws ecs describe-tasks \
  --cluster $CLUSTER --tasks $TASK_ARN --region $AWS_REGION \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI_ID \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

echo "Service running at: http://$PUBLIC_IP:8000"

# Health check
curl http://$PUBLIC_IP:8000/health

# Predict with a sample bean image
curl -sL -o test.jpg \
  "https://huggingface.co/datasets/beans/resolve/main/data/test/angular_leaf_spot/angular_leaf_spot_test.0.jpg"

curl -X POST http://$PUBLIC_IP:8000/predict \
  -F "file=@test.jpg"
