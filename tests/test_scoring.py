import json
import logging
import os
import queue
import time
import urllib.request
from collections.abc import Callable
from logging.handlers import QueueHandler
from pathlib import Path
from shutil import copytree
from typing import Any

import numpy as np
import pandas as pd
import pytest
from azureml.ai.monitoring.init import teardown

from app.domain.fleet import plan
from app.domain.simulator import Feed
from ml import score
from ml.features import FEATURES, features
from tests.doubles import WEEK


@pytest.fixture
def body(feed: Feed) -> str:
    return json.dumps({"rows": features(feed.telemetry, feed.failures, WEEK).drop(columns="as_of").to_dict("records")})


@pytest.fixture
def served(model: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], dict[str, Any]]:
    url = os.environ.get("SCORING_URL", "")
    if not url:
        monkeypatch.setenv("AZUREML_MODEL_DIR", str(copytree(model, tmp_path / "trainyard-risk" / "7")))
        score.init()
        return score.run

    def post(raw: str) -> dict[str, Any]:
        request = urllib.request.Request(url, raw.encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as answer:
            return dict(json.load(answer))

    return post


def test_score_latency_local(served: Callable[[str], dict[str, Any]], body: str, feed: Feed) -> None:
    timings, answer = [], {}
    for _ in range(30):
        start = time.perf_counter()
        answer = served(body)
        timings.append(time.perf_counter() - start)
    scores = pd.DataFrame(answer["scores"])
    assert len(scores) == 40 and set(scores.columns) == {"unit", "probability", *FEATURES}
    assert scores["probability"].between(0, 1).all() and answer["model_version"] in ("7", "local")
    assert np.percentile(timings, 95) < 0.5, f"p95 {np.percentile(timings, 95):.3f} s"
    inspection = plan(features(feed.telemetry, feed.failures, WEEK), scores, answer["threshold"])
    assert "EMU 2417" in [unit.unit for unit in inspection.units] and all(u.signals for u in inspection.units)


def test_collector_logs(model: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    for name in ("AZUREML_MDC_ENABLED", "AZUREML_MDC_LOCAL_CAPTURE"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(copytree(model, tmp_path / "trainyard-risk" / "7")))
    score.init()
    captured: queue.Queue[logging.LogRecord] = queue.Queue()
    logging.getLogger("local.capture").addHandler(handler := QueueHandler(captured))
    score.run(body)
    payloads = sorted(captured.get(timeout=10).getMessage().split(" | ", 3)[1:] for _ in range(2))
    logging.getLogger("local.capture").removeHandler(handler)
    teardown(wait_for_flush=True)
    (inputs, context, rows), (outputs, same, scored) = payloads
    assert (inputs, outputs) == ("model_inputs", "model_outputs") and context == same
    assert set(pd.DataFrame(json.loads(rows)).columns) == {"unit", *FEATURES} and len(json.loads(scored)) == 40
