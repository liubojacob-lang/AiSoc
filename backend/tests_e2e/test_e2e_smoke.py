"""E2E smoke: real browser against a RUNNING full stack (Docker compose).

Opt-in: set E2E_BASE_URL (default http://localhost:8080) — skipped from the
default `pytest tests/` run (tests_e2e/ is outside testpaths).
Requires Chrome installed; playwright uses the system browser (channel=chrome).
"""

from __future__ import annotations

import os

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8080")
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "admin@aisoc.dev")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "admin12345")


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def _login(page) -> None:
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_role("textbox", name="邮箱").fill(ADMIN_EMAIL)
    page.get_by_role("textbox", name="密码").fill(ADMIN_PASSWORD)
    page.get_by_role("textbox", name="密码").press("Enter")
    expect(page.get_by_role("heading", name="安全运营工作台")).to_be_visible(timeout=10_000)


def test_e2e_login_dashboard(page):
    _login(page)
    # KPI 卡片与看板数据
    expect(page.get_by_text("AI 降噪率")).to_be_visible()
    expect(page.get_by_text("LLM 成本（30 天）")).to_be_visible()


def test_e2e_alerts_and_triage_report(page):
    page.goto(f"{BASE_URL}/alerts")
    page.wait_for_load_state("domcontentloaded")
    rows = page.locator("main .divide-y > button")
    rows.first.wait_for(state="visible", timeout=10_000)
    rows.first.click()
    # AI 研判报告要素
    expect(page.get_by_text("AI 研判结论")).to_be_visible(timeout=10_000)
    expect(page.get_by_text("证据链")).to_be_visible()
    # 关闭抽屉，避免遮罩影响后续测试
    page.keyboard.press("Escape")


def test_e2e_assistant_chat(page):
    page.goto(f"{BASE_URL}/assistant")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_role("textbox", name="提问").fill("现在有多少告警？")
    page.get_by_role("textbox", name="提问").press("Enter")
    # 确定性 FakeLLM 的摘要必然包含“告警”字样与条目
    expect(page.get_by_text("当前查询到").first).to_be_visible(timeout=20_000)


def test_e2e_notifications_bell(page):
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("domcontentloaded")
    bell = page.get_by_role("button", name="通知")
    expect(bell).to_be_visible(timeout=10_000)
    bell.click()
    expect(page.get_by_text("全部已读")).to_be_visible()
