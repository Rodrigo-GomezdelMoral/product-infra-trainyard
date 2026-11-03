"""REQ-07, REQ-08: load scenarios against staging, run by `load-test.yml`.

The inference endpoint is called with an Entra ID token (`aad_token`) and a real 40-row request built by the same
simulator and features as the app, from the last week of the staging feed after `firmware-b`, so the rows the load
writes to the data collector look like the fleet the monitor watches; `/api/fleet/risk` uses no language model, so
the Container App replicas scale without spending tokens. The chat scenario is two users asking the planner's question.
Locust's times include the runner's network path; `load-test.yml` judges REQ-07 and REQ-08 at the endpoint instead.
"""

import json
import os
import time
from datetime import date

import pandas as pd
from locust import HttpUser, between, constant_pacing, events, task
from locust.env import Environment

from app.domain.simulator import simulate
from ml.features import features

FEED = simulate(date(2026, 10, 1), 31, firmware_b_from=date(2026, 5, 1))
ROWS = features(FEED.telemetry, FEED.failures, pd.Timestamp("2026-10-31")).drop(columns="as_of")
BODY = json.dumps({"rows": ROWS.to_dict("records")})
STRESS_FAILED = 0.01
SCORE = "score 40 rows"
PACE = constant_pacing(10) if os.environ.get("SCENARIO") == "peak" else None


def bearer(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ.get(name, '')}"}


class EndpointUser(HttpUser):
    host = os.environ.get("SCORING_URL", "")
    wait_time = PACE or between(0.5, 1.5)

    @task
    def score(self) -> None:
        headers = bearer("ENDPOINT_TOKEN") | {"Content-Type": "application/json"}
        self.client.post("", data=BODY, headers=headers, name=SCORE)


class FleetUser(HttpUser):
    host = os.environ.get("APP_URL", "")
    wait_time = PACE or between(1, 3)

    @task
    def fleet_risk(self) -> None:
        self.client.get("/api/fleet/risk", headers=bearer("APP_TOKEN"), name="fleet risk")


class ChatUser(HttpUser):
    host = os.environ.get("APP_URL", "")
    wait_time = between(5, 10)

    @task
    def ask(self) -> None:
        started, question = time.perf_counter(), {"message": "Which trains should we inspect this week?"}
        headers, chat = bearer("APP_TOKEN"), self.client.post
        with chat("/api/chat", json=question, headers=headers, stream=True, catch_response=True, name="chat") as answer:
            chunks = answer.iter_content(chunk_size=None)
            first = next(chunks, b"")
            waited = 1000 * (time.perf_counter() - started)
            events.request.fire(
                request_type="SSE",
                name="chat first event",
                response_time=waited,
                response_length=len(first),
                exception=None,
                context={},
            )
            for _ in chunks:
                pass
            answer.success() if answer.ok and first else answer.failure(f"HTTP {answer.status_code}, empty or failed")


def stop_at_the_break(environment: Environment) -> None:
    total, runner = environment.stats.total, environment.runner
    if runner and total.num_requests > 100 and total.fail_ratio > STRESS_FAILED:
        print(f"Breaking point: {runner.user_count} users, failed {total.fail_ratio:.2%}")
        runner.quit()


@events.init.add_listener
def on_init(environment: Environment, **_: object) -> None:
    if os.environ.get("SCENARIO") == "stress":
        events.request.add_listener(lambda **_: stop_at_the_break(environment))


@events.quitting.add_listener
def on_quitting(environment: Environment, **_: object) -> None:
    if os.environ.get("SCENARIO") != "chat":
        environment.process_exit_code = int(environment.stats.get(SCORE, "POST").num_requests == 0)
