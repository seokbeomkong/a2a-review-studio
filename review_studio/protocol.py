import asyncio
import json
import time
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
    SendMessageRequest,
)
from google.protobuf.json_format import MessageToDict, ParseDict
from starlette.applications import Starlette

from .models import AGENTS, AgentJob, ReviewContent
from .providers import ProviderError


class A2ABroker:
    """Every call uses the official SDK and real loopback HTTP, including peer calls."""

    def __init__(self, settings, store, client: httpx.AsyncClient):
        self.settings, self.store, self.http = settings, store, client

    async def call(self, source, target, job: AgentJob):
        run = self.store.get(job.run_id)
        if not run or run.status != "running" or target not in AGENTS:
            raise ProviderError("유효하지 않거나 종료된 검토 요청입니다.")
        message = new_text_message(job.model_dump_json(), context_id=run.id, role=Role.ROLE_USER)
        message.message_id = str(uuid4())
        endpoint = f"{self.settings.base_url}/agents/{target}/"
        trace = {
            "source": source,
            "target": target,
            "phase": job.phase,
            "method": "SendMessage",
            "message_id": message.message_id,
            "endpoint": endpoint,
        }
        run.event(kind="request", request=MessageToDict(message), **trace)
        started = time.monotonic()
        try:
            card_response = await self.http.get(endpoint + ".well-known/agent-card.json")
            card_response.raise_for_status()
            card = ParseDict(card_response.json(), AgentCard())
            if not card.supported_interfaces or any(
                i.url != endpoint for i in card.supported_interfaces
            ):
                raise ProviderError("Agent Card의 주소가 허용된 경로와 다릅니다.")
            sdk = ClientFactory(
                ClientConfig(
                    streaming=False,
                    httpx_client=self.http,
                    supported_protocol_bindings=["JSONRPC"],
                )
            ).create(card)
            async for event in sdk.send_message(SendMessageRequest(message=message)):
                if event.HasField("message"):
                    envelope = json.loads(get_message_text(event.message))
                    if not envelope.get("ok"):
                        raise ProviderError(envelope.get("error", "전문가 요청 실패"))
                    content = ReviewContent.model_validate(envelope["content"]).model_dump()
                    feedback = {
                        name: ReviewContent.model_validate(value).model_dump()
                        for name, value in envelope.get("feedback", {}).items()
                        if name in AGENTS
                    }
                    run.event(
                        kind="response",
                        response=MessageToDict(event.message),
                        elapsed_ms=round((time.monotonic() - started) * 1000),
                        **trace,
                    )
                    return {"content": content, "feedback": feedback}
            raise ProviderError("전문가가 결과 메시지를 반환하지 않았습니다.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            safe = (
                str(error)
                if isinstance(error, ProviderError)
                else "A2A 통신 또는 응답 처리에 실패했습니다."
            )
            if run.status == "running":
                run.errors.append(f"{AGENTS[target]['label']} / {job.phase}: {safe}")
            run.event(kind="error", error=safe, **trace)
            raise ProviderError(safe) from None


class ReviewExecutor(AgentExecutor):
    def __init__(self, name, settings, store, broker, provider_factory):
        self.name, self.settings, self.store = name, settings, store
        self.broker, self.provider_factory = broker, provider_factory

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            job = AgentJob.model_validate_json(context.get_user_input())
            run = self.store.get(job.run_id)
            if not run or run.status != "running" or job.proposal != run.proposal:
                raise ProviderError("유효하지 않거나 종료된 검토입니다.")
            if job.phase == "synthesize" or (job.phase in ("feedback", "revise") and not job.draft):
                raise ProviderError("전문가 요청 단계 또는 초안이 유효하지 않습니다.")
            if job.phase == "feedback" and (not job.author or job.author == self.name):
                raise ProviderError("피드백 대상이 유효하지 않습니다.")
            remaining = self.settings.run_timeout - (time.monotonic() - run.started)
            if remaining <= 0:
                raise ProviderError("검토 제한 시간이 만료되었습니다.")
            async with asyncio.timeout(remaining):
                peer_feedback = {}
                if job.phase == "revise":
                    # Only the revise phase may request feedback. Feedback never calls peers.
                    async def ask(peer):
                        try:
                            reply = await self.broker.call(
                                self.name,
                                peer,
                                AgentJob(
                                    run_id=job.run_id,
                                    phase="feedback",
                                    proposal=job.proposal,
                                    author=self.name,
                                    draft=job.draft,
                                ),
                            )
                            peer_feedback[peer] = ReviewContent.model_validate(reply["content"])
                        except ProviderError:
                            pass

                    await asyncio.gather(*(ask(peer) for peer in AGENTS if peer != self.name))
                    job = job.model_copy(update={"feedback": peer_feedback})
                content = await self.provider_factory(run.mode).generate(self.name, job)
                envelope = {
                    "ok": True,
                    "content": content.model_dump(),
                    "feedback": {key: value.model_dump() for key, value in peer_feedback.items()},
                }
        except asyncio.CancelledError:
            raise
        except Exception as error:
            safe = (
                str(error)
                if isinstance(error, ProviderError)
                else "전문가 요청 처리에 실패했습니다."
            )
            envelope = {"ok": False, "error": safe}
        await event_queue.enqueue_event(
            new_text_message(
                json.dumps(envelope, ensure_ascii=False),
                context_id=context.context_id,
            )
        )

    async def cancel(self, context, event_queue):
        raise NotImplementedError("This message-only agent does not expose task cancellation.")


def agent_app(name, settings, store, broker, provider_factory):
    card = AgentCard(
        name=AGENTS[name]["label"],
        description=AGENTS[name]["role"],
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                url=f"{settings.base_url}/agents/{name}/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        skills=[
            AgentSkill(
                id=f"{name}-review",
                name="업무 개선안 검토·피드백",
                description=AGENTS[name]["role"],
                tags=["review", "feedback"],
            )
        ],
    )
    # The process-local key is intentionally not returned by any browser-facing API.
    ParseDict(
        {
            "securitySchemes": {
                "studio": {
                    "apiKeySecurityScheme": {
                        "location": "header",
                        "name": "x-studio-agent-token",
                    }
                }
            },
            "securityRequirements": [{"schemes": {"studio": []}}],
        },
        card,
    )
    handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(name, settings, store, broker, provider_factory),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))
