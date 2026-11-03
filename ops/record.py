"""Phase 9: records runs of the deployed system in the form the published demo replays (`web/src/demo/runs`).

The owner signs in to staging in a browser and passes that request's `Cookie` header in `TRAINYARD_COOKIE`; the run
keeps the roles the session really has. Every step is a real request, saved with its status, body and duration: the
run's question; `allow` or `refuse` for the tool calls the last answer asked to approve; `decide <approve|promote|
rollback|close>`; `wait <shadow|canary|window>`, which reads the promotion card every 30 seconds until it reaches that
step and is ready, and keeps only the last read. Nothing is edited.
"""

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

RUNS = Path(__file__).resolve().parent.parent / "web" / "src" / "demo" / "runs"


def exchange(client: httpx.Client, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    answer = client.request(method, path, json=body, timeout=900)
    kind, ms = answer.headers.get("content-type", "").split(";")[0], round(1000 * (time.perf_counter() - started))
    content = {"text": answer.text, "type": kind} if kind == "text/event-stream" else {"json": answer.json()}
    asked = {"request": body} if body is not None else {}
    return {"method": method, "path": path, "status": answer.status_code, "ms": ms} | asked | content


def fields(stream: str, event: str) -> list[Any]:
    return [json.loads(data) for data in re.findall(rf"event: {event}\r?\ndata: (.+)", stream)]


def reached(read: dict[str, Any], step: str) -> bool:
    card = read["json"].get("card") or {}
    return bool(card.get("step") == step and card.get("facts", {}).get("ready", True))


def record(client: httpx.Client, question: str, steps: list[str]) -> list[dict[str, Any]]:
    done = [exchange(client, "POST", "/api/chat", {"message": question})]
    conversation = fields(done[0]["text"], "conversation")[0]
    for step in steps:
        verb, _, word = step.partition(" ")
        if verb in ("allow", "refuse"):
            chats = [item["text"] for item in done if item["path"] == "/api/chat"]
            calls = dict.fromkeys((call["id"] for call in fields(chats[-1], "approval")), verb == "allow")
            done.append(exchange(client, "POST", "/api/chat", {"conversation": conversation, "approvals": calls}))
        elif verb == "decide":
            done.append(exchange(client, "POST", "/api/promotion", {"decision": word}))
        else:
            while not reached(read := exchange(client, "GET", "/api/promotion"), word):
                time.sleep(30)
            done.append(read)
    return done


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="ops.record")
    parser.add_argument("--app", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("steps", nargs="*")
    args = parser.parse_args()
    with httpx.Client(base_url=args.app, headers={"Cookie": os.environ["TRAINYARD_COOKIE"]}) as client:
        roles = client.get("/api/me").raise_for_status().json()["roles"]
        exchanges = record(client, args.question, args.steps)
    user = {"name": "Leo Owner" if "ModelApprover" in roles else "Marta Planner", "roles": roles}
    today, name = datetime.now(UTC).date().isoformat(), re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")
    run = {"title": args.title, "prompt": args.question, "user": user, "recorded": today, "exchanges": exchanges}
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{name}.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
