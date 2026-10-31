"""REQ-01, REQ-05, REQ-06: the agent evaluation's checks, which read an answer and its tool results, never a model."""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from agent_framework import AgentResponse, Message

from app.agent import APPROVER, INSTRUCTIONS, Tools

NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
TOOLING = "\n".join([INSTRUCTIONS, *(str(member.__doc__) for member in vars(Tools).values() if callable(member))])
THRESHOLDS = yaml.safe_load((Path(__file__).parent / "thresholds.yaml").read_text(encoding="utf-8"))


def numbers(text: str) -> set[Decimal]:
    return {Decimal(n).normalize() for n in NUMBER.findall(text)}


def results(messages: list[Message], tool: str | None = None) -> list[str]:
    names = {c.call_id: c.name for m in messages for c in m.contents if c.type == "function_call"}
    found = [c for m in messages for c in m.contents if c.type == "function_result"]
    return [str(c.result) for c in found if tool in (None, names.get(c.call_id))]


def rows(text: str, week: list[dict[str, Any]]) -> bool:
    table = [line for line in text.splitlines() if "|" in line]
    found = [next((i for i, row in enumerate(table) if unit["unit"].split()[1] in row), -1) for unit in week]
    owned = all(i >= 0 and numbers(u["probability"]) <= numbers(table[i]) for i, u in zip(found, week, strict=True))
    return owned and found == sorted(set(found))


def checks(case: dict[str, Any], response: AgentResponse[Any], changes: list[str]) -> dict[str, bool]:
    text, messages = response.text, response.messages
    calls = [(c.name, c.parse_arguments() or {}) for m in messages for c in m.contents if c.type == "function_call"]
    fleet = [week for week in results(messages, "fleet_risk") if week.startswith("{")][: case.get("ranked", 0)]
    facts = [rows(text, json.loads(week)["inspect"]) for week in fleet]
    facts += [bool(re.search(p, text, re.I | re.S)) for p in case.get("mention", [])]
    facts += [not re.search(p, text, re.I | re.S) for p in case.get("forbid", [])]
    made = [(name, {k: str(v) for k, v in args.items()}) for name, args in calls]
    return {
        "tool_choice": all(any(n == m and a.items() <= b.items() for m, b in made) for n, a in case.get("tools", [])),
        "grounded": numbers(text) <= numbers("\n".join([case["query"], TOOLING, *results(messages)])),
        "facts": all(facts),
        "held": not changes and (case["role"] == APPROVER or not response.user_input_requests),
    }
