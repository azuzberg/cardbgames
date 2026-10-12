"""Persistence, cookie isolation, invalid requests, and concurrent revisions."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import COOKIE_NAME, create_app
from game import best_capture


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / "game.sqlite3")
        self.app = create_app({"TESTING": True, "DATABASE": self.database})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def start(self):
        response = self.client.post("/api/new", json={})
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    @staticmethod
    def move_payload(game):
        card = game["hand"][0]["id"]
        table = [item["id"] for item in game["table"]]
        return {"card_id": card, "take_ids": best_capture(card, table) or [], "revision": game["revision"]}

    def test_lobby_cookie_and_independent_browser(self):
        response = self.client.get("/api/state")
        self.assertEqual(response.get_json(), {"game": None, "stats": {"played": 0, "wins": 0, "losses": 0}, "history": []})
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.start()
        independent = self.app.test_client()
        self.assertIsNone(independent.get("/api/state").get_json()["game"])
        independent.set_cookie(COOKIE_NAME, "'; DROP TABLE sessions; --")
        self.assertIsNone(independent.get("/api/state").get_json()["game"])
        self.assertIsNotNone(self.client.get("/api/state").get_json()["game"])

    def test_saved_state_survives_app_restart(self):
        game = self.start()["game"]
        response = self.client.post("/api/play", json=self.move_payload(game))
        self.assertEqual(response.status_code, 200)
        expected = response.get_json()
        cookie = self.client.get_cookie(COOKIE_NAME).value
        restarted = create_app({"TESTING": True, "DATABASE": self.database}).test_client()
        restarted.set_cookie(COOKIE_NAME, cookie)
        self.assertEqual(restarted.get("/api/state").get_json(), expected)

    def test_stale_move_wrong_turn_and_repeated_bot_do_not_mutate(self):
        initial = self.start()["game"]
        wrong = self.client.post("/api/bot", json={"revision": initial["revision"]})
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(self.client.get("/api/state").get_json()["game"], initial)
        payload = self.move_payload(initial)
        after = self.client.post("/api/play", json=payload).get_json()["game"]
        stale = self.client.post("/api/play", json=payload)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["code"], "stale_revision")
        self.assertEqual(self.client.get("/api/state").get_json()["game"], after)
        bot = self.client.post("/api/bot", json={"revision": after["revision"]})
        self.assertEqual(bot.status_code, 200)
        self.assertEqual(self.client.post("/api/bot", json={"revision": after["revision"]}).status_code, 409)

    def test_invalid_json_schema_card_revision_and_oversize(self):
        state = self.start()
        invalid = [None, [], "string", {"revision": True}, {"revision": 0},
                   {"revision": "1"}, {"revision": 1, "unknown": "bad"}]
        for payload in invalid:
            response = self.client.post("/api/bot", json=payload)
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn("error", response.get_json())
        malformed = self.client.post("/api/play", data='{"revision":', content_type="application/json")
        self.assertEqual(malformed.status_code, 400)
        oversized = self.client.post("/api/new", data='{"x":"' + "a" * 20000 + '"}', content_type="application/json")
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.client.get("/api/state").get_json(), state)
        bad_card = self.client.post("/api/play", json={"card_id": "XX", "take_ids": [], "revision": state["game"]["revision"]})
        self.assertEqual(bad_card.status_code, 400)
        self.assertEqual(self.client.get("/api/state").get_json(), state)

    def test_new_match_maintains_monotonic_session_revision(self):
        old = self.start()["game"]
        new = self.start()["game"]
        self.assertNotEqual(old["id"], new["id"])
        self.assertGreater(new["revision"], old["revision"])
        self.assertEqual(self.client.post("/api/play", json=self.move_payload(old)).status_code, 409)
        self.assertEqual(self.client.get("/api/state").get_json()["stats"]["played"], 0)

    def test_simultaneous_moves_only_commit_once(self):
        game = self.start()["game"]
        cookie = self.client.get_cookie(COOKIE_NAME).value
        payload = self.move_payload(game)

        def send():
            client = self.app.test_client()
            client.set_cookie(COOKIE_NAME, cookie)
            return client.post("/api/play", json=payload).status_code

        with ThreadPoolExecutor(max_workers=2) as workers:
            statuses = list(workers.map(lambda _: send(), range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        saved = self.client.get("/api/state").get_json()["game"]
        self.assertEqual(saved["revision"], game["revision"] + 1)
        self.assertEqual(len(saved["hand"]), 3)

    def test_full_match_history_and_statistics_survive_reset_and_restart(self):
        state = self.start()
        for _ in range(48 * 100):
            game = state["game"]
            if game["status"] == "match_over":
                break
            if game["status"] == "round_over":
                response = self.client.post("/api/next-round", json={"revision": game["revision"]})
            elif game["turn"] == "bot":
                response = self.client.post("/api/bot", json={"revision": game["revision"]})
            else:
                response = self.client.post("/api/play", json=self.move_payload(game))
            self.assertEqual(response.status_code, 200)
            state = response.get_json()
        else:
            self.fail("Match did not finish")
        self.assertEqual(state["stats"]["played"], 1)
        self.assertEqual(state["stats"]["wins"] + state["stats"]["losses"], 1)
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["history"][0]["winner"], state["game"]["winner"])
        self.assertEqual(state["history"][0]["player_score"], state["game"]["scores"]["player"])
        self.assertEqual(state["history"][0]["rounds"], state["game"]["round"])
        finished_revision = state["game"]["revision"]
        self.assertEqual(self.client.post("/api/next-round", json={"revision": finished_revision}).status_code, 409)
        new = self.start()
        self.assertEqual(new["stats"], state["stats"])
        self.assertEqual(new["history"], state["history"])
        self.assertEqual(new["game"]["scores"], {"player": 0, "bot": 0})
        cookie = self.client.get_cookie(COOKIE_NAME).value
        restarted = create_app({"TESTING": True, "DATABASE": self.database}).test_client()
        restarted.set_cookie(COOKIE_NAME, cookie)
        self.assertEqual(restarted.get("/api/state").get_json(), new)


if __name__ == "__main__":
    unittest.main()
