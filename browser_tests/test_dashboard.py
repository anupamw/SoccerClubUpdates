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
            freshness_override = {"value": None}

            def league_response(route):
                response = route.fetch()
                data = response.json()
                if freshness_override["value"] == "stale":
                    data["collection_status"]["freshness"] = "stale"
                    data["collection_status"]["error_summary"] = "Most recent refresh failed"
                elif freshness_override["value"] == "unavailable":
                    data["collection_status"]["freshness"] = "unavailable"
                route.fulfill(response=response, json=data)

            page.route("**/api/v1/league", league_response)
            page.goto(base_url, wait_until="networkidle")
            expect(page.get_by_role("heading", name="Soccer Club Updates")).to_be_visible()
            page.locator("#signup-tab").click()
            page.locator("#signup-username").fill(username)
            page.locator("#signup-password").fill(old_password)
            page.locator("#signup-form").get_by_role("button", name="Create account").click()
            expect(page.locator("#shell")).to_be_visible()
            expect(page.locator("#welcome-user")).to_have_text(username)
            expect(page.locator("#content")).to_contain_text(
                "Premier League standings, recent results and upcoming fixtures."
            )
            expect(page.locator("#overview-content .status-pill")).to_have_text("fresh")
            overview_standings = page.locator(
                '#overview-content [aria-label="All league standings"]'
            )
            expect(overview_standings.locator("tbody tr")).to_have_count(20)
            expect(overview_standings).to_contain_text("Wolverhampton Wanderers")
            assert overview_standings.evaluate(
                "(region) => region.scrollHeight > region.clientHeight"
            )

            page.get_by_role("button", name="Matches").click()
            expect(page.locator("#matches-content .status-pill")).to_have_text("fresh")
            expect(page.locator("#matches-content tbody tr")).to_have_count(10)
            expect(page.locator("#matches-content .table-wrap")).to_have_attribute("tabindex", "0")
            expect(page.locator("#matches-content .table-wrap")).to_have_attribute(
                "aria-label", "All league matches"
            )
            expect(page.locator("#matches-content")).to_contain_text("Arsenal")
            expect(page.locator("#matches-content")).to_contain_text("Manchester United")
            expect(page.locator("#matches-content")).to_contain_text("FINISHED")

            page.get_by_role("button", name="Table").click()
            expect(page.locator("#table-content .status-pill")).to_have_text("fresh")
            expect(page.locator("#table-content tbody tr")).to_have_count(20)
            expect(page.locator("#table-content .table-wrap")).to_have_attribute("tabindex", "0")
            assert page.locator("#table-content .table-wrap").evaluate(
                "(region) => region.scrollHeight > region.clientHeight"
            )
            expect(page.locator("#table-content")).to_contain_text("Wolverhampton Wanderers")

            freshness_override["value"] = "stale"
            page.get_by_role("button", name="Matches").click()
            expect(page.locator("#matches-content .status-pill")).to_have_text("stale")
            expect(page.locator("#matches-content")).to_contain_text("Most recent refresh failed")

            freshness_override["value"] = "unavailable"
            page.get_by_role("button", name="Table").click()
            expect(page.locator("#table-content .status-pill")).to_have_text("unavailable")
            expect(page.locator("#table-content")).to_contain_text("League data is unavailable")

            for label, title in [("News", "Club news"), ("Squad", "Squad")]:
                page.get_by_role("button", name=label).click()
                expect(page.locator("#page-title")).to_have_text(title)
                expect(page.locator("#content")).to_contain_text("not collected")

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
