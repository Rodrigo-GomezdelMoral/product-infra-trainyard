"""REQ-01 to REQ-04: the training pipeline in Azure Machine Learning, its online deployment and its monitor.

Every node runs as the workspace's user-assigned identity, `id-trainyard-aml-<env>`: serverless compute has no
system-assigned identity and cannot pull from the admin-disabled shared registry as the submitter (ADR-006). The job
gets its name before submission, so `register` can tag the model with the job that produced it (REQ-01).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.ai.ml import Input, MLClient, load_component
from azure.ai.ml.dsl import pipeline
from azure.ai.ml.entities import (
    CodeConfiguration,
    DataCollector,
    DeploymentCollection,
    JobResourceConfiguration,
    ManagedIdentityConfiguration,
    ManagedOnlineDeployment,
    MonitorDefinition,
    MonitoringTarget,
    MonitorSchedule,
    PipelineJob,
    RecurrencePattern,
    RecurrenceTrigger,
    ServerlessSparkCompute,
)

COMPONENTS, STEPS = Path(__file__).parent / "components", ("prep", "train", "evaluate", "register")
INSTANCE, EXPERIMENT = "Standard_F2s_v2", "trainyard-training"
FEED, MODEL, MONITOR, SERVING = "fleet-feed", "trainyard-risk", "trainyard-monitor", "Standard_DS1_v2"


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


def submit(client: MLClient, endpoint: str, version: str, identity: str) -> dict[str, str]:
    """REQ-02: the components registered with image `version`, on the latest feed, against the model serving 100 %."""
    feed = client.data.get(FEED, label="latest")
    slot = next(
        (name for name, share in (client.online_endpoints.get(endpoint).traffic or {}).items() if share == 100), None
    )
    champion = str(client.online_deployments.get(slot, endpoint).model).rsplit("/", 1)[-1] if slot else None
    steps = {step: client.components.get(step, version=version) for step in STEPS}
    name, reference = f"training-{datetime.now(UTC):%Y%m%d%H%M%S}", f"azureml:{FEED}:{feed.version}"
    job = build(
        steps, reference, name, identity, version.rsplit("-", 1)[-1], champion and f"azureml:{MODEL}:{champion}"
    )
    created = client.jobs.create_or_update(job)
    return {
        "pipeline_job": str(created.name),
        "data_asset": FEED,
        "data_version": str(feed.version),
        "status": str(getattr(created.status, "value", created.status)),
    }


def deployment(client: MLClient, endpoint: str, slot: str, model: str, version: str) -> ManagedOnlineDeployment:
    """REQ-04, REQ-08: `ml/score.py` with the data collector, on the code and environment registered with `version`."""
    prep = client.components.get("prep", version=version)
    collector = DataCollector(
        {name: DeploymentCollection(enabled="true") for name in ("model_inputs", "model_outputs")}
    )
    return ManagedOnlineDeployment(
        name=slot,
        endpoint_name=endpoint,
        model=f"azureml:{MODEL}:{model}",
        environment=prep.environment,
        code_configuration=CodeConfiguration(code=prep.code, scoring_script="ml/score.py"),
        instance_type=SERVING,
        instance_count=1,
        app_insights_enabled=True,
        data_collector=collector,
    )


def monitor(endpoint: str, slot: str) -> MonitorSchedule:
    """REQ-04, ADR-010: out-of-box GA signals on serverless Spark, daily at 03:15 UTC."""
    target = MonitoringTarget(ml_task="classification", endpoint_deployment_id=f"azureml:{endpoint}:{slot}")
    definition = MonitorDefinition(
        compute=ServerlessSparkCompute(instance_type="standard_e4s_v3", runtime_version="3.4"), monitoring_target=target
    )
    daily = RecurrenceTrigger(frequency="day", interval=1, schedule=RecurrencePattern(hours=3, minutes=15))
    return MonitorSchedule(name=MONITOR, trigger=daily, create_monitor=definition)
