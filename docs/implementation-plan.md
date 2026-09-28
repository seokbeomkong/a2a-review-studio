# A2A Review Studio Implementation Plan

> Execute inline with superpowers:executing-plans and test-driven-development. User authorized full implementation before reviewing the finished result.

**Goal:** Publish a reproducible A2A portfolio with an inspectable review/feedback workflow.
**Architecture:** FastAPI hosts a browser UI and three A2A 1.0 JSON-RPC agents. Official SDK clients call loopback HTTP; an asynchronous orchestrator owns bounded, isolated review runs. Claude uses the Messages API; deterministic demo responses are labeled separately.
**Tech Stack:** Python 3.12, a2a-sdk 1.1.5, FastAPI, HTTPX, vanilla HTML/CSS/JS.
**Spec:** docs/design.md (approved in conversation; user asks to build everything then provide review items).

## Global constraints

- Separate repository at `Documents/a2a-review-studio`; existing teaching workspace is untouched.
- Three experts: technical, business, user. One revision round; each expert requests feedback from the other two.
- Inputs 20–4000 characters; 4 simultaneous runs; 50 retained runs; 1-hour retention; 180-second run deadline.
- All A2A destinations fixed to the configured loopback base URL; process-local secret authenticates internal execution. Cards declare this requirement. No arbitrary URL or code execution.
- Demo clearly marked; no silent fallback when Claude fails. No API key exposed to browser/logs.
- Bind loopback; reject foreign Host/Origin; no production hosting claim.

## Review focus

1. Timeout or missing peer must mark a partial result, never claim unanimous review.
2. Concurrent runs must not share drafts or feedback.
3. Upstream model output must be validated, size limited, and safely rendered.
4. Untrusted web origins must not trigger API spending or internal A2A execution.
5. Polling failures and mobile layouts must leave the UI recoverable.

## Task 1: contracts and providers

Files: `models.py`, `providers.py`, `config.py`, `tests/test_providers.py`.
Interface: `ReviewRequest(proposal, mode)`, `AgentJob(run_id, phase, proposal, draft, feedback, author)`, `ReviewContent`, `Provider.generate(agent, job) -> ReviewContent`.
- [ ] Write tests for empty/oversized input, demo labeling and peer feedback incorporated in revised content, provider output parsing and API failure without fallback.
- [ ] Run pytest and observe missing implementation failure; implement; repeat until green.

## Task 2: real A2A and orchestration

Files: `protocol.py`, `runs.py`, `app.py`, `__main__.py`, `tests/test_workflow.py`.
Interface: `create_app(settings, provider_factory)`, `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/report`, `GET /api/config`; SDK cards and JSON-RPC at `/agents/{name}`.
- [ ] Write network integration tests using a real Uvicorn server: cards, SDK exchange, complete run with six peer feedback calls, isolation, failure, timeout, input rejection, origin/token enforcement and Markdown output.
- [ ] Observe failures, then implement HTTP transport, executors, run store and APIs. Run the whole suite.

## Task 3: browser UI

Files: `static/index.html`, `static/styles.css`, `static/app.js`.
- [ ] Implement semantic form, samples, live workflow graph, review tabs, final report, export and expandable wire log.
- [ ] Browser verify full demo, tab switching, new run, download, narrow 390px and wide 1440px layouts; save screenshots. Use textContent for all dynamic text.

## Task 4: delivery

Files: `README.md`, `docs/review-guide.md`, `docs/architecture.md`, `docs/verification.md`, `.github/workflows/ci.yml`, sample output.
- [ ] Fresh independent code review; fix important findings with regression tests.
- [ ] Run pytest, lint, format check, wheel/package smoke check, secret/file inventory check.
- [ ] Publish only this new repo publicly as `seokbeomkong/a2a-review-studio`, verify remote files and CI.
- [ ] Give user repository URL, local launch path, review checklist, and exact unverified live-model limitation.

## UI direction

Editorial workspace: warm off-white canvas, dark ink, restrained teal accent, fine ruled borders, prominent left-aligned title. Two columns: compact input brief and spacious collaboration/results. System Korean fonts, monospace metadata; 44px touch targets, visible focus, 390px stacking, reduced-motion support. No decorative imagery or remote font dependency. The catalog's retail ratings pattern is not applicable; task status and evidence hierarchy drive this app.
