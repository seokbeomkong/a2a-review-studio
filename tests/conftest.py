import asyncio
import socket
from contextlib import asynccontextmanager

import uvicorn

from review_studio.app import create_app
from review_studio.config import Settings
from review_studio.providers import DemoProvider


@asynccontextmanager
async def live_server(provider=None, **overrides):
    # Bind first so concurrent tests cannot steal the selected port.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    settings = Settings(_env_file=None, studio_port=port, **overrides)
    app = create_app(settings, lambda mode: provider or DemoProvider(delay=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        yield app, settings
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        sock.close()


async def complete_run(
    client, proposal="고객 문의를 자동 분류하고 담당자에게 전달하는 도구를 도입하려고 합니다."
):
    response = await client.post("/api/runs", json={"proposal": proposal, "mode": "demo"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    async with asyncio.timeout(15):
        while True:
            result = (await client.get(f"/api/runs/{run_id}")).json()
            if result["status"] in ("completed", "partial", "failed"):
                return result
            await asyncio.sleep(0.02)
