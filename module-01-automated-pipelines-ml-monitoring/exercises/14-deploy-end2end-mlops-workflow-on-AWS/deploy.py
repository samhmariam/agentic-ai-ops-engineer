"""
Deploy a trained FinBERT model and configure auto-scaling.

Run after the pipeline completes:
    python deploy.py --model-s3 <uri> --role <ARN> 
"""

import argparse
import json

import boto3
from sagemaker.core import image_uris
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.serve.model_builder import ModelBuilder

ENDPOINT_NAME = "finbert-sentiment-endpoint"


# https://docs.aws.amazon.com/sagemaker/latest/dg/how-it-works-modelbuilder-creation.html#how-it-works-modelbuilder-creation-deploy
def deploy_endpoint(role: str, model_s3: str, session: Session):
    region = session.boto_region_name

    inference_image = image_uris.retrieve(
        framework="huggingface",
        region=region,
        version="4.26.0",
        py_version="py39",
        base_framework_version="pytorch1.13.1",
        image_scope="inference",
        instance_type="ml.m5.large",
    )

    model_builder = ModelBuilder(
        s3_model_data_url=model_s3,
        image_uri=inference_image,
        role_arn=role,
        sagemaker_session=session,
        instance_type="ml.m5.large",
        env_vars={"HF_TASK": "text-classification"},
    )
    model_builder.build()
    predictor = model_builder.deploy(
        endpoint_name=ENDPOINT_NAME,
        initial_instance_count=1,
        instance_type="ml.m5.large",
        wait=True,
    )
    return predictor


# Configure a target-tracking auto-scaling policy on the endpoint.
#   - Metric  : SageMakerVariantInvocationsPerInstance: requests per instance per minute
#   - Target  : 1000 invocations/instance/min
#   - Min/Max : 1-4 instances
#   - ScaleOut cooldown : 60 s
#   - ScaleIn  cooldown : 300 s
def configure_autoscaling(endpoint_name: str, region: str):
    # https://docs.aws.amazon.com/boto3/latest/reference/services/application-autoscaling.html
    aas = boto3.client("application-autoscaling", region_name=region)
    resource_id = f"endpoint/{endpoint_name}/variant/AllTraffic"

    aas.register_scalable_target(
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        MinCapacity=1,
        MaxCapacity=4,
    )

    aas.put_scaling_policy(
        PolicyName=f"{endpoint_name}-target-tracking",
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        PolicyType="TargetTrackingScaling",
        TargetTrackingScalingPolicyConfiguration={
            "TargetValue": 1000.0,
            "PredefinedMetricSpecification": {
                "PredefinedMetricType": "SageMakerVariantInvocationsPerInstance",
            },
            "ScaleOutCooldown": 60,
            "ScaleInCooldown": 300,
        },
    )


# Send test requests and return the sentiment and confidence for each headline.
# https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-test-endpoints.html
def verify_endpoint(endpoint_name: str, region: str):
    runtime = boto3.client("sagemaker-runtime", region_name=region)
    test_inputs = [
        "The company reported record profits and strong revenue growth.",
        "The stock plummeted after missing earnings expectations.",
        "Trading volume remained steady with no major changes.",
    ]

    print("\nVerifying endpoint predictions:")
    response = runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/json",
        Accept="application/json",
        Body=json.dumps({"inputs": test_inputs}),
    )
    result = json.loads(response["Body"].read().decode("utf-8"))
    if not isinstance(result, list) or len(result) != len(test_inputs):
        raise ValueError("Expected one prediction per test input")

    id2label = {"0": "negative", "1": "neutral", "2": "positive"}
    predictions = []
    for text, pred in zip(test_inputs, result):
        if isinstance(pred, list):
            pred = max(pred, key=lambda item: item["score"])
        raw_label = str(pred["label"])
        label = id2label.get(raw_label.removeprefix("LABEL_"), raw_label)
        confidence = float(pred["score"])
        predictions.append({"text": text, "sentiment": label, "confidence": confidence})
        print(f"  [Sentiment: {label:8} - Confidence: {confidence:.2f}]  {text[:60]}")
    return predictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-s3", required=True,
                        help="S3 URI of model.tar.gz (from training job output)")
    parser.add_argument("--role", default=None)
    args = parser.parse_args()

    session = Session()
    role    = args.role or get_execution_role()
    region  = session.boto_region_name

    predictor = deploy_endpoint(role, args.model_s3, session)
    configure_autoscaling(predictor.endpoint_name, region)
    
    verify_endpoint(predictor.endpoint_name, region)

    print(f"\nDeployment complete.")
    print(f"Endpoint: {predictor.endpoint_name}")


if __name__ == "__main__":
    main()
