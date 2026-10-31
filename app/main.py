"""REQ-05, REQ-06, REQ-09, REQ-10: the API behind Easy Auth; the chat, the promotion cards, feedback and deletion."""

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass
from os import environ
from secrets import token_hex
from typing import Annotated, Any, Literal

from agent_framework import AgentSession, Message, SupportsChatGetResponse
from agent_framework.exceptions import ChatClientException
from agent_framework.foundry import FoundryChatClient
from agent_framework_azure_cosmos import CosmosCheckpointStorage
from azure.core.exceptions import AzureError
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app import telemetry
from app.agent import APPROVER, Tools, build_agent
from app.platform import Platform
from app.promotion import Promotions
from app.store import Conversations, Lease, messages

READER, OID = "Reader", "http://schemas.microsoft.com/identity/claims/objectidentifier"
DATABASE, TICK_SECONDS, MODEL_TIMEOUT, MODEL_RETRIES, STORE_TIMEOUT = "trainyard", 60, 60, 3, 15


@dataclass(frozen=True)
class Services:
    platform: Platform
    promotions: Promotions
    conversations: Conversations
    chat: SupportsChatGetResponse[Any]


@dataclass(frozen=True)
class User:
    id: str
    roles: frozenset[str]


class Ask(BaseModel):
    conversation: str | None = Field(None, max_length=64)
    message: str | None = Field(None, min_length=1, max_length=2000)
    approvals: dict[str, bool] = Field(default_factory=dict, max_length=8)


class Decision(BaseModel):
    decision: Literal["approve", "promote", "rollback", "close"]


class Feedback(BaseModel):
    conversation: str = Field(max_length=64)
    helpful: bool


@asynccontextmanager
async def connect(platform: Platform) -> AsyncIterator[Services]:
    credential = DefaultAzureCredential()
    async with credential, CosmosClient(environ["COSMOS_ENDPOINT"], credential, timeout=STORE_TIMEOUT) as cosmos:
        database = cosmos.get_database_client(DATABASE)
        checkpoints, chat = database.get_container_client("checkpoints"), FoundryChatClient(credential=credential)
        chat.client = chat.client.with_options(timeout=MODEL_TIMEOUT, max_retries=MODEL_RETRIES)
        promotions = Promotions(platform, CosmosCheckpointStorage(container_client=checkpoints), Lease(checkpoints))
        try:
            yield Services(platform, promotions, Conversations(database.get_container_client("conversations")), chat)
        finally:
            await chat.client.close()


def user(x_ms_client_principal: Annotated[str | None, Header()] = None) -> User:
    try:
        principal = json.loads(base64.b64decode(x_ms_client_principal or ""))
        claims = [(claim["typ"], claim["val"]) for claim in principal["claims"]]
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(401, "Sign in to use Trainyard.") from error
    roles = frozenset(val for typ, val in claims if typ in (principal.get("role_typ"), "roles")) & {READER, APPROVER}
    oid = next((val for typ, val in claims if typ in (OID, "oid")), "")
    if not roles or not oid:
        raise HTTPException(403, "Ask your administrator for the Reader or the ModelApprover role.")
    return User(hashlib.sha256(oid.encode()).hexdigest()[:16], roles)


def approver(who: Annotated[User, Depends(user)]) -> User:
    if APPROVER not in who.roles:
        raise HTTPException(403, "Only a model owner can change the model.")
    return who


def services(request: Request) -> Services:
    found: Services = request.app.state.services
    return found


Signed = Annotated[User, Depends(user)]
Owner = Annotated[User, Depends(approver)]
Wired = Annotated[Services, Depends(services)]
router = APIRouter()


def trouble(error: Exception) -> tuple[int, dict[str, str]]:
    model = isinstance(error, ChatClientException)
    cause, what = error.__cause__ if model else error, "The language model" if model else "A Trainyard service"
    retry = str(getattr(getattr(cause, "response", None), "headers", {}).get("retry-after", "60"))
    if getattr(cause, "status_code", None) == 429:
        return 429, {"detail": f"{what} is at its request limit; try again in {retry} seconds.", "retry": retry}
    return 503, {"detail": f"{what} is unavailable; try again in a minute.", "retry": retry}


async def unavailable(request: Request, error: Exception) -> JSONResponse:
    code, body = trouble(error)
    return JSONResponse({"detail": body["detail"]}, code, {"Retry-After": body["retry"]})


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    alive = not request.app.state.timer.done()
    return JSONResponse({"status": "ok" if alive else "the promotion timer stopped"}, 200 if alive else 503)


@router.get("/api/me")
async def me(who: Signed) -> dict[str, list[str]]:
    return {"roles": sorted(who.roles)}


@router.get("/api/fleet/risk")
async def fleet_risk(who: Signed, wired: Wired) -> Any:
    return json.loads(await Tools(wired.platform, wired.promotions).fleet_risk())


async def prompt(body: Ask, who: Signed, wired: Wired) -> tuple[AgentSession, Message]:
    fresh = AgentSession(session_id=token_hex(8))
    session = await wired.conversations.load(who.id, body.conversation) if body.conversation else fresh
    if session is None:
        raise HTTPException(404, "No such conversation.")
    asked = {c.id: c for m in messages(session) for c in m.contents if c.type == "function_approval_request"}
    answers = [asked[key].to_function_approval_response(ok) for key, ok in body.approvals.items() if key in asked]
    if not answers and not body.message:
        raise HTTPException(422, "Send a message or answer a pending approval.")
    return session, Message("user", answers or [body.message or ""])


@router.post("/api/chat", response_class=EventSourceResponse)
async def chat(
    turn: Annotated[tuple[AgentSession, Message], Depends(prompt)], who: Signed, wired: Wired
) -> AsyncIterator[ServerSentEvent]:
    (session, message), tools = turn, Tools(wired.platform, wired.promotions, who.id)
    yield ServerSentEvent(event="conversation", data=session.session_id)
    try:
        async for update in build_agent(wired.chat, tools, who.roles).run(message, stream=True, session=session):
            if update.text:
                yield ServerSentEvent(event="text", data=update.text)
            for c in update.contents:
                if c.type == "function_approval_request" and c.function_call:
                    call = {"id": c.id, "tool": c.function_call.name, "arguments": c.function_call.parse_arguments()}
                    yield ServerSentEvent(event="approval", data=call)
        await wired.conversations.save(who.id, session)
        card = await wired.promotions.card() if APPROVER in who.roles else None
    except (AzureError, ChatClientException) as error:
        code, body = trouble(error)
        yield ServerSentEvent(event="error", data={"status": code, "detail": body["detail"]})
        return
    yield ServerSentEvent(event="done", data={"card": asdict(card) if card else None})


@router.get("/api/conversations")
async def conversations(who: Signed, wired: Wired) -> list[dict[str, Any]]:
    return await wired.conversations.mine(who.id)


@router.get("/api/conversations/{conversation}")
async def conversation(conversation: str, who: Signed, wired: Wired) -> list[dict[str, str]]:
    if (session := await wired.conversations.load(who.id, conversation)) is None:
        raise HTTPException(404, "No such conversation.")
    return [{"role": str(m.role), "text": m.text} for m in messages(session) if m.text]


@router.delete("/api/conversations/{conversation}", status_code=204)
async def forget(conversation: str, who: Signed, wired: Wired) -> None:
    if not await wired.conversations.delete(who.id, conversation):
        raise HTTPException(404, "No such conversation.")


@router.post("/api/feedback", status_code=204)
async def feedback(body: Feedback, who: Signed) -> None:
    telemetry.event("feedback_given", conversation=body.conversation, helpful=body.helpful)


@router.get("/api/promotion")
async def promotion(who: Owner, wired: Wired) -> dict[str, Any]:
    card = await wired.promotions.card()
    return {"card": asdict(card) if card else None}


@router.post("/api/promotion")
async def decide(body: Decision, who: Owner, wired: Wired) -> dict[str, Any]:
    return asdict(await wired.promotions.answer(body.decision, who.id))


async def beat(step: Callable[[], Awaitable[object]]) -> None:
    try:
        await step()
    except AzureError:
        telemetry.LOGGER.warning("The promotion timer could not reach Azure; it tries again in a minute.")


async def timer(promotions: Promotions, seconds: float) -> None:
    await beat(promotions.resume)
    while True:
        await asyncio.sleep(seconds)
        await beat(promotions.tick)


def create(open_services: Callable[[], AbstractAsyncContextManager[Services]], tick: float = TICK_SECONDS) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        telemetry.configure()
        async with open_services() as wired:
            api.state.services, api.state.timer = wired, asyncio.create_task(timer(wired.promotions, tick))
            yield
            api.state.timer.cancel()

    api = FastAPI(title="Trainyard", lifespan=lifespan)
    api.include_router(router)
    for kind in (AzureError, ChatClientException):
        api.add_exception_handler(kind, unavailable)
    return api
