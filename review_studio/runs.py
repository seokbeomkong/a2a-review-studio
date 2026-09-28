import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from .config import Settings
from .models import AGENTS, AgentJob, ReviewContent, ReviewRequest
from .providers import ProviderError


@dataclass
class ReviewRun:
    proposal: str
    mode: str
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started: float = field(default_factory=time.monotonic)
    status: str = "running"
    stage: str = "draft"
    reviews: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    summary: dict | None = None
    task: asyncio.Task | None = None

    def snapshot(self):
        return {
            key: getattr(self, key)
            for key in (
                "id",
                "proposal",
                "mode",
                "created_at",
                "status",
                "stage",
                "reviews",
                "events",
                "errors",
                "summary",
            )
        }

    def event(self, **data):
        if self.status == "running":
            self.events.append(
                {
                    "seq": len(self.events) + 1,
                    "run_id": self.id,
                    "at": datetime.now(UTC).isoformat(),
                    **data,
                }
            )


class RunStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runs: dict[str, ReviewRun] = {}

    def prune(self):
        cutoff = time.monotonic() - self.settings.retention_seconds
        for key, run in list(self.runs.items()):
            if run.status != "running" and run.started < cutoff:
                del self.runs[key]

    def get(self, run_id: str):
        self.prune()
        return self.runs.get(run_id)

    def create(self, request: ReviewRequest):
        self.prune()
        if sum(r.status == "running" for r in self.runs.values()) >= self.settings.max_concurrent:
            raise RuntimeError(
                "동시에 진행할 수 있는 검토 수를 초과했습니다. 잠시 후 다시 시도하세요."
            )
        while len(self.runs) >= self.settings.max_retained:
            key = next((k for k, r in self.runs.items() if r.status != "running"), None)
            if key is None:
                raise RuntimeError("진행 중인 검토가 많습니다. 잠시 후 다시 시도하세요.")
            del self.runs[key]
        run = ReviewRun(proposal=request.proposal, mode=request.mode)
        self.runs[run.id] = run
        return run


async def orchestrate(run, broker, provider, settings):
    try:
        async with asyncio.timeout(settings.run_timeout):

            async def draft(name):
                try:
                    reply = await broker.call(
                        "orchestrator",
                        name,
                        AgentJob(
                            run_id=run.id,
                            phase="draft",
                            proposal=run.proposal,
                        ),
                    )
                    run.reviews[name] = {"draft": reply["content"], "revised": None, "feedback": {}}
                except ProviderError:
                    pass  # The broker records the user-visible failure and trace.

            await asyncio.gather(*(draft(name) for name in AGENTS))
            if not run.reviews:
                run.status = "failed"
                return
            run.stage = "feedback"

            async def revise(name):
                try:
                    reply = await broker.call(
                        "orchestrator",
                        name,
                        AgentJob(
                            run_id=run.id,
                            phase="revise",
                            proposal=run.proposal,
                            draft=ReviewContent.model_validate(run.reviews[name]["draft"]),
                        ),
                    )
                    run.reviews[name]["revised"] = reply["content"]
                    run.reviews[name]["feedback"] = reply.get("feedback", {})
                except ProviderError:
                    pass

            await asyncio.gather(*(revise(name) for name in list(run.reviews)))
            run.stage = "synthesize"
            summary = await provider.generate(
                "orchestrator",
                AgentJob(
                    run_id=run.id,
                    phase="synthesize",
                    proposal=run.proposal,
                    feedback={
                        name: ReviewContent.model_validate(r["revised"] or r["draft"])
                        for name, r in run.reviews.items()
                    },
                ),
            )
            run.summary = summary.model_dump()
            run.status = "partial" if run.errors else "completed"
    except TimeoutError:
        run.errors.append("전체 검토 제한 시간을 초과했습니다. 더 짧은 제안으로 다시 시도하세요.")
        run.status = "failed"
    except asyncio.CancelledError:
        run.errors.append("서버 종료로 검토가 중단되었습니다.")
        run.status = "failed"
        raise
    except ProviderError as error:
        run.errors.append(str(error))
        run.status = "failed"
    except Exception:
        run.errors.append("검토를 완료하지 못했습니다. 서버 상태를 확인하고 다시 시도하세요.")
        run.status = "failed"
    finally:
        run.stage = "done"


def markdown_report(run: ReviewRun) -> str:
    label = "데모 · LLM 미사용 · 규칙 기반 예시" if run.mode == "demo" else "Claude API"
    text = [
        "# A2A Review Studio 검토 결과",
        "",
        f"- 실행: {run.id}",
        f"- 모드: {label}",
        f"- 상태: {run.status}",
        f"- 생성: {run.created_at}",
        "",
        "## 입력 제안",
        "",
        run.proposal,
    ]
    if run.errors:
        text += ["", "## 누락·오류", ""] + [f"- {e}" for e in run.errors]
    sections = [("최종 실행안", run.summary)]
    for name, review in run.reviews.items():
        sections.extend(
            [
                (f"{AGENTS[name]['label']} — 초안", review["draft"]),
                (f"{AGENTS[name]['label']} — 피드백 후", review["revised"]),
            ]
        )
    fields = {
        "findings": "검토 내용",
        "risks": "우려·남은 이견",
        "actions": "실행 단계",
        "metrics": "검증 지표",
        "changes": "의견 반영",
    }
    for title, content in sections:
        if not content:
            continue
        text += ["", f"## {title}", "", content["headline"]]
        for key, heading in fields.items():
            if content.get(key):
                text += ["", f"### {heading}", ""] + [f"- {s}" for s in content[key]]
    text += [
        "",
        "## 통신 요약",
        "",
        f"A2A 1.0 / JSON-RPC / SendMessage 요청 {sum(e['kind'] == 'request' for e in run.events)}건",
        "Orchestrator → 전문가 초안·수정 요청과 전문가 ↔ 전문가 피드백 요청을 포함합니다.",
        "",
    ]
    return "\n".join(text)
