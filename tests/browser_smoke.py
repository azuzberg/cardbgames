"""Optional real-browser checks; requires Playwright and Chromium (see TESTING.md)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка игры в настоящем браузере")
    repo = Path(__file__).resolve().parents[1]
    default_python = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    parser.add_argument("--python", default=str(default_python))
    parser.add_argument("--chromium", default=None)
    parser.add_argument("--screenshots", default=None)
    args = parser.parse_args()
    screenshots = Path(args.screenshots) if args.screenshots else None
    if screenshots:
        screenshots.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="cardbgames-browser-") as directory:
        env = os.environ.copy()
        env.update(PORT=str(port), CARDBGAMES_DATABASE=str(Path(directory) / "test.sqlite3"))
        with open(Path(directory) / "server.log", "w+", encoding="utf-8") as log:
            server = subprocess.Popen([args.python, "app.py"], cwd=repo, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        with urllib.request.urlopen(url + "/api/state", timeout=1) as response:
                            assert response.status == 200
                        break
                    except (OSError, AssertionError):
                        if server.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise AssertionError("HTTP server failed to start:\n" + log.read())
                        time.sleep(0.1)

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=args.chromium)
                    context = browser.new_context(viewport={"width": 1440, "height": 1050}, reduced_motion="reduce")
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def state():
                        response = page.request.get(url + "/api/state")
                        assert response.ok, response.text()
                        return response.json()

                    def wait_for_turn():
                        limit = time.monotonic() + 15
                        while time.monotonic() < limit:
                            current = state()["game"]
                            if current and (current["status"] != "playing" or current["turn"] == "player"):
                                return current
                            page.wait_for_timeout(40)
                        raise AssertionError("Bot did not complete its turn")

                    def screenshot(name):
                        if screenshots:
                            page.screenshot(path=str(screenshots / name), full_page=True)

                    page.goto(url)
                    page.locator('body[data-view="lobby"]').wait_for()
                    assert state()["game"] is None
                    screenshot("desktop-lobby.png")
                    page.locator(".rules-trigger").first.click()
                    page.locator("#rules-dialog[open]").wait_for()
                    page.keyboard.press("Escape")
                    page.locator("#rules-dialog[open]").wait_for(state="hidden")
                    page.locator("#start-game").click()
                    page.locator('body[data-view="game"]').wait_for()
                    current = wait_for_turn()
                    assert len(current["hand"]) == current["bot_hand_count"] == 4
                    assert len(current["table"]) == 4 and current["deck_count"] == 40
                    assert current["dealer"] == "bot"
                    screenshot("desktop-table.png")
                    initial_id, initial_revision = current["id"], current["revision"]
                    page.reload()
                    page.locator('body[data-view="game"]').wait_for()
                    restored = state()["game"]
                    assert (restored["id"], restored["revision"]) == (initial_id, initial_revision)

                    player_moves = 0
                    rounds = 0
                    capture_guard_checked = False
                    limit = time.monotonic() + 240
                    while time.monotonic() < limit:
                        current = wait_for_turn()
                        if current["status"] == "match_over":
                            page.locator("#result-dialog[open]").wait_for()
                            rounds = current["round"]
                            screenshot("match-result.png")
                            break
                        if current["status"] == "round_over":
                            page.locator("#result-dialog[open]").wait_for()
                            assert sum(current["round_result"]["points"].values()) == 5
                            assert sum(current["round_result"]["cards"].values()) == 52
                            if not rounds:
                                screenshot("round-result.png")
                            rounds = current["round"]
                            page.locator("#next-round-button").click()
                            next_deadline = time.monotonic() + 5
                            while state()["game"]["round"] == rounds:
                                assert time.monotonic() < next_deadline, "Next round did not start"
                                page.wait_for_timeout(25)
                            continue
                        assert current["turn"] == "player"
                        options = current["hints"]
                        card = next((item for item in current["hand"] if item["id"] in options), current["hand"][0])
                        card_id = card["id"]
                        page.locator(f'#player-hand button[data-card-id="{card_id}"]').click()
                        if options.get(card_id):
                            assert page.locator("#play-button").is_disabled(), "Mandatory capture allowed empty discard"
                            capture_guard_checked = True
                            for table_id in options[card_id]:
                                page.locator(f'#table-cards button[data-card-id="{table_id}"]').click()
                        page.locator("#play-button").click()
                        previous = current["revision"]
                        action_deadline = time.monotonic() + 5
                        while state()["game"]["revision"] == previous:
                            assert time.monotonic() < action_deadline, "Human move was not accepted"
                            page.wait_for_timeout(20)
                        player_moves += 1
                    else:
                        raise AssertionError("Full match did not end within 240 seconds")

                    result = state()
                    game = result["game"]
                    assert game["status"] == "match_over"
                    assert max(game["scores"].values()) >= 21
                    assert game["scores"]["player"] != game["scores"]["bot"]
                    assert result["stats"]["played"] == 1
                    assert result["stats"]["wins"] + result["stats"]["losses"] == 1
                    assert len(result["history"]) == 1
                    assert capture_guard_checked
                    assert player_moves == game["round"] * 24
                    page.reload()
                    page.locator("#result-dialog[open]").wait_for()
                    assert state()["stats"] == result["stats"]
                    assert not errors, errors

                    # A separate cookie jar must receive an independent mobile game.
                    mobile = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce", is_mobile=True, has_touch=True)
                    phone = mobile.new_page()
                    phone.on("pageerror", lambda error: errors.append(str(error)))
                    phone.goto(url)
                    phone.locator('body[data-view="lobby"]').wait_for()
                    assert phone.request.get(url + "/api/state").json()["game"] is None
                    assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile lobby overflows horizontally"
                    if screenshots:
                        phone.screenshot(path=str(screenshots / "mobile-lobby.png"), full_page=True)
                    phone.locator("#start-game").click()
                    phone.locator('body[data-view="game"]').wait_for()
                    phone.locator("#player-hand button").first.wait_for()
                    assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile table overflows horizontally"
                    assert phone.locator("#player-hand").bounding_box()["y"] > phone.locator("#bot-hand").bounding_box()["y"]
                    assert phone.locator("#deck-stack").bounding_box()["x"] < phone.locator("#table-cards").bounding_box()["x"]
                    if screenshots:
                        phone.screenshot(path=str(screenshots / "mobile-table.png"), full_page=True)
                    for width in (320, 768):
                        phone.set_viewport_size({"width": width, "height": 844})
                        assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Table overflow at {width}px"

                    # Normal-motion dealing and capture must visibly move cards.
                    animated = browser.new_context(viewport={"width": 1440, "height": 1050}, reduced_motion="no-preference")
                    moving = animated.new_page()
                    moving.on("pageerror", lambda error: errors.append(str(error)))
                    moving.goto(url)
                    moving.locator('body[data-view="lobby"]').wait_for()
                    moving.locator("#start-game").click()
                    moving.locator(".flying-card").first.wait_for(state="visible")
                    assert moving.locator(".flying-card").first.evaluate("element => getComputedStyle(element).visibility") == "visible"
                    if screenshots:
                        moving.screenshot(path=str(screenshots / "animated-deal.png"), full_page=True)
                    moving.wait_for_function("document.querySelectorAll('.flying-card').length === 0")
                    animated_capture = False
                    for _ in range(24):
                        moving.wait_for_function("!document.querySelector('#hint-button').disabled")
                        current = moving.request.get(url + "/api/state").json()["game"]
                        if current["status"] != "playing":
                            break
                        options = current["hints"]
                        card = next((item for item in current["hand"] if item["id"] in options), current["hand"][0])
                        moving.locator(f'#player-hand button[data-card-id="{card["id"]}"]').click()
                        for table_id in options.get(card["id"], []):
                            moving.locator(f'#table-cards button[data-card-id="{table_id}"]').click()
                        moving.locator("#play-button").click()
                        moving.locator(".flying-card").first.wait_for(state="visible")
                        assert moving.locator(".flying-card").first.evaluate("element => getComputedStyle(element).visibility") == "visible"
                        if options.get(card["id"]):
                            # Multiple visible ghosts distinguish capture from a single discard.
                            moving.wait_for_function("document.querySelectorAll('.flying-card').length >= 2")
                            animated_capture = True
                            moving.wait_for_function("document.querySelectorAll('.flying-card').length === 0")
                            break
                        moving.wait_for_function("!document.querySelector('#hint-button').disabled")
                    assert animated_capture, "No capture animation demonstrated"
                    assert not errors, errors
                    print(json.dumps({"browser": "Chromium", "full_match_rounds": rounds, "human_moves": player_moves, "winner": game["winner"], "scores": game["scores"], "desktop": "passed", "mobile": "passed", "animations": "passed", "javascript_errors": errors}, ensure_ascii=False))
                    browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    main()
