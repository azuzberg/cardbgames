"""Check a running server using a separate cookie jar, without touching user games."""

import argparse
from http.cookiejar import CookieJar
import json
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description="Проверка запущенного игрового сервера")
    parser.add_argument("--url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {} if payload is None else {"Content-Type": "application/json"}
        with browser.open(Request(base + path, data=data, headers=headers), timeout=15) as response:
            return json.load(response)

    assert request("/api/state")["game"] is None
    game = request("/api/new", {})["game"]
    assert len(game["hand"]) == game["bot_hand_count"] == 4
    assert game["deck_count"] == 40 and len(game["table"]) == 4
    card = game["hand"][0]["id"]
    game = request("/api/play", {"card_id": card, "take_ids": game["hints"].get(card, []), "revision": game["revision"]})["game"]
    assert game["turn"] == "bot" and len(game["hand"]) == 3
    game = request("/api/bot", {"revision": game["revision"]})["game"]
    assert game["turn"] == "player" and game["bot_hand_count"] == 3
    assert request("/api/state")["game"] == game
    print("HTTP, SQLite, раздача, ход игрока, ход бота и сохранение: OK")


if __name__ == "__main__":
    main()
