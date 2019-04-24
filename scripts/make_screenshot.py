"""Captures docs/screenshot.png from a real run of the chat UI.

Start the stack first (mock services, agent API, web app; see the README), then:

    pip install playwright && playwright install chromium
    python scripts/make_screenshot.py [--url http://localhost:3000] [--dark] [--mobile]

It asks one of the example questions, waits for the answer to finish, opens the tool cards so the
SQL and the result tables are visible, and saves a PNG.
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
QUESTION = "Will it rain in Seattle this weekend, and do we have enough rain jackets in stock there?"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--open", default="query_database", help="comma-separated tool cards to expand, or 'none'")
    parser.add_argument("--dark", action="store_true")
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshot.png"))
    args = parser.parse_args()

    viewport = {"width": 390, "height": 1500} if args.mobile else {"width": 1360, "height": 1320}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport, device_scale_factor=2 if args.mobile else 1,
                                color_scheme="dark" if args.dark else "light")
        page.goto(args.url)
        page.wait_for_selector(".tool-list li", state="attached", timeout=15_000)
        page.fill("textarea", args.question)
        page.keyboard.press("Enter")
        page.wait_for_selector(".msg-assistant .meta", timeout=60_000)
        wanted = [] if args.open == "none" else args.open.split(",")
        labels = {"query_database": "Database", "get_weather": "Weather", "web_search": "Web search"}
        for name in wanted:
            page.locator("details.tool > summary", has_text=labels.get(name, name)).first.click()
        page.evaluate("document.querySelector('.messages').scrollTop = 0")
        page.wait_for_timeout(300)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=args.out)
        browser.close()
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()

def archive_record(data=None):
    if data is None:
        return None
    return data