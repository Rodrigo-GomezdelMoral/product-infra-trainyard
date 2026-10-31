import json
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import yaml
from mlflow import MlflowClient

from ml.features import LABEL
from ml.pipeline import INSTANCE, build, components
from ml.score import Scorer
from ml.steps import COMPONENTS, LINEAGE, STEPS, evaluate, fit, gate, local, register, save
from ops.feed import write
from tests.conftest import LIMITS
from tests.doubles import START

TAGS = {"git_sha": "abc1234", "data_asset": "fleet-feed", "data_version": "5", "pipeline_job": "training-x"}


def test_environment_pins_match_the_laptop() -> None:
    lines = [line for name in ("requirements.txt", "requirements-dev.txt") for line in Path(name).read_text().split()]
    pins = {name: version for name, version in (line.split("==") for line in lines if "==" in line)}
    conda = yaml.safe_load((COMPONENTS.parent / "environment" / "conda.yaml").read_text())["dependencies"][-1]["pip"]
    shared = {name: version for name, version in (pin.split("==") for pin in conda) if name in pins}
    assert shared == {name: pins[name] for name in shared} and {"numpy", "pandas", "lightgbm", "mlflow"} <= set(shared)


def test_components_local(tmp_path: Path, tracking: None) -> None:
    write(tmp_path / "feed", START, 90)
    run = local(tmp_path / "feed", tmp_path / "run", validation_days="14", holdout_days="14", git_sha="abc1234")
    client = MlflowClient()
    runs = client.search_runs([experiment.experiment_id for experiment in client.search_experiments()])
    assert sorted((r.data.tags["step"], r.info.status) for r in runs) == sorted((s, "FINISHED") for s in STEPS)
    assert json.loads(Path(run["report"]).read_text(encoding="utf-8"))["gate"] == "passed"
    assert client.get_model_version("trainyard-risk", "1").tags["git_sha"] == "abc1234"
    train, validation = (pd.read_parquet(run[name]) for name in ("train", "validation"))
    again = [fit(train, validation, 42, 6, 0.6)[0].calibration for _ in range(2)]
    assert again == [Scorer.load(Path(run["model"])).calibration] * 2


def test_pipeline_builds() -> None:
    job = build(components(), "azureml:fleet-feed:5", "training-x", "aml-client-id", "abc1234", "azureml:model:2")
    spec, identity = job._to_dict(), {"type": "managed_identity", "client_id": "aml-client-id"}
    nodes, compute = spec["jobs"], {"default_compute": "serverless"}
    assert (list(nodes), spec["settings"], spec["name"], spec["identity"]) == (
        list(STEPS),
        compute,
        "training-x",
        identity,
    )
    assert all(n["identity"] == identity and n["resources"]["instance_type"] == INSTANCE for n in nodes.values())
    assert {str(n.component.environment.build.path) for n in job.jobs.values()} == {"../environment"}
    assert nodes["evaluate"]["inputs"]["model"] == {"path": "${{parent.jobs.train.outputs.model}}"}
    assert {name: nodes["register"]["inputs"][name] for name in LINEAGE} == TAGS
    alone = build(components(), "azureml:fleet-feed:5", "y", "id", "sha")._to_dict()["jobs"]["evaluate"]["inputs"]
    assert nodes["evaluate"]["inputs"]["champion_version"] == "2" and "champion" in nodes["evaluate"]["inputs"]
    assert not {"champion", "champion_version"} & set(alone)


def test_gate_refuses_worse(splits: dict[str, pd.DataFrame], model: Path, tmp_path: Path, tracking: None) -> None:
    train = splits["train"].assign(**{LABEL: np.random.default_rng(1).permutation(splits["train"][LABEL])})
    save(fit(train, splits["validation"], 42, 6, 0.6)[0], splits["validation"], tmp_path / "worse")
    report = evaluate(tmp_path / "worse", splits["holdout"], model, "7", LIMITS)
    assert report["gate"] == "failed" and "more than 0.02 below the champion's" in report["reasons"][-1]
    with mlflow.start_run():
        assert register(tmp_path / "worse", report, "trainyard-risk", dict.fromkeys(LINEAGE, "x")) is None
    assert not MlflowClient().search_registered_models()
    close = {"recall": 0.89, "precision": 0.7, "recall_series_b": 0.75, "champion_recall": 0.9}
    assert gate(close, LIMITS) == [] and gate(close | {"recall": 0.87}, LIMITS) == [
        "recall 0.870 is more than 0.02 below the champion's 0.900"
    ]


def test_register_tags_lineage(splits: dict[str, pd.DataFrame], model: Path, tracking: None) -> None:
    report = evaluate(model, splits["holdout"], model, "7", LIMITS)
    with mlflow.start_run():
        version = register(model, report, "trainyard-risk", TAGS)
    tags = MlflowClient().get_model_version("trainyard-risk", str(version)).tags
    assert {name: tags[name] for name in [*TAGS, "gate", "champion"]} == TAGS | {"gate": "passed", "champion": "7"}
    assert tags["recall"] == f"{report['metrics']['recall']:.4f}" and "champion_precision" in tags
    registered = Path(mlflow.artifacts.download_artifacts(f"models:/trainyard-risk/{version}"))
    assert Scorer.load(registered).calibration == Scorer.load(model).calibration


def test_gate_thresholds_match_the_component() -> None:
    inputs = yaml.safe_load((COMPONENTS / "evaluate.yaml").read_text(encoding="utf-8"))["inputs"]
    assert {name: inputs[name]["default"] for name in LIMITS} == LIMITS
