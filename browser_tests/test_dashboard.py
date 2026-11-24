import os
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def test_signup_navigation_password_change_and_logout():
    username = f"fan-{uuid4().hex[:10]}"
    old_password = f"old-{uuid4().hex}"
    new_password = f"new-{uuid4().hex}"
    base_url = os.getenv("SOCCER_BASE_URL", "http://127.0.0.1:8000")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(base_url, wait_until="networkidle")
            expect(page.get_by_role("heading", name="Soccer Club Updates")).to_be_visible()
            page.locator("#signup-tab").click()
            page.locator("#signup-username").fill(username)
            page.locator("#signup-password").fill(old_password)
            page.locator("#signup-form").get_by_role("button", name="Create account").click()
            expect(page.locator("#shell")).to_be_visible()
            expect(page.locator("#welcome-user")).to_have_text(username)
            expect(page.get_by_text("Manchester United updates for the week ahead.", exact=True)).to_be_visible()

            for label, title in [("Matches", "Matches"), ("News", "Club news"), ("Squad", "Squad"), ("Table", "Premier League table")]:
                page.get_by_role("button", name=label).click()
                expect(page.locator("#page-title")).to_have_text(title)
            page.get_by_role("button", name="Overview").click()
            expect(page.get_by_text("Liverpool", exact=True).first).to_be_visible()

            page.get_by_role("button", name="Password").click()
            page.locator("#current-password").fill(old_password)
            page.locator("#new-password").fill(new_password)
            page.get_by_role("button", name="Update password").click()
            expect(page.locator("#shell")).to_be_hidden()
            expect(page.get_by_role("status")).to_contain_text("Sign in")

            page.locator("#username").fill(username)
            page.locator("#password").fill(old_password)
            page.locator("#signin-form").get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("status")).to_have_text("Invalid username or password")
            page.locator("#password").fill(new_password)
            page.locator("#signin-form").get_by_role("button", name="Sign in").click()
            expect(page.locator("#shell")).to_be_visible()

            page.get_by_role("button", name="Log out").click()
            expect(page.locator("#auth-panel")).to_be_visible()
            assert page.evaluate("sessionStorage.getItem('soccer-access-token')") is None
        finally:
            browser.close()
