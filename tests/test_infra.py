"""REQ-04, REQ-07, REQ-08: the workbook and the alerts read what the app and the endpoint really emit."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TILES = json.loads((ROOT / "infra" / "workbook.json").read_text(encoding="utf-8"))
KPI_EVENTS = {"retrain_completed", "model_promoted", "model_evaluated", "model_rolled_back", "feedback_given"}


def emitted() -> dict[str, set[str]]:
    events: dict[str, set[str]] = {}
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            called = getattr(node, "func", None)
            if isinstance(node, ast.Call) and getattr(called, "attr", getattr(called, "id", "")) == "event":
                name = node.args[0]
                assert isinstance(name, ast.Constant) and isinstance(name.value, str), f"{path.name}:{node.lineno}"
                events.setdefault(name.value, set()).update(keyword.arg for keyword in node.keywords if keyword.arg)
    return events


def test_kpi_tiles_read_the_events_and_fields_the_app_sends() -> None:
    events, shown = emitted(), set()
    for tile in (tile for tile in TILES if "AppEvents" in tile["query"]):
        names = set(re.findall(r'"(\w+)"', " ".join(re.findall(r"Name (?:==|in) [^|]+", tile["query"]))))
        assert names and names <= events.keys(), tile["title"]
        assert set(re.findall(r"Properties\.(\w+)", tile["query"])) <= set().union(*(events[n] for n in names))
        shown |= names
    assert shown == KPI_EVENTS


def test_sla_tiles_follow_the_sli_definitions() -> None:
    availability, latency = (tile["query"] for tile in TILES[:2])
    assert availability.startswith("AmlOnlineEndpointTrafficLog") and "toint(ResponseCode) >= 500" in availability
    assert "toint(ResponseCode) in (408, 429)" in availability
    assert latency.startswith("AmlOnlineEndpointTrafficLog") and "percentile(TotalDurationMs, 95)" in latency


def test_failed_runs_reach_the_workbook_and_an_alert() -> None:
    assert any(tile["query"].startswith("AmlRunStatusChangedEvent") for tile in TILES)
    alerts = (ROOT / "infra" / "modules" / "monitor.bicep").read_text(encoding="utf-8")
    assert "query: 'AmlRunStatusChangedEvent | where Status == \"Failed\"'" in alerts
