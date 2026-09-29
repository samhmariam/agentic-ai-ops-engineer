"""
SageMaker Pipeline

Steps:
  1. PreprocessData: downloads & splits financial headlines dataset
  2. TrainModel: fine-tunes FinBERT
  3. EvaluateModel: computes accuracy, writes evaluation.json
  4. CheckAccuracy: ConditionStep: if accuracy >= ACCURACY_THRESHOLD → RegisterModel
  5. RegisterModel: registers model to SageMaker Model Registry

Usage:
    python pipeline.py --role <SageMaker-execution-role-ARN>
"""

import argparse
from pathlib import Path

from sagemaker.core import image_uris
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.processing import ScriptProcessor
from sagemaker.core.shapes import (
    ProcessingInput,
    ProcessingS3Input,
    ProcessingOutput,
    ProcessingS3Output,
    OutputDataConfig,
)
from sagemaker.core.workflow.pipeline_context import PipelineSession
from sagemaker.mlops.workflow.condition_step import ConditionStep
from sagemaker.mlops.workflow.model_step import ModelStep
from sagemaker.mlops.workflow.pipeline import Pipeline
from sagemaker.mlops.workflow.steps import ProcessingStep, TrainingStep
from sagemaker.serve.model_builder import ModelBuilder
from sagemaker.train import ModelTrainer
from sagemaker.train.configs import Compute, InputData, SourceCode
from sagemaker.core.workflow.conditions import ConditionGreaterThanOrEqualTo
from sagemaker.core.workflow.functions import JsonGet
from sagemaker.core.workflow.properties import PropertyFile

MODEL_PACKAGE_GROUP = "FinBERTSentimentClassifiers"

# Minimum evaluation accuracy required for model registration.
ACCURACY_THRESHOLD = 0.80


def get_pipeline(role: str, bucket: str, session: PipelineSession, region: str) -> Pipeline:
    script_dir = Path(__file__).resolve().parent

    # Step 1: Preprocess
    print("Configuring preprocessing step...")
    preprocessor = ScriptProcessor(
        image_uri=image_uris.retrieve(
            framework="sklearn",
            region=region,
            version="1.2-1",
            py_version="py3",
            instance_type="ml.m5.large",
        ),
        command=["python3"],
        role=role,
        instance_count=1,
        instance_type="ml.m5.large",
        sagemaker_session=session,
        base_job_name="finbert-preprocess",
    )

    preprocess_step = ProcessingStep(
        name="PreprocessData",
        step_args=preprocessor.run(
            code=str(script_dir / "preprocess.py"),
            arguments=["--output-dir", "/opt/ml/processing/output"],
            outputs=[
                ProcessingOutput(
                    output_name=split,
                    s3_output=ProcessingS3Output(
                        s3_uri=f"s3://{bucket}/finbert/processed/{split}",
                        local_path=f"/opt/ml/processing/output/{split}",
                        s3_upload_mode="EndOfJob",
                    ),
                )
                for split in ("train", "valid", "test")
            ],
        ),
    )

    # Step 2: Train
    print("Configuring training step...")
    training_image = image_uris.retrieve(
        framework="huggingface",
        region=region,
        version="4.26.0",
        py_version="py39",
        base_framework_version="pytorch1.13.1",
        image_scope="training",
        instance_type="ml.g4dn.xlarge",
    )

    model_trainer = ModelTrainer(
        training_image=training_image,
        role=role,
        sagemaker_session=session,
        base_job_name="finbert-train",
        source_code=SourceCode(source_dir=str(script_dir), entry_script="train.py"),
        compute=Compute(instance_type="ml.g4dn.xlarge", instance_count=1),
        output_data_config=OutputDataConfig(s3_output_path=f"s3://{bucket}/finbert/output"),
        input_data_config=[
            InputData(
                channel_name=split,
                data_source=preprocess_step.properties.ProcessingOutputConfig.Outputs[split].S3Output.S3Uri,
                content_type="application/json",
            )
            for split in ("train", "valid")
        ],
    )

    training_step = TrainingStep(
        name="TrainModel",
        step_args=model_trainer.train(),
    )

    # Step 3: Evaluate 
    print("Configuring evaluation step...")
    evaluator = ScriptProcessor(
        image_uri=image_uris.retrieve(
            framework="huggingface",
            region=region,
            version="4.26.0",
            py_version="py39",
            base_framework_version="pytorch1.13.1",
            image_scope="inference",
            instance_type="ml.m5.large",
        ),
        command=["python3"],
        role=role,
        instance_count=1,
        instance_type="ml.m5.large",
        sagemaker_session=session,
        base_job_name="finbert-evaluate",
    )

    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )

    evaluation_step = ProcessingStep(
        name="EvaluateModel",
        step_args=evaluator.run(
            code=str(script_dir / "evaluate.py"),
            inputs=[
                ProcessingInput(
                    input_name="model",
                    s3_input=ProcessingS3Input(
                        s3_uri=training_step.properties.ModelArtifacts.S3ModelArtifacts,
                        local_path="/opt/ml/processing/model",
                        s3_data_type="S3Prefix",
                        s3_input_mode="File",
                    ),
                ),
                ProcessingInput(
                    input_name="test",
                    s3_input=ProcessingS3Input(
                        s3_uri=preprocess_step.properties.ProcessingOutputConfig.Outputs["test"].S3Output.S3Uri,
                        local_path="/opt/ml/processing/test",
                        s3_data_type="S3Prefix",
                        s3_input_mode="File",
                    ),
                ),
            ],
            outputs=[
                ProcessingOutput(
                    output_name="evaluation",
                    s3_output=ProcessingS3Output(
                        s3_uri=f"s3://{bucket}/finbert/evaluation",
                        local_path="/opt/ml/processing/evaluation",
                        s3_upload_mode="EndOfJob",
                    ),
                )
            ],
        ),
        property_files=[evaluation_report],
    )

    # ── Step 4: Register model (if accuracy meets threshold) ──────────────────
    print("Configuring register step...")

    # Retrieve inference image explicitly to avoid internal SDK version lookup issues
    inference_image = image_uris.retrieve(
        framework="huggingface",
        region=region,
        version="4.26.0",
        py_version="py39",
        base_framework_version="pytorch1.13.1",
        image_scope="inference",
        instance_type="ml.g4dn.xlarge",
    )

    model_builder = ModelBuilder(
        image_uri=inference_image,
        s3_model_data_url=training_step.properties.ModelArtifacts.S3ModelArtifacts,
        role_arn=role,
        sagemaker_session=session,
        instance_type="ml.g4dn.xlarge",
        env_vars={"HF_TASK": "text-classification"},
    )

    create_step = ModelStep(
        name="CreateModel",
        step_args=model_builder.build(),
    )

    register_step = ModelStep(
        name="RegisterModel",
        step_args=model_builder.register(
            model_package_group_name=MODEL_PACKAGE_GROUP,
            content_types=["application/json"],
            response_types=["application/json"],
            inference_instances=["ml.m5.large", "ml.g4dn.xlarge"],
            approval_status="Approved",
        ),
        depends_on=[create_step],
    )

    condition_step = ConditionStep(
        name="CheckAccuracy",
        conditions=[
            ConditionGreaterThanOrEqualTo(
                left=JsonGet(
                    step_name=evaluation_step.name,
                    property_file=evaluation_report,
                    json_path="metrics.accuracy.value",
                ),
                right=ACCURACY_THRESHOLD,
            )
        ],
        if_steps=[create_step, register_step],
        else_steps=[],
    )

    return Pipeline(
        name="FinBERTPipeline",
        steps=[preprocess_step, training_step, evaluation_step, condition_step],
        sagemaker_session=session,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default=None)
    parser.add_argument("--bucket", default=None)
    args = parser.parse_args()

    sagemaker_session = Session()
    pipeline_session = PipelineSession()
    role   = args.role or get_execution_role()
    bucket = args.bucket or sagemaker_session.default_bucket()
    region = sagemaker_session.boto_region_name

    print(f"Role   : {role}")
    print(f"Bucket : {bucket}")

    pipeline = get_pipeline(role=role, bucket=bucket, session=pipeline_session, region=region)
    pipeline.upsert(role_arn=role)

    print("Starting execution...")
    execution = pipeline.start()
    print(f"Execution ARN: {execution.arn}")
    execution.wait()
    print("Done.")


if __name__ == "__main__":
    main()
