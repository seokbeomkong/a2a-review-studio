import asyncio

import httpx
from conftest import complete_run, live_server

from review_studio.providers import DemoProvider, ProviderError


async def test_real_http_a2a_roundtrip_and_six_peer_feedback_exchanges():
    async with (
        live_server() as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        card = (await client.get("/agents/technical/.well-known/agent-card.json")).json()
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert card["supportedInterfaces"][0]["url"] == settings.base_url + "/agents/technical/"
        result = await complete_run(client)
        assert result["status"] == "completed", result["errors"]
        assert len(result["reviews"]) == 3
        feedback = [
            e for e in result["events"] if e["kind"] == "request" and e["phase"] == "feedback"
        ]
        assert len(feedback) == 6
        assert all(e["source"] != e["target"] for e in feedback)
        assert all(e["method"] == "SendMessage" and e["message_id"] for e in feedback)
        assert all(v["revised"]["changes"] for v in result["reviews"].values())
        assert all(e.get("response") for e in result["events"] if e["kind"] == "response")
        report = await client.get(f"/api/runs/{result['id']}/report")
        assert report.status_code == 200
        assert "LLM 미사용" in report.text and "고객 문의" in report.text


async def test_parallel_runs_do_not_mix_proposals_or_context_ids():
    async with (
        live_server() as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        a, b = await asyncio.gather(
            complete_run(client, "ALPHA 창고 출고 업무의 누락을 줄이기 위한 자동 확인 제안입니다."),
            complete_run(client, "BETA 인사팀의 휴가 신청을 자동으로 분류하는 도구를 제안합니다."),
        )
        assert a["id"] != b["id"]
        assert "BETA" not in str(a)
        assert "ALPHA" not in str(b)
        assert {e["run_id"] for e in a["events"]} == {a["id"]}


class BrokenExpert(DemoProvider):
    async def generate(self, agent, job):
        if agent == "business":
            raise ProviderError("의도된 전문가 장애")
        return await super().generate(agent, job)


async def test_missing_expert_is_partial_not_a_fabricated_consensus():
    async with (
        live_server(BrokenExpert(0)) as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        result = await complete_run(client)
        assert result["status"] == "partial"
        assert "business" not in result["reviews"]
        assert result["errors"] and result["summary"]


class AllBroken(DemoProvider):
    async def generate(self, agent, job):
        raise ProviderError("의도된 전체 장애")


async def test_all_failed_has_no_success_summary():
    async with (
        live_server(AllBroken(0)) as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        result = await complete_run(client)
        assert result["status"] == "failed"
        assert result["summary"] is None


async def test_run_deadline_reports_failure():
    async with (
        live_server(DemoProvider(0.3), run_timeout=0.05) as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        result = await complete_run(client)
        assert result["status"] == "failed"
        assert any("시간" in error for error in result["errors"])


class SlowRevision(DemoProvider):
    async def generate(self, agent, job):
        if job.phase == "revise":
            await asyncio.sleep(1)
        return await super().generate(agent, job)


async def test_deadline_preserves_completed_drafts_as_partial():
    async with (
        live_server(SlowRevision(0), run_timeout=0.4) as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        result = await complete_run(client)
        assert result["status"] == "partial"
        assert len(result["reviews"]) == 3
        assert result["summary"] is None
        assert any("시간" in error for error in result["errors"])


async def test_rejects_foreign_origin_unauthed_agent_and_invalid_input():
    async with (
        live_server() as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        assert (await client.post("/api/runs", json={"proposal": "x"})).status_code == 422
        assert (
            await client.post(
                "/api/runs", json={"proposal": "x" * 30}, headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
        assert (await client.post("/agents/technical/", json={})).status_code == 401
        assert (
            await client.get("/api/config", headers={"Host": "evil.example"})
        ).status_code == 400
        response = await client.post("/api/runs", json={"proposal": "x" * 30, "mode": "claude"})
        assert response.status_code == 409
        assert (await client.get("/api/runs/missing")).status_code == 404


async def test_capacity_limits_running_and_retained_results():
    async with (
        live_server(DemoProvider(0.1), max_concurrent=1, max_retained=2) as (_, settings),
        httpx.AsyncClient(base_url=settings.base_url) as client,
    ):
        first = await client.post("/api/runs", json={"proposal": "x" * 30})
        assert first.status_code == 202
        assert (await client.post("/api/runs", json={"proposal": "y" * 30})).status_code == 429
        async with asyncio.timeout(10):
            while (await client.get("/api/runs/" + first.json()["id"])).json()[
                "status"
            ] == "running":
                await asyncio.sleep(0.02)
        await complete_run(client)
        await complete_run(client)
        assert (await client.get("/api/runs/" + first.json()["id"])).status_code == 404
