# Module 29 - ML Pipelines on AWS SageMaker

## Overview

In this exercise you will build and run an end-to-end ML pipeline on AWS SageMaker. The pipeline preprocesses financial headlines, fine-tunes FinBERT, evaluates accuracy, and conditionally registers the model in the SageMaker Model Registry. You will then deploy the registered model to a managed endpoint, configure auto-scaling, and verify the endpoint.

---

## Prerequisites

Before running any scripts, you need a SageMaker Domain and Studio environment:

1. In the AWS Console, navigate to **SageMaker > Domains > Create domain**
2. Use **Quick setup** and select your default VPC and subnet

Read more: https://docs.aws.amazon.com/sagemaker/latest/dg/gs-studio-onboard.html

---

## 1. Complete `pipeline.py`

Complete the TODOs across all four pipeline steps. 

Run the pipeline:

```bash
python pipeline.py --role <SageMaker-execution-role-ARN>
```

Read more: https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html

---

## 2. Complete `deploy.py`

Once the pipeline completes and the model is registered, deploy it to a real-time endpoint. Complete the TODOs to:

- Build and deploy the model to a SageMaker managed endpoint
- Configure target-tracking auto-scaling (1 to 4 instances, target 1000 invocations/instance/min)
- Send test requests to verify the endpoint returns predictions

```bash
python deploy.py --model-s3 s3://<bucket>/finbert/output/<job>/output/model.tar.gz
```

Read more: https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints.html

---