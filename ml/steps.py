"""REQ-02, REQ-03: the four steps of the training pipeline, one per component, and a local run of all four.

`prep` builds feature rows with the function the app scores with and splits them by time; `train` fits, calibrates and
picks the operating point on validation; `evaluate` scores challenger and champion on the same holdout and decides the
gate; `register` registers only what passed, with its lineage. Each step's options come from its component spec, and
`local` runs the specs' own command lines, so a spec that does not match its step fails on a laptop first.
"""

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
import yaml
from mlflow.models import Model, infer_signature
from sklearn.linear_model import LogisticRegression

from ml.features import FEATURES, HORIZON, LABEL, training_rows
from ml.score import Scorer

COMPONENTS, STEPS = Path(__file__).parent / "components", ("prep", "train", "evaluate", "register")
WEEK, SERIES, TYPES = pd.Timedelta(days=7), {"a": 0, "b": 1}, {"integer": int, "number": float, "string": str}
LINEAGE = ("git_sha", "data_asset", "data_version", "pipeline_job")
LIMITS = ("min_recall", "min_precision", "min_series_recall", "max_recall_loss")
PARAMS: dict[str, Any] = {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 20}
PARAMS |= {"subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8}
PARAMS |= {"deterministic": True, "force_row_wise": True, "n_jobs": 1, "verbose": -1}


def spec(step: str) -> dict[str, Any]:
    return dict(yaml.safe_load((COMPONENTS / f"{step}.yaml").read_text(encoding="utf-8")))


def split(rows: pd.DataFrame, validation_days: int, holdout_days: int) -> dict[str, pd.DataFrame]:
    holdout = rows["as_of"].max() - pd.Timedelta(days=holdout_days - 1)
    validation = holdout - HORIZON - pd.Timedelta(days=validation_days)
    return {
        "train": rows.loc[rows["as_of"] < validation - HORIZON],
        "validation": rows.loc[rows["as_of"].between(validation, holdout - HORIZON, inclusive="left")],
        "holdout": rows.loc[rows["as_of"] >= holdout],
    }


def weekly_units(rows: pd.DataFrame, flagged: np.ndarray) -> int:
    weeks = (rows["as_of"] - rows["as_of"].min()).dt.days.to_numpy() // 7
    return int(rows.loc[flagged, "unit"].groupby(weeks[flagged]).nunique().max()) if flagged.any() else 0


def quality(rows: pd.DataFrame, probability: np.ndarray, threshold: float) -> dict[str, float]:
    flagged, positive, series = probability >= threshold, rows[LABEL].to_numpy() == 1, rows["series_b"].to_numpy()
    metrics = {f"recall_series_{name}": positive & (series == b) for name, b in SERIES.items()}
    metrics = {"recall": positive} | {name: members for name, members in metrics.items() if members.any()}
    measured = {name: float(flagged[members].mean()) if members.any() else 0.0 for name, members in metrics.items()}
    precision = float(positive[flagged].mean()) if flagged.any() else 0.0
    return measured | {"precision": precision, "weekly_units": float(weekly_units(rows, flagged))}


def operating_point(rows: pd.DataFrame, probability: np.ndarray, budget: int, min_precision: float) -> float:
    positive = rows[LABEL].to_numpy() == 1
    for threshold in np.unique(probability[positive]):
        flagged = probability >= threshold
        if weekly_units(rows, flagged) <= budget and positive[flagged].mean() >= min_precision:
            return float(threshold)
    return 1.0


def fit(
    train: pd.DataFrame, validation: pd.DataFrame, seed: int, budget: int, min_precision: float
) -> tuple[Scorer, dict[str, float]]:
    features = list(FEATURES)
    model = lgb.LGBMClassifier(random_state=seed, **PARAMS).fit(train[features], train[LABEL])
    raw = np.asarray(model.predict(validation[features], raw_score=True)).reshape(-1, 1)
    platt = LogisticRegression().fit(raw, validation[LABEL])
    scorer = Scorer(model, features, {"scale": float(platt.coef_[0, 0]), "shift": float(platt.intercept_[0])})
    probability = scorer.score(validation)["probability"].to_numpy()
    threshold = operating_point(validation, probability, budget, min_precision)
    calibrated = scorer._replace(calibration=scorer.calibration | {"threshold": threshold})
    return calibrated, quality(validation, probability, threshold)


def save(scorer: Scorer, rows: pd.DataFrame, path: Path) -> None:
    example = rows[scorer.features].head(5).astype(float)
    signature, metadata = infer_signature(example), scorer.calibration
    mlflow.lightgbm.save_model(scorer.model, str(path), signature=signature, input_example=example, metadata=metadata)


def measure(scorer: Scorer, rows: pd.DataFrame) -> dict[str, float]:
    return quality(rows, scorer.score(rows)["probability"].to_numpy(), scorer.threshold)


def gate(metrics: dict[str, float], limits: dict[str, float]) -> list[str]:
    floors = {"recall": limits["min_recall"], "precision": limits["min_precision"]}
    floors |= {name: limits["min_series_recall"] for name in metrics if name.startswith("recall_series")}
    below = {name: floor for name, floor in floors.items() if metrics[name] < floor}
    reasons = [f"{name.replace('_', ' ')} {metrics[name]:.3f} is below {floor}" for name, floor in below.items()]
    champion, loss = metrics.get("champion_recall"), limits["max_recall_loss"]
    if champion is not None and metrics["recall"] < champion - loss:
        reasons.append(f"recall {metrics['recall']:.3f} is more than {loss} below the champion's {champion:.3f}")
    return reasons


def evaluate(
    model: Path, holdout: pd.DataFrame, champion: Path | None, version: str | None, limits: dict[str, float]
) -> dict[str, Any]:
    metrics = measure(Scorer.load(model), holdout)
    if champion:
        metrics |= {f"champion_{name}": value for name, value in measure(Scorer.load(champion), holdout).items()}
    reasons = gate(metrics, limits)
    return {
        "gate": "failed" if reasons else "passed",
        "reasons": reasons,
        "champion": version or "",
        "metrics": metrics,
    }


def register(model: Path, report: dict[str, Any], name: str, lineage: dict[str, str]) -> str | None:
    if report["gate"] != "passed":
        return None
    saved = Model.load(str(model))
    info = mlflow.lightgbm.log_model(
        mlflow.lightgbm.load_model(str(model)),
        artifact_path="model",
        signature=saved.signature,
        input_example=saved.load_input_example(str(model)),
        metadata=saved.metadata,
    )
    tags = lineage | {"gate": "passed"} | ({"champion": report["champion"]} if report["champion"] else {})
    tags |= {metric: f"{value:.4f}" for metric, value in report["metrics"].items()}
    return str(mlflow.register_model(info.model_uri, name, tags=tags).version)


def run_prep(args: argparse.Namespace) -> None:
    feed = (pd.read_parquet(args.feed / f"{table}.parquet") for table in ("telemetry", "failures"))
    for name, rows in split(training_rows(*feed), args.validation_days, args.holdout_days).items():
        rows.to_parquet(getattr(args, name), index=False)
        mlflow.log_metrics({f"{name}_rows": len(rows), f"{name}_positives": int(rows[LABEL].sum())})
        mlflow.log_params({f"{name}_from": rows["as_of"].min().date(), f"{name}_to": rows["as_of"].max().date()})


def run_train(args: argparse.Namespace) -> None:
    train, validation = pd.read_parquet(args.train), pd.read_parquet(args.validation)
    scorer, metrics = fit(train, validation, args.seed, args.budget, args.min_precision)
    mlflow.log_params(PARAMS | {"seed": args.seed, "budget": args.budget, "min_precision": args.min_precision})
    mlflow.log_metrics({f"validation_{name}": value for name, value in metrics.items()} | scorer.calibration)
    save(scorer, validation, args.model)


def run_evaluate(args: argparse.Namespace) -> None:
    limits = {name: getattr(args, name) for name in LIMITS}
    report = evaluate(args.model, pd.read_parquet(args.holdout), args.champion, args.champion_version, limits)
    mlflow.log_metrics(report["metrics"])
    mlflow.log_params({"gate": report["gate"], "champion": report["champion"] or "none"} | limits)
    args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")


def run_register(args: argparse.Namespace) -> None:
    report = json.loads(args.report.read_text(encoding="utf-8"))
    version = register(args.model, report, args.model_name, {name: getattr(args, name) for name in LINEAGE})
    refused = "refused: " + "; ".join(report["reasons"])
    mlflow.log_params({"decision": f"registered {args.model_name} version {version}" if version else refused})


def local(feed: Path, out: Path, **given: str) -> dict[str, str]:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    values = {"feed": str(feed), "data_asset": "fleet-feed", "data_version": "local", "pipeline_job": "local"} | given
    for step in STEPS:
        component = spec(step)
        values |= {name: str(out / name) for name in component.get("outputs", {})}
        known = {name: str(io["default"]) for name, io in component["inputs"].items() if "default" in io} | values

        def keep(block: re.Match[str], known: dict[str, str] = known) -> str:
            return block[1] if set(re.findall(r"inputs\.(\w+)", block[1])) <= known.keys() else ""

        def fill(name: re.Match[str], known: dict[str, str] = known) -> str:
            return known[name[1]]

        command = shlex.split(re.sub(r"\$\[\[(.*?)\]\]", keep, component["command"], flags=re.S))
        subprocess.run(
            [sys.executable, *(re.sub(r"\$\{\{\w+\.(\w+)\}\}", fill, token) for token in command[1:])], check=True
        )
    return values


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ml.steps")
    steps = parser.add_subparsers(dest="step", required=True)
    for step in STEPS:
        component, options = spec(step), steps.add_parser(step)
        for name, io in (component["inputs"] | component.get("outputs", {})).items():
            options.add_argument(f"--{name.replace('_', '-')}", type=TYPES.get(io["type"], Path))
    options = steps.add_parser("local")
    for name in ("feed", "out", "git_sha", "champion", "champion_version", "validation_days", "holdout_days"):
        options.add_argument(f"--{name.replace('_', '-')}", required=name in ("feed", "out", "git_sha"))
    args = parser.parse_args(argv)
    if args.step == "local" and bool(args.champion) != bool(args.champion_version):
        parser.error("--champion and --champion-version go together")
    if args.step == "local":
        given = {name: value for name, value in vars(args).items() if value and name not in ("step", "feed", "out")}
        local(Path(args.feed), Path(args.out), **given)
        return
    with mlflow.start_run(tags={"step": args.step}):
        {"prep": run_prep, "train": run_train, "evaluate": run_evaluate, "register": run_register}[args.step](args)


if __name__ == "__main__":
    main()
