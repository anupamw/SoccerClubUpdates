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
            expect(page.locator("#matches-content tbody tr")).to_have_count(24)
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


def test_favorite_team_selection_navigation_and_overview():
    username = f"favorite-{uuid4().hex[:10]}"
    password = f"password-{uuid4().hex}"
    base_url = os.getenv("SOCCER_BASE_URL", "http://127.0.0.1:8000")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.route(
                "https://example.test/arsenal.svg",
                lambda route: route.fulfill(
                    status=200,
                    content_type="image/svg+xml",
                    body='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5"/></svg>',
                ),
            )
            page.goto(base_url, wait_until="networkidle")
            page.locator("#signup-tab").click()
            page.locator("#signup-username").fill(username)
            page.locator("#signup-password").fill(password)
            page.locator("#signup-form").get_by_role("button", name="Create account").click()
            expect(page.locator("#shell")).to_be_visible()
            expect(page.locator("#overview-content .panel").filter(has_text="Recent results").locator("tbody tr")).to_have_count(10)
            expect(page.locator("#overview-content .panel").filter(has_text="Upcoming fixtures").locator("tbody tr")).to_have_count(10)

            page.get_by_role("button", name="Account").click()
            team_select = page.locator("#favorite-team-select")
            expect(team_select.locator("option")).to_have_count(21)
            team_select.select_option("2")
            expect(page.locator("#favorite-preview .team-crest")).to_have_text("AV")
            team_select.select_option("1")
            expect(page.locator("#favorite-preview img")).to_be_visible()
            page.get_by_role("button", name="Save favourite team").click()
            favorite_nav = page.locator("#favorite-nav")
            expect(favorite_nav).to_be_visible()
            expect(favorite_nav).to_have_text("Arsenal")

            favorite_nav.click()
            expect(page.locator("#page-title")).to_have_text("Arsenal")
            expect(page.locator("#favorite-content h2")).to_have_text("Arsenal")
            expect(page.locator('[aria-label="Arsenal recent results"] tbody tr')).to_have_count(10)
            expect(page.locator('[aria-label="Arsenal upcoming fixtures"] tbody tr')).to_have_count(10)
            expect(page.locator("#favorite-content")).not_to_contain_text("Unrelated")
            expect(page.locator("#favorite-content .favorite-row")).to_contain_text("Favourite")

            page.get_by_role("button", name="Matches").click()
            expect(page.locator("#matches-content tbody tr")).to_have_count(24)
            expect(page.locator("#matches-content tbody tr.favorite-match-row")).to_have_count(22)
            expect(page.locator("#matches-content .favorite-marker")).to_have_count(22)

            page.get_by_role("button", name="Table").click()
            expect(page.locator("#table-content tbody tr")).to_have_count(20)
            expect(page.locator("#table-content tbody tr.favorite-row")).to_have_count(1)
            expect(page.locator("#table-content tr.favorite-row")).to_contain_text("Arsenal")
            expect(page.locator("#table-content tr.favorite-row")).to_contain_text("Favourite")

            page.get_by_role("button", name="Overview").click()
            expect(page.locator('#overview-content [aria-label="All league standings"] tbody tr')).to_have_count(20)
            expect(page.locator("#overview-content tr.favorite-row")).to_contain_text("Arsenal")
            expect(page.locator("#overview-content tr.favorite-row")).to_contain_text("Favourite")
            recent_panel = page.locator("#overview-content .panel").filter(has_text="Recent results")
            upcoming_panel = page.locator("#overview-content .panel").filter(has_text="Upcoming fixtures")
            expect(recent_panel.locator("tbody tr")).to_have_count(10)
            expect(recent_panel.locator("tbody tr.favorite-match-row")).to_have_count(10)
            expect(recent_panel.locator(".favorite-marker")).to_have_count(10)
            expect(upcoming_panel.locator("tbody tr")).to_have_count(10)
            expect(upcoming_panel.locator("tbody tr.favorite-match-row")).to_have_count(10)
            expect(upcoming_panel.locator(".favorite-marker")).to_have_count(10)

            page.reload(wait_until="networkidle")
            expect(page.locator("#shell")).to_be_visible()
            expect(page.locator("#favorite-nav")).to_be_visible()
            expect(page.locator("#favorite-nav")).to_have_text("Arsenal")
            page.get_by_role("button", name="Account").click()
            expect(page.locator("#favorite-team-select")).to_have_value("1")
        finally:
            browser.close()


def test_timezone_selection_formats_timestamps_and_persists():
    username = f"timezone-{uuid4().hex[:10]}"
    password = f"password-{uuid4().hex}"
    base_url = os.getenv("SOCCER_BASE_URL", "http://127.0.0.1:8000")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            def league_response(route):
                response = route.fetch()
                data = response.json()
                finished = [match for match in data["matches"] if match["status"] == "FINISHED"]
                for index, match in enumerate(finished[:-1]):
                    match["utc_date"] = f"2026-03-07T06:{index:02d}:00Z"
                finished[-1]["utc_date"] = "2026-03-08T06:30:00Z"
                upcoming = [
                    match
                    for match in data["matches"]
                    if match["status"] in {"TIMED", "SCHEDULED"}
                ]
                for index, match in enumerate(upcoming):
                    match["utc_date"] = f"2026-03-08T07:{30 + index:02d}:00Z"
                data["collection_status"]["last_updated"] = "2026-03-08T07:30:00Z"
                route.fulfill(response=response, json=data)

            page.route("**/api/v1/league", league_response)
            page.goto(base_url, wait_until="networkidle")
            page.locator("#signup-tab").click()
            page.locator("#signup-username").fill(username)
            page.locator("#signup-password").fill(password)
            page.locator("#signup-form").get_by_role("button", name="Create account").click()
            expect(page.locator("#shell")).to_be_visible()

            page.get_by_role("button", name="Account").click()
            timezone_select = page.locator("#timezone-select")
            expect(timezone_select).to_have_value("UTC")
            timezone_select.select_option("Asia/Kolkata")
            page.get_by_role("button", name="Save timezone").click()
            expect(page.locator("#timezone-status")).to_contain_text("Asia/Kolkata")
            page.get_by_role("button", name="Overview").click()

            expected_kolkata = page.evaluate(
                """new Intl.DateTimeFormat(undefined, {
                    weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "numeric",
                    minute: "2-digit", timeZone: "Asia/Kolkata", timeZoneName: "short"
                }).format(new Date("2026-03-08T06:30:00Z"))"""
            )
            recent = page.locator("#overview-content .panel").filter(has_text="Recent results")
            expect(recent.locator("tbody tr").first.locator("td").first).to_have_text(expected_kolkata)
            expect(page.locator("#overview-content")).to_contain_text("Kickoff (Asia/Kolkata)")

            page.get_by_role("button", name="Account").click()
            timezone_select = page.locator("#timezone-select")
            timezone_select.select_option("America/New_York")
            page.get_by_role("button", name="Save timezone").click()
            expect(page.locator("#timezone-status")).to_contain_text("America/New_York")
            page.get_by_role("button", name="Overview").click()

            expected_before_dst = page.evaluate(
                """new Intl.DateTimeFormat(undefined, {
                    weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "numeric",
                    minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short"
                }).format(new Date("2026-03-08T06:30:00Z"))"""
            )
            expected_after_dst = page.evaluate(
                """new Intl.DateTimeFormat(undefined, {
                    weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "numeric",
                    minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short"
                }).format(new Date("2026-03-08T07:30:00Z"))"""
            )
            recent = page.locator("#overview-content .panel").filter(has_text="Recent results")
            upcoming = page.locator("#overview-content .panel").filter(has_text="Upcoming fixtures")
            expect(recent.locator("tbody tr").first.locator("td").first).to_have_text(expected_before_dst)
            expect(upcoming.locator("tbody tr").first.locator("td").first).to_have_text(expected_after_dst)
            expect(page.locator("#overview-content")).to_contain_text("Kickoff (America/New_York)")

            page.reload(wait_until="networkidle")
            expect(page.locator("#shell")).to_be_visible()
            expect(page.locator("#overview-content")).to_contain_text("Kickoff (America/New_York)")
            page.get_by_role("button", name="Account").click()
            expect(page.locator("#timezone-select")).to_have_value("America/New_York")
        finally:
            browser.close()
