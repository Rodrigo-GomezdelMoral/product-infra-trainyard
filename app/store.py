"""REQ-05, REQ-10: the Cosmos DB documents the API writes itself, the promotion lease and the conversations."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import time
from typing import Any

from agent_framework import AgentSession, Message
from azure.core import MatchConditions
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

LEASE, HISTORY = {"id": "promotion", "workflow_name": "lease"}, "in_memory"
Document = dict[str, Any]


class Lease:
    def __init__(self, container: ContainerProxy, seconds: float = 180) -> None:
        self.container, self.seconds = container, seconds

    async def write(self, document: Document) -> Document | None:
        try:
            if "_etag" not in document:
                return await self.container.create_item(document)
            return await self.container.replace_item(
                document["id"], document, etag=document["_etag"], match_condition=MatchConditions.IfNotModified
            )
        except (CosmosResourceExistsError, CosmosAccessConditionFailedError):
            return None

    async def take(self) -> Document | None:
        try:
            held: Document = await self.container.read_item(LEASE["id"], partition_key=LEASE["workflow_name"])
        except CosmosResourceNotFoundError:
            held = LEASE | {"expires": 0.0}
        return None if held["expires"] > time() else await self.write(held | {"expires": time() + self.seconds})

    async def keep(self, held: Document, holder: asyncio.Task[Any]) -> None:
        while True:
            await asyncio.sleep(self.seconds / 3)
            if (renewed := await self.write(held | {"expires": time() + self.seconds})) is None:
                holder.cancel()
                return
            held.update(renewed)

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[Document | None]:
        holder = asyncio.current_task()
        held = await self.take() if holder else None
        if held is None or holder is None:
            yield None
            return
        keeper = asyncio.create_task(self.keep(held, holder))
        try:
            yield held
        finally:
            keeper.cancel()
            await self.write(held | {"expires": 0.0})


def messages(session: AgentSession) -> list[Message]:
    return list(session.state.get(HISTORY, {}).get("messages", []))


class Conversations:
    def __init__(self, container: ContainerProxy) -> None:
        self.container = container

    async def load(self, owner: str, conversation: str) -> AgentSession | None:
        try:
            document = await self.container.read_item(conversation, partition_key=owner)
        except CosmosResourceNotFoundError:
            return None
        return AgentSession.from_dict(document["session"])

    async def save(self, owner: str, session: AgentSession) -> None:
        title = next((m.text for m in messages(session) if m.role == "user" and m.text), "")[:80]
        document = {"id": session.session_id, "owner": owner, "title": title, "session": session.to_dict()}
        await self.container.upsert_item(document)

    async def mine(self, owner: str) -> list[Document]:
        found = self.container.query_items("SELECT c.id, c.title FROM c ORDER BY c._ts DESC", partition_key=owner)
        return [{"id": c["id"], "title": c["title"]} async for c in found]

    async def delete(self, owner: str, conversation: str) -> bool:
        try:
            await self.container.delete_item(conversation, partition_key=owner)
        except CosmosResourceNotFoundError:
            return False
        return True
