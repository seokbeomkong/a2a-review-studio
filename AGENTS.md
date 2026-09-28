# A2A Review Studio

Standalone Korean portfolio app showing real A2A HTTP collaboration between three review agents.

- `review_studio/`: FastAPI app, A2A SDK endpoints/client, bounded orchestration, demo/Claude providers.
- `review_studio/static/`: dependency-free responsive browser UI.
- `tests/`: provider, protocol, orchestration and HTTP integration tests.
- `docs/`: design, implementation plan, review guide and screenshots.
- Python 3.12+. Install: `python -m pip install -e ".[dev]"`.
- Check: `python -m pytest -q`; `ruff check .`; `ruff format --check .`.
- Run: `python -m review_studio` (loopback only, one worker).
- Keep demo responses explicitly labeled. Real Claude calls require server-side environment settings. Never commit secrets or claim live-model verification without an actual successful call.
- Agent-to-agent calls must cross HTTP using the pinned official SDK, not in-process mocks. Keep run data isolated and bounded; do not render untrusted HTML.
- Before changing timeout or reload recovery, read `docs/solutions/logic-errors/preserve-review-progress-on-transient-failure.md` and preserve both regression checks.
