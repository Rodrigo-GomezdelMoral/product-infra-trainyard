import base64
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

from agent_framework import Message
from agent_framework.exceptions import ChatClientException
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.cosmos.aio import ContainerProxy
from fastapi.testclient import TestClient

from app.domain.fleet import INSPECTION_BUDGET
from app.main import Services, create
from app.store import Conversations
from tests.doubles import FakeContainer, FakePlatform, Reply, Scripted, call, promotions, say

READER, DOWN = "Reader", "The language model is unavailable; try again in a minute."


def signed(role: str, oid: str = "planner-1") -> dict[str, str]:
    claims = [{"typ": "roles", "val": role}, {"typ": "oid", "val": oid}]
    return {"X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps({"claims": claims}).encode()).decode()}


def serve(platform: FakePlatform, *script: Reply, store: FakeContainer | None = None) -> TestClient:
    wired = Services(
        platform,
        promotions(platform),
        Conversations(cast(ContainerProxy, store or FakeContainer("owner"))),
        Scripted(*script),
    )

    @asynccontextmanager
    async def opened() -> AsyncIterator[Services]:
        yield wired

    return TestClient(create(opened, tick=3600))


def sse(text: str) -> list[tuple[str, Any]]:
    blocks = [dict(line.split(": ", 1) for line in block.splitlines()) for block in text.strip().split("\n\n")]
    return [(block["event"], json.loads(block["data"])) for block in blocks]


def test_sign_in_and_roles(platform: FakePlatform) -> None:
    with serve(platform) as client:
        assert [client.get("/api/me", headers=h).status_code for h in ({}, signed("Guest"))] == [401, 403]
        assert client.get("/api/me", headers=signed("ModelApprover")).json() == {"roles": ["ModelApprover"]}
        assert client.get("/api/fleet/risk", headers=signed(READER)).json()["inspection_budget"] == INSPECTION_BUDGET
        changes = [client.get("/api/promotion", headers=signed(READER))]
        changes += [client.post("/api/promotion", headers=signed(READER), json={"decision": "promote"})]
        assert [r.status_code for r in changes] == [403, 403] and client.get("/healthz").json() == {"status": "ok"}


def test_delete_conversation(platform: FakePlatform) -> None:
    with serve(platform, say("Hello."), say("Again.")) as client:
        opened = sse(client.post("/api/chat", headers=signed(READER), json={"message": "Hi"}).text)
        mine, theirs = f"/api/conversations/{opened[0][1]}", signed(READER, "planner-2")
        again = client.post("/api/chat", headers=signed(READER), json={"conversation": opened[0][1], "message": "More"})
        assert [name for name, _ in sse(again.text)] == ["conversation", "text", "done"]
        assert [m["text"] for m in client.get(mine, headers=signed(READER)).json()] == [
            "Hi",
            "Hello.",
            "More",
            "Again.",
        ]
        assert client.get("/api/conversations", headers=signed(READER)).json() == [{"id": opened[0][1], "title": "Hi"}]
        assert [client.delete(mine, headers=h).status_code for h in (theirs, signed(READER))] == [404, 204]
        assert client.get(mine, headers=signed(READER)).status_code == 404


def test_feedback_event(platform: FakePlatform, events: Callable[[], list[tuple[str, dict[str, Any]]]]) -> None:
    with serve(platform) as client:
        given = client.post("/api/feedback", headers=signed(READER), json={"conversation": "c1", "helpful": True})
    assert given.status_code == 204 and events() == [("feedback_given", {"conversation": "c1", "helpful": True})]


def test_promotion_cards_through_the_chat(platform: FakePlatform) -> None:
    owner = signed("ModelApprover", "owner-1")
    with serve(platform, call("start_promotion", version="3"), say("The shadow is running.")) as client:
        asked = sse(client.post("/api/chat", headers=owner, json={"message": "Promote model 3"}).text)
        approval = next(data for name, data in asked if name == "approval")
        answer = {"conversation": asked[0][1], "approvals": {approval["id"]: True}}
        done = sse(client.post("/api/chat", headers=owner, json=answer).text)[-1]
        canary = client.post("/api/promotion", headers=owner, json={"decision": "approve"}).json()
    assert approval["tool"] == "start_promotion" and done[1]["card"]["step"] == "shadow"
    assert canary["card"]["step"] == "canary" and not canary["card"]["facts"]["ready"]


def test_dependency_down(platform: FakePlatform, monkeypatch: Any) -> None:
    throttled, store = HttpResponseError("Too many requests."), FakeContainer("owner")
    throttled.status_code = 429

    def model(cause: BaseException | None) -> Callable[[Sequence[Message]], Message]:
        def fail(messages: Sequence[Message]) -> Message:
            raise ChatClientException("The model call failed.") from cause

        return fail

    async def unreachable() -> None:
        raise ServiceRequestError("The endpoint is unreachable.")

    with serve(platform, model(None), model(throttled), store=store) as client:
        chats = [sse(client.post("/api/chat", headers=signed(READER), json={"message": "Hi"}).text) for _ in range(2)]
        monkeypatch.setattr(platform, "week", unreachable)
        risk, store.down = client.get("/api/fleet/risk", headers=signed(READER)), True
        listed = client.get("/api/conversations", headers=signed(READER))
    assert chats[0][-1] == ("error", {"status": 503, "detail": DOWN}) and chats[1][-1][1]["status"] == 429
    assert [(r.status_code, r.headers["Retry-After"]) for r in (risk, listed)] == [(503, "60"), (503, "60")]
    assert risk.json() == {"detail": "A Trainyard service is unavailable; try again in a minute."}
