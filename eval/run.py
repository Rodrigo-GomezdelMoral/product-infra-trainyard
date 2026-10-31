"""REQ-01, REQ-05, REQ-06: the agent against the real model and the endpoint double, gated by `thresholds.yaml`."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, quantiles
from time import perf_counter
from typing import Any

from agent_framework import InMemoryCheckpointStorage, SupportsChatGetResponse
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential

from app.agent import Tools, build_agent
from app.domain.simulator import Feed, simulate
from app.platform import Endpoint
from app.promotion import Promotions
from eval.evaluators import THRESHOLDS, checks
from tests.doubles import START, FakePlatform

DATASET, CONCURRENCY, RETRIES = Path(__file__).parent / "datasets" / "agent.jsonl", 2, 8
CASES = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
USD_PER_MILLION_TOKENS = (0.25, 2.0)
Case = dict[str, Any]
Outcome = tuple[dict[str, bool], float, float, str]


async def answer(client: SupportsChatGetResponse[Any], feed: Feed, case: Case, limit: asyncio.Semaphore) -> Outcome:
    platform = FakePlatform(feed, Endpoint(**case["endpoint"]) if "endpoint" in case else None)
    tools = Tools(platform, Promotions(platform, InMemoryCheckpointStorage(), checks=1, interval=0))
    agent = build_agent(client, tools, [case["role"]])
    async with limit:
        began = perf_counter()
        response = await agent.run(case["query"], session=agent.create_session())
        seconds = perf_counter() - began
    usage, (given, made) = response.usage_details or {}, USD_PER_MILLION_TOKENS
    cost = ((usage.get("input_token_count") or 0) * given + (usage.get("output_token_count") or 0) * made) / 1e6
    said = " ".join(response.text.split())[:300].replace("@", "(at)")
    return checks(case, response, platform.calls), seconds, cost, said


async def evaluate(client: SupportsChatGetResponse[Any], model: str) -> tuple[str, bool]:
    feed, limit, gate = simulate(START, 90), asyncio.Semaphore(CONCURRENCY), THRESHOLDS["agent"]
    outcomes = await asyncio.gather(*(answer(client, feed, case, limit) for case in CASES))
    rates = {name: fmean(checked[name] for checked, *_ in outcomes) for name in gate}
    failed = {name for name, rate in rates.items() if rate < gate[name]}
    text = [f"Agent evaluation {datetime.now(UTC):%Y-%m-%d}, {model}, {len(CASES)} cases", ""]
    text += ["| Check | Result | Minimum | |", "|---|---|---|---|"]
    text += [f"| {k} | {v:.1%} | {gate[k]:.0%} | {'fail' if k in failed else 'pass'} |" for k, v in rates.items()]
    p95, cost = quantiles([o[1] for o in outcomes], n=20)[-1], fmean(o[2] for o in outcomes)
    text += ["", f"p95 answer {p95:.1f} s, mean USD {cost:.4f} per question."]
    graded = [(c["id"], [k for k, ok in o[0].items() if not ok], o[3]) for c, o in zip(CASES, outcomes, strict=True)]
    missed = [f"- {case}, {', '.join(names)}: {said}" for case, names, said in graded if names]
    text += ["", "Cases that failed a check, for review:", *missed] if missed else []
    return "\n".join(text), not failed


async def main() -> int:
    async with AzureCliCredential() as credential:
        client = FoundryChatClient(credential=credential)
        client.client = client.client.with_options(max_retries=RETRIES)
        try:
            text, passed = await evaluate(client, os.environ["FOUNDRY_MODEL"])
        finally:
            await client.client.close()
    sys.stdout.buffer.write(f"{text}\n".encode())
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
