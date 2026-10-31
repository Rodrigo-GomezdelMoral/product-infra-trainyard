"""REQ-01 to REQ-08 on Azure: the platform seam on Azure Machine Learning, its endpoint and the endpoint's traffic log.

The Azure ML SDK is synchronous, so each call runs in a worker thread. A deployment takes minutes: `deploy` starts it
and raises `NotReadyError` until it serves, and the promotion timer runs the step again (ADR-009).
"""

import asyncio
import io
from collections.abc import Callable, Coroutine
from datetime import UTC, timedelta
from itertools import takewhile
from os import environ
from typing import Any

import pandas as pd
from azure.ai.ml import MLClient
from azure.core import PipelineClient
from azure.core.exceptions import ResourceNotFoundError
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, RetryPolicy
from azure.core.rest import HttpRequest
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryResult
from azure.storage.blob import ContainerClient

from app.platform import Endpoint, Health, Model, NotReadyError, Run, Scores
from ml.features import FEATURES, features
from ml.pipeline import EXPERIMENT, FEED, MODEL, MONITOR, deployment, submit
from ml.pipeline import monitor as schedule

LINEAGE = ("data_asset", "data_version", "pipeline_job", "git_sha", "gate", "champion")
BREACH, SIGNALS = "azureml_modelmonitor_threshold_breached", "data drift, prediction drift, data quality"
WINDOW, AGREEMENT, SETTLED = timedelta(minutes=30), "trainyard-agreement", ("Succeeded", "Failed", "Canceled")
FINISHED = ("Completed", "Failed", "Canceled")
HEALTH = """AmlOnlineEndpointTrafficLog | where DeploymentName == '{slot}' and UserAgent != '{agreement}'
| summarize requests = count(), failed = countif(toint(ResponseCode) >= 500 or toint(ResponseCode) in (408, 429)),
  p95 = percentile(TotalDurationMs, 95), seconds = datetime_diff('second', max(TimeGenerated), min(TimeGenerated))
| project requests, failed, coalesce(todouble(p95), 0.0), coalesce(todouble(seconds), 0.0) / 60.0"""


def threaded[**P, T](work: Callable[P, T]) -> Callable[P, Coroutine[Any, Any, T]]:
    async def run(*args: P.args, **kwargs: P.kwargs) -> T:
        return await asyncio.to_thread(work, *args, **kwargs)

    return run


def model(found: Any) -> Model:
    tags: dict[str, str] = found.tags or {}
    metrics = {k: float(v) for k, v in tags.items() if k not in LINEAGE and v.replace(".", "", 1).isdigit()}
    return Model(str(found.version), metrics, {k: v for k, v in tags.items() if k in LINEAGE})


def stamp(found: Any) -> str:
    return str(found.creation_context.created_at.astimezone(UTC).isoformat())


class AzureML:
    def __init__(self) -> None:
        self.credential = DefaultAzureCredential()
        group, workspace = environ["AZURE_RESOURCE_GROUP"], environ["AML_WORKSPACE"]
        self.ml = MLClient(self.credential, environ["AZURE_SUBSCRIPTION_ID"], group, workspace)
        self.logs = LogsQueryClient(self.credential)
        self.name, self.version = environ["AML_ENDPOINT"], environ["ML_COMPONENT_VERSION"]
        self.feed: tuple[str, pd.DataFrame] = ("", pd.DataFrame())
        self.scoring: tuple[str, str, PipelineClient[Any, Any]] | None = None

    def target(self) -> tuple[str, str, PipelineClient[Any, Any]]:
        if self.scoring is None:
            found = self.ml.online_endpoints.get(self.name)
            policies = [RetryPolicy(), BearerTokenCredentialPolicy(self.credential, "https://ml.azure.com/.default")]
            uri = str(found.scoring_uri)
            self.scoring = (str(found.id), uri, PipelineClient(uri, policies=policies))
        return self.scoring

    @threaded
    def week(self) -> pd.DataFrame:
        asset = self.ml.data.get(FEED, label="latest")
        if asset.version != self.feed[0]:
            store, folder = str(asset.path).split("/datastores/")[1].split("/paths/")
            found: Any = self.ml.datastores.get(store)
            blobs = ContainerClient(
                f"https://{found.account_name}.blob.{found.endpoint}", found.container_name, self.credential
            )
            read = (
                blobs.download_blob(f"{folder.rstrip('/')}/{table}.parquet").readall()
                for table in ("telemetry", "failures")
            )
            telemetry, failures = (pd.read_parquet(io.BytesIO(data)) for data in read)
            as_of = telemetry["timestamp"].max().normalize() + pd.Timedelta(days=1)
            self.feed = (str(asset.version), features(telemetry, failures, as_of))
        return self.feed[1]

    @threaded
    def score(self, rows: pd.DataFrame, slot: str | None = None) -> Scores:
        _, uri, client = self.target()
        headers = {"Content-Type": "application/json", "User-Agent": AGREEMENT if slot else "trainyard"}
        body = f'{{"rows": {rows[["unit", *FEATURES]].to_json(orient="records")}}}'
        request = HttpRequest(
            "POST", uri, content=body, headers=headers | ({"azureml-model-deployment": slot} if slot else {})
        )
        response = client.send_request(request, connection_timeout=5, read_timeout=15)
        response.raise_for_status()
        found = response.json()
        return Scores(pd.DataFrame(found["scores"], index=rows.index), str(found["model_version"]), found["threshold"])

    @threaded
    def models(self) -> list[Model]:
        return [model(m) for m in sorted(self.ml.models.list(name=MODEL), key=lambda m: int(m.version or 0))]

    @threaded
    def endpoint(self) -> Endpoint:
        found = self.ml.online_endpoints.get(self.name)
        models = {d.name: str(d.model).rsplit("/", 1)[-1] for d in self.ml.online_deployments.list(self.name)}
        return Endpoint(models, dict(found.traffic or {}), dict(found.mirror_traffic or {}))

    @threaded
    def deploy(self, slot: str, version: str) -> None:
        try:
            found = self.ml.online_deployments.get(slot, self.name)
        except ResourceNotFoundError:
            found = None
        if found and found.provisioning_state == "Succeeded" and str(found.model).endswith(f"/{version}"):
            return
        if found is None or found.provisioning_state in SETTLED:
            self.ml.online_deployments.begin_create_or_update(
                deployment(self.ml, self.name, slot, version, self.version)
            )
        raise NotReadyError(
            f"Model {version} is being deployed to {slot}, about 10 minutes; the promotion then goes on."
        )

    @threaded
    def route(self, live: dict[str, int], mirror: dict[str, int]) -> None:
        found = self.ml.online_endpoints.get(self.name)
        found.traffic = (found.traffic or {}) | live
        found.mirror_traffic = mirror
        self.ml.online_endpoints.begin_create_or_update(found).result()

    @threaded
    def traffic(self, slot: str) -> list[Any]:
        result = self.logs.query_resource(
            self.target()[0], HEALTH.format(slot=slot, agreement=AGREEMENT), timespan=WINDOW
        )
        return list((result.tables if isinstance(result, LogsQueryResult) else result.partial_data)[0].rows[0])

    async def health(self, slot: str) -> Health:
        requests, failed, p95, minutes = await self.traffic(slot)
        champion, agreement = (await self.endpoint()).champion, None
        if champion not in (None, slot):
            rows = await self.week()
            flags = [
                s.frame["probability"] >= s.threshold
                for s in (await self.score(rows, slot), await self.score(rows, champion))
            ]
            agreement = round(float((flags[0] == flags[1]).mean()), 3)
        return Health(int(requests), int(failed), float(p95), round(float(minutes), 1), agreement)

    @threaded
    def delete(self, slot: str) -> None:
        self.ml.online_deployments.begin_delete(slot, self.name)

    @threaded
    def watch(self, slot: str) -> None:
        self.ml.schedules.begin_create_or_update(schedule(self.name, slot)).result()
        if environ["ENVIRONMENT"] != "production":
            self.ml.schedules.begin_disable(MONITOR).result()

    @threaded
    def retrain(self) -> dict[str, str]:
        return submit(self.ml, self.name, self.version, environ["AML_IDENTITY_CLIENT_ID"])

    @threaded
    def monitor(self) -> dict[str, str]:
        runs = sorted(
            (j for j in self.ml.jobs.list() if j.experiment_name == MONITOR and j.status in FINISHED), key=stamp
        )
        breach = list(takewhile(lambda job: BREACH in (job.tags or {}), reversed(runs)))
        last = {
            "run_date": stamp(runs[-1])[:10] if runs else "no run yet",
            "signals": SIGNALS,
            "breached": "yes" if breach else "none",
        }
        return last | ({"breached_at": stamp(breach[-1])} if breach else {})

    @threaded
    def runs(self, after: str) -> list[Run]:
        registered = {(m.tags or {}).get("pipeline_job"): m for m in self.ml.models.list(name=MODEL)}
        found: list[Run] = []
        for job in (j for j in self.ml.jobs.list() if j.experiment_name == EXPERIMENT and j.status == "Completed"):
            if (raw := registered.get(job.name)) and stamp(raw) > after:
                chosen, ended = model(raw), raw.creation_context.created_at
                minutes = round((ended - job.creation_context.created_at).total_seconds() / 60, 1)
                quality = [
                    chosen.metrics.get(f"champion_{k}", chosen.metrics.get(k, 0.0)) for k in ("recall", "precision")
                ]
                found.append(Run(str(job.name), stamp(raw), minutes, chosen.version, *quality))
        return found
