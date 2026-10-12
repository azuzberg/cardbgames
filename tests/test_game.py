"""Rule examples, complete matches, and server-side information boundaries."""

import random
import unittest
from copy import deepcopy

from game import (CARDS, GameError, _finish_round, best_capture, bot_turn,
                  choose_bot_move, new_game, next_round, play_card, public_state,
                  score_captured)


class CaptureRulesTests(unittest.TestCase):
    def setUp(self):
        self.game = new_game(rng=random.Random(7))
        self.game["hands"] = {"player": ["S10", "SK", "SA"], "bot": ["D3"]}
        self.game["table"] = ["D10", "C7", "H2", "CA", "DK", "HK", "DQ"]

    def test_numeric_capture_allows_equal_card_or_sum(self):
        for selected in (["D10"], ["C7", "H2", "CA"]):
            game = deepcopy(self.game)
            play_card(game, "player", "S10", selected)
            self.assertEqual(game["captured"]["player"], ["S10"] + [item for item in self.game["table"] if item in selected])
            self.assertEqual(game["last_capture"], "player")
            self.assertEqual(game["events"][0]["take"], [CARDS[item] for item in selected])

    def test_numeric_cannot_add_face_zeroes(self):
        before = deepcopy(self.game)
        with self.assertRaises(GameError) as error:
            play_card(self.game, "player", "S10", ["D10", "DQ"])
        self.assertEqual(error.exception.code, "invalid_capture")
        self.assertEqual(self.game, before)

    def test_picture_takes_exactly_one_same_rank(self):
        play_card(self.game, "player", "SK", ["DK"])
        self.assertIn("HK", self.game["table"])
        self.assertEqual(self.game["captured"]["player"], ["SK", "DK"])
        for selected in (["DK", "HK"], ["DQ"]):
            game = new_game(rng=random.Random(8))
            game["hands"]["player"] = ["SK"]
            game["table"] = ["DK", "HK", "DQ"]
            with self.assertRaises(GameError):
                play_card(game, "player", "SK", selected)

    def test_capture_mandatory_for_chosen_card(self):
        before = deepcopy(self.game)
        with self.assertRaises(GameError) as error:
            play_card(self.game, "player", "S10", [])
        self.assertEqual(error.exception.code, "capture_required")
        self.assertEqual(self.game, before)

    def test_other_hand_card_without_capture_can_discard(self):
        self.game["table"].remove("CA")
        play_card(self.game, "player", "SA", [])
        self.assertEqual(self.game["table"][-1], "SA")
        self.assertEqual(self.game["last_capture"], None)

    def test_duplicates_unknowns_and_wrong_turn_do_not_change_state(self):
        for card_id, selected in (("S10", ["D10", "D10"]), ("S10", ["S2"]),
                                  ("D3", []), ("S10", None), ("S10", [["D10"]])):
            game = deepcopy(self.game)
            with self.assertRaises(GameError):
                play_card(game, "player", card_id, selected)
            self.assertEqual(game, self.game)
        with self.assertRaises(GameError):
            play_card(self.game, "bot", "D3", [])

    def test_best_capture_never_reuses_a_card(self):
        self.assertIsNone(best_capture("S4", ["C2"]))
        self.assertEqual(best_capture("S4", ["C2", "H2"]), ["C2", "H2"])
        self.assertIsNone(best_capture("SA", ["CK", "DQ"]))
        self.assertEqual(best_capture("SA", ["CA"]), ["CA"])
        self.assertIsNone(best_capture("SK", ["SQ", "C10"]))

    def test_best_capture_existence_matches_exhaustive_search(self):
        rng = random.Random(430)
        deck = list(CARDS)
        for _ in range(80):
            hand_card, *table = rng.sample(deck, 11)
            card = CARDS[hand_card]
            valid = []
            for mask in range(1, 1 << len(table)):
                subset = [table[i] for i in range(len(table)) if mask & (1 << i)]
                values = [CARDS[item]["value"] for item in subset]
                if card["value"] and all(values) and sum(values) == card["value"]:
                    valid.append(subset)
                elif card["value"] == 0 and len(subset) == 1 and CARDS[subset[0]]["rank"] == card["rank"]:
                    valid.append(subset)
            actual = best_capture(hand_card, table)
            self.assertEqual(actual is not None, bool(valid))
            if actual is not None:
                self.assertIn(actual, valid)


class ScoringAndRoundTests(unittest.TestCase):
    def test_score_categories_and_tie_cards(self):
        player = list(CARDS)[:26]
        bot = list(CARDS)[26:]
        result = score_captured({"player": player, "bot": bot})
        self.assertEqual(result["cards"], {"player": 26, "bot": 26})
        self.assertEqual(result["points"], {"player": 4, "bot": 1})
        self.assertEqual(result["clubs"], {"player": 13, "bot": 0})

    def test_club_tie_gives_neither_point(self):
        result = score_captured({"player": ["C2", "D10", "HA"], "bot": ["C3"]})
        self.assertEqual(result["rows"][1]["player"], 0)
        self.assertEqual(result["rows"][1]["bot"], 0)
        self.assertEqual(result["points"], {"player": 4, "bot": 0})

    def test_leftover_goes_to_last_capture_or_dealer(self):
        for last, expected in (("player", "player"), (None, "bot")):
            game = new_game(rng=random.Random(5))
            game["captured"] = {"player": [], "bot": []}
            game["table"] = list(CARDS)
            game["last_capture"] = last
            _finish_round(game)
            self.assertEqual(game["round_result"]["remaining_to"], expected)
            self.assertEqual(game["round_result"]["remaining_count"], 52)
            self.assertEqual(len(game["captured"][expected]), 52)
            self.assertEqual(game["table"], [])

    def test_target_tie_continues_and_next_dealer_alternates(self):
        game = new_game(rng=random.Random(2))
        game["captured"] = {"player": list(CARDS)[:26], "bot": list(CARDS)[26:]}
        game["table"] = []
        game["scores"] = {"player": 17, "bot": 20}
        _finish_round(game)
        self.assertEqual(game["scores"], {"player": 21, "bot": 21})
        self.assertEqual(game["status"], "round_over")
        next_round(game, random.Random(3))
        self.assertEqual(game["dealer"], "player")
        self.assertEqual(game["turn"], "bot")
        self.assertEqual(game["round"], 2)
        self.assertEqual(game["scores"], {"player": 21, "bot": 21})
        self.assertEqual(len(game["table"]), 4)

    def test_winner_decided_only_after_whole_round(self):
        game = new_game(rng=random.Random(2))
        game["scores"] = {"player": 30, "bot": 4}
        self.assertEqual(game["status"], "playing")
        game["captured"] = {"player": list(CARDS)[:26], "bot": list(CARDS)[26:]}
        game["table"] = []
        _finish_round(game)
        self.assertEqual(game["status"], "match_over")
        self.assertEqual(game["winner"], "player")
        with self.assertRaises(GameError):
            next_round(game)

    def test_public_state_never_exposes_hidden_cards(self):
        game = new_game(rng=random.Random(42))
        view = public_state(game)
        self.assertNotIn("deck", view)
        self.assertNotIn("hands", view)
        self.assertEqual(view["deck_count"], 40)
        self.assertEqual(view["bot_hand_count"], 4)
        self.assertIsNone(public_state(None))
        view["scores"]["player"] = 100
        self.assertEqual(game["scores"]["player"], 0)

    def test_bot_decision_has_only_hand_and_table_inputs(self):
        first = new_game(rng=random.Random(42))
        altered = deepcopy(first)
        altered["hands"]["player"] = ["C2", "D10"]
        altered["deck"].reverse()
        expected = choose_bot_move(first["hands"]["bot"], first["table"])
        self.assertEqual(expected, choose_bot_move(altered["hands"]["bot"], altered["table"]))

    def test_thirty_complete_matches_preserve_cards_and_rules(self):
        for seed in range(30):
            rng = random.Random(seed)
            game = new_game(rng=rng)
            rounds_checked = 0
            while game["status"] != "match_over":
                moves, deal_events = 0, 1
                while game["status"] == "playing":
                    locations = game["deck"] + game["table"]
                    for actor in ("player", "bot"):
                        locations += game["hands"][actor] + game["captured"][actor]
                    self.assertEqual(len(locations), 52)
                    self.assertEqual(set(locations), set(CARDS))
                    actor = game["turn"]
                    card, take = choose_bot_move(game["hands"][actor], game["table"])
                    previous_deck = len(game["deck"])
                    play_card(game, actor, card, take)
                    moves += 1
                    for event in game["events"]:
                        if event["type"] == "deal":
                            deal_events += 1
                            self.assertEqual(event["table_count"], 0)
                            self.assertEqual(previous_deck - len(game["deck"]), 8)
                            self.assertEqual(len(game["hands"]["player"]), 4)
                            self.assertEqual(len(game["hands"]["bot"]), 4)
                rounds_checked += 1
                self.assertEqual(moves, 48)
                self.assertEqual(deal_events, 6)
                self.assertEqual(sum(map(len, game["captured"].values())), 52)
                self.assertEqual(sum(game["round_result"]["points"].values()), 5)
                self.assertEqual(len(game["deck"]), 0)
                self.assertEqual(game["table"], [])
                self.assertLessEqual(len(game["log"]), 12)
                if game["status"] == "round_over":
                    next_round(game, rng)
                self.assertLess(rounds_checked, 100)
            self.assertGreaterEqual(max(game["scores"].values()), 21)
            self.assertNotEqual(game["scores"]["player"], game["scores"]["bot"])


if __name__ == "__main__":
    unittest.main()
