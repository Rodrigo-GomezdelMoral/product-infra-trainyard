"""REQ-01, REQ-02: the training pipeline in Azure Machine Learning, four components on serverless compute.

Every node runs as the workspace's user-assigned identity, `id-trainyard-aml-<env>`: serverless compute has no
system-assigned identity and cannot pull from the admin-disabled shared registry as the submitter (ADR-006). The job
gets its name before submission, so `register` can tag the model with the job that produced it (REQ-01).
"""

from pathlib import Path
from typing import Any

from azure.ai.ml import Input, load_component
from azure.ai.ml.dsl import pipeline
from azure.ai.ml.entities import JobResourceConfiguration, ManagedIdentityConfiguration, PipelineJob

COMPONENTS, STEPS = Path(__file__).parent / "components", ("prep", "train", "evaluate", "register")
INSTANCE, EXPERIMENT = "Standard_F2s_v2", "trainyard-training"


def components() -> dict[str, Any]:
    return {step: load_component(source=COMPONENTS / f"{step}.yaml") for step in STEPS}


def build(
    steps: dict[str, Any], feed: str, name: str, identity: str, git_sha: str, champion: str | None = None
) -> PipelineJob:
    """`feed` and `champion` are asset references such as `azureml:fleet-feed:5` and `azureml:trainyard-risk:2`."""
    _, asset, version = feed.split(":")
    compared: dict[str, Any] = {}
    if champion:
        compared = {"champion": Input(type="mlflow_model", path=champion), "champion_version": champion.split(":")[2]}

    def training(feed: Input) -> None:
        prep = steps["prep"](feed=feed)
        train = steps["train"](train=prep.outputs.train, validation=prep.outputs.validation)
        evaluate = steps["evaluate"](model=train.outputs.model, holdout=prep.outputs.holdout, **compared)
        lineage = {"data_asset": asset, "data_version": version, "git_sha": git_sha, "pipeline_job": name}
        steps["register"](model=train.outputs.model, report=evaluate.outputs.report, **lineage)

    definition = pipeline(training, name="training", display_name="Trainyard training", default_compute="serverless")
    job = definition(feed=Input(type="uri_folder", path=feed))
    job.name, job.experiment_name = name, EXPERIMENT
    job.identity = ManagedIdentityConfiguration(client_id=identity)
    for node in job.jobs.values():
        node.resources = JobResourceConfiguration(instance_type=INSTANCE, instance_count=1)
        node.identity = ManagedIdentityConfiguration(client_id=identity)
    return job
