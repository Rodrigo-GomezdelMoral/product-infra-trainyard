"""REQ-04, REQ-06, REQ-08: the endpoint's scoring script and the gate's scorer, so the gate measures what serves.

Each unit gets its calibrated 7-day failure probability and every feature's exact contribution to it in log-odds:
LightGBM's own `pred_contrib`, scaled by the calibration, so the contributions and the base add up to the logit.
The module imports nothing from the repository: a deployment's snapshot is this folder alone (ADR-008).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, NamedTuple

import mlflow
import numpy as np
import pandas as pd
from azureml.ai.monitoring import Collector
from mlflow.models import Model


class Scorer(NamedTuple):
    model: Any
    features: list[str]
    calibration: dict[str, float]

    @classmethod
    def load(cls, path: Path) -> "Scorer":
        saved = Model.load(str(path))
        return cls(mlflow.lightgbm.load_model(str(path)), saved.signature.inputs.input_names(), saved.metadata or {})

    @property
    def threshold(self) -> float:
        return self.calibration["threshold"]

    def score(self, rows: pd.DataFrame) -> pd.DataFrame:
        scale, shift = self.calibration["scale"], self.calibration["shift"]
        contributions = scale * np.asarray(self.model.predict(rows[self.features], pred_contrib=True))
        logit = contributions.sum(axis=1) + shift
        return pd.DataFrame(contributions[:, :-1], columns=self.features, index=rows.index).assign(
            unit=rows["unit"], probability=1 / (1 + np.exp(-logit))
        )


class Serving(NamedTuple):
    scorer: Scorer
    version: str
    inputs: Any
    outputs: Any


SERVING: Serving


def init() -> None:
    global SERVING
    folder = Path(os.environ["AZUREML_MODEL_DIR"])
    report = logging.getLogger(__name__).warning
    inputs, outputs = (Collector(name=name, on_error=report) for name in ("model_inputs", "model_outputs"))
    SERVING = Serving(Scorer.load(next(folder.rglob("MLmodel")).parent), folder.name, inputs, outputs)


def run(raw_data: str) -> dict[str, Any]:
    rows = pd.DataFrame(json.loads(raw_data)["rows"])
    context = SERVING.inputs.collect(rows)
    scores = SERVING.scorer.score(rows)
    SERVING.outputs.collect(scores[["unit", "probability"]], context)
    return {
        "model_version": SERVING.version,
        "threshold": SERVING.scorer.threshold,
        "scores": scores.round(dict.fromkeys(SERVING.scorer.features, 4)).to_dict("records"),
    }
