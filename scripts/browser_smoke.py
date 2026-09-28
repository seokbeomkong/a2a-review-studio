"""Run against a local server; saves review screenshots and checks real user flows.

python scripts/browser_smoke.py http://127.0.0.1:8765
Requires the [browser] extra and `python -m playwright install chromium`.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    root = Path(__file__).resolve().parents[1]
    screenshots = root / "docs" / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect(page.get_by_role("button", name="검토 시작하기")).to_be_enabled()
        page.screenshot(path=str(screenshots / "desktop.png"), full_page=True)
        page.get_by_role("button", name="고객 문의 자동 분류").click()
        page.get_by_role("button", name="검토 시작하기").click()
        expect(page.locator("#run-status")).to_have_text("검토 완료", timeout=20000)
        expect(page.locator("#peer-count")).to_have_text("6 / 6")
        expect(page.locator("#request-count")).to_have_text("12 MESSAGES")
        expect(page.locator("#result-panel")).to_contain_text("검증 지표")
        page.screenshot(path=str(screenshots / "review-complete.png"), full_page=True)
        with page.expect_download() as download_info:
            page.get_by_role("link", name="결과 내려받기").click()
        downloaded = download_info.value
        downloaded.save_as(root / "docs" / "sample-report.md")
        assert "LLM 미사용" in (root / "docs" / "sample-report.md").read_text(encoding="utf-8")
        page.get_by_role("tab", name="기술", exact=True).click()
        expect(page.locator("#result-panel")).to_contain_text("피드백 반영")
        page.get_by_text("피드백 이전 초안 비교하기", exact=True).click()
        page.get_by_role("tab", name="기술", exact=True).press("ArrowRight")
        expect(page.get_by_role("tab", name="비용", exact=True)).to_be_focused()
        expect(page.get_by_role("tab", name="비용", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        page.get_by_role("tab", name="최종 실행안").click()
        page.locator("#trace > summary").click()
        expect(page.locator(".trace-row")).to_have_count(24)
        page.locator(".trace-row summary").first.click()
        expect(page.locator(".trace-row pre").first).to_contain_text("SendMessage")
        # Render untrusted input as text; no HTML executes through the result or trace.
        page.get_by_role("textbox", name="업무 개선 아이디어").fill(
            '<img src=x onerror="window.__xss=true"> 주간 보고서 자동화 제안을 검토합니다.'
        )
        page.get_by_role("button", name="검토 시작하기").click()
        expect(page.locator("#run-status")).to_have_text("검토 완료", timeout=20000)
        expect(page.locator("#result-panel")).to_contain_text("<img src=x")
        assert page.evaluate("window.__xss") is None
        assert page.locator("#result-panel img").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("button", name="주간 보고서 자동화").click()
        page.get_by_role("button", name="검토 시작하기").click()
        page.reload()
        expect(page.locator("#run-status")).to_have_text("검토 완료", timeout=20000)
        expect(page.locator("#result-panel")).to_contain_text("주간 업무")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
        # A transient error during reload must not discard a recoverable run ID.
        page.get_by_role("button", name="주간 보고서 자동화").click()
        with page.expect_response(
            lambda r: r.url.endswith("/api/runs") and r.request.method == "POST"
        ) as started:
            page.get_by_role("button", name="검토 시작하기").click()
        saved_id = started.value.json()["id"]
        page.evaluate('(id) => sessionStorage.setItem("studio-run", id)', saved_id)
        page.route(
            "**/api/runs/" + saved_id,
            lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"detail":"temporary"}'
            ),
        )
        page.reload()
        expect(page.get_by_role("button", name="검토 시작하기")).to_be_enabled()
        assert page.evaluate('sessionStorage.getItem("studio-run")') == saved_id
        page.unroute("**/api/runs/" + saved_id)
        page.reload()
        expect(page.locator("#run-status")).to_have_text("검토 완료", timeout=20000)
        assert not errors, errors
        browser.close()
    print(
        json.dumps(
            {
                "browser": "Chromium",
                "flows": [
                    "demo",
                    "12 A2A calls",
                    "export",
                    "tabs + keyboard",
                    "24 trace events",
                    "XSS text rendering",
                    "new run",
                    "reload recovery",
                    "390px responsive",
                ],
                "page_errors": errors,
            }
        )
    )


if __name__ == "__main__":
    main()
