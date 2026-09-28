import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .models import AGENTS, ReviewRequest
from .protocol import A2ABroker, agent_app
from .providers import ClaudeProvider, DemoProvider
from .runs import RunStore, markdown_report, orchestrate

STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, provider_factory=None):
    settings = settings or Settings()
    store = RunStore(settings)
    # Construct clients once; lifespan owns their close operation.
    peer_http = httpx.AsyncClient(
        timeout=settings.rpc_timeout,
        trust_env=False,
        headers={"x-studio-agent-token": settings.internal_token},
        limits=httpx.Limits(max_connections=80, max_keepalive_connections=30),
    )
    model_http = httpx.AsyncClient(timeout=35, trust_env=False)
    providers = {
        "demo": DemoProvider(),
        "claude": ClaudeProvider(
            settings.anthropic_api_key.get_secret_value(),
            settings.claude_model,
            model_http,
        ),
    }
    factory = provider_factory or providers.__getitem__
    broker = A2ABroker(settings, store, peer_http)

    @asynccontextmanager
    async def lifespan(app):
        yield
        pending = [r.task for r in store.runs.values() if r.task and not r.task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await peer_http.aclose()
        await model_http.aclose()

    app = FastAPI(title="A2A Review Studio", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.broker = store, broker
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {settings.base_url, f"http://localhost:{settings.studio_port}"}
        if origin and origin not in allowed:
            return JSONResponse({"detail": "허용되지 않은 웹 출처입니다."}, status_code=403)
        if request.method == "POST":
            # Bound raw input before JSON parsing, including chunked bodies.
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 100_000:
                    return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            if request.url.path.startswith("/agents/") and not secrets.compare_digest(
                request.headers.get("x-studio-agent-token", ""),
                settings.internal_token,
            ):
                return JSONResponse({"detail": "Agent 인증이 필요합니다."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/api/config")
    async def config():
        return {
            "claude_available": settings.claude_available,
            "agents": AGENTS,
            "protocol": "A2A 1.0 · JSON-RPC",
            "max_chars": 4000,
            "claude_model": settings.claude_model if settings.claude_available else None,
        }

    @app.post("/api/runs", status_code=202)
    async def start(request: ReviewRequest):
        if request.mode == "claude" and not settings.claude_available:
            raise HTTPException(409, "서버의 ANTHROPIC_API_KEY와 CLAUDE_MODEL을 설정하세요.")
        try:
            run = store.create(request)
        except RuntimeError as error:
            raise HTTPException(429, str(error)) from None
        run.task = asyncio.create_task(orchestrate(run, broker, factory(run.mode), settings))
        return {"id": run.id}

    def get_run(run_id):
        run = store.get(run_id)
        if not run:
            raise HTTPException(404, "검토 결과가 없거나 보관 기간이 만료되었습니다.")
        return run

    @app.get("/api/runs/{run_id}")
    async def status(run_id: str):
        return get_run(run_id).snapshot()

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str):
        run = get_run(run_id)
        if run.status == "running":
            raise HTTPException(409, "검토가 끝난 후 다운로드할 수 있습니다.")
        return Response(
            markdown_report(run),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="review-{run.id[:8]}.md"'},
        )

    for name in AGENTS:
        app.mount(f"/agents/{name}", agent_app(name, settings, store, broker, factory))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    return app
