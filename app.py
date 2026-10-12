"""Flask entrypoint. Run with Python 3.13.3: ``python app.py``."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from game import GameError, bot_turn, next_round, play_card
from storage import Storage

COOKIE_NAME = "cardbgames_session"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("CARDBGAMES_DATABASE", os.path.join(app.instance_path, "cardbgames.sqlite3")),
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_SECURE=False,
    )
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False
    storage = Storage(app.config["DATABASE"])
    app.extensions["game_storage"] = storage

    @app.before_request
    def browser_session():
        token = request.cookies.get(COOKIE_NAME, "")
        g.session_id = token if TOKEN_RE.fullmatch(token) else secrets.token_urlsafe(32)
        g.new_session = g.session_id != token

    @app.after_request
    def response_headers(response):
        if g.get("new_session", False):
            response.set_cookie(COOKIE_NAME, g.session_id, max_age=365 * 24 * 60 * 60,
                                httponly=True, samesite="Lax", secure=app.config["SESSION_COOKIE_SECURE"])
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def body(allowed: set[str], required: set[str]) -> dict:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise GameError("Отправьте корректный JSON-объект.", "invalid_json")
        if set(payload) - allowed or not required.issubset(payload):
            raise GameError("Запрос содержит неверный набор параметров.", "invalid_request")
        if "revision" in required and (type(payload["revision"]) is not int or payload["revision"] < 1):
            raise GameError("Укажите текущую версию состояния игры.", "invalid_revision")
        return payload

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def state():
        return jsonify(storage.state(g.session_id))

    @app.post("/api/new")
    def start_game():
        body(set(), set())
        return jsonify(storage.start(g.session_id)), 201

    @app.post("/api/play")
    def play():
        payload = body({"card_id", "take_ids", "revision"}, {"card_id", "take_ids", "revision"})
        result = storage.mutate(g.session_id, payload["revision"],
                                lambda game: play_card(game, "player", payload["card_id"], payload["take_ids"]))
        return jsonify(result)

    @app.post("/api/bot")
    def bot():
        payload = body({"revision"}, {"revision"})
        return jsonify(storage.mutate(g.session_id, payload["revision"], bot_turn))

    @app.post("/api/next-round")
    def advance_round():
        payload = body({"revision"}, {"revision"})
        return jsonify(storage.mutate(g.session_id, payload["revision"], next_round))

    @app.errorhandler(GameError)
    def game_error(error):
        return jsonify(error=error.message, code=error.code), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: "Некорректный запрос.", 404: "Адрес не найден.",
                    405: "Этот способ запроса не поддерживается.",
                    413: "Запрос слишком большой.", 415: "Требуется формат JSON."}
        return jsonify(error=messages.get(error.code, "Не удалось выполнить запрос."),
                       code=f"http_{error.code}"), error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception("SQLite operation failed")
        return jsonify(error="Не удалось сохранить игру. Повторите запрос.", code="database_error"), 503

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
