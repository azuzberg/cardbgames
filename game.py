"""Rules for the 52-card capture game; internal hands stay on the server."""

from __future__ import annotations

import random
import uuid
from copy import deepcopy
from typing import Any

PLAYERS = ("player", "bot")
SUITS = {"C": ("♣", False), "D": ("♦", True), "H": ("♥", True), "S": ("♠", False)}
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
LABELS = {"A": "Т", "J": "В", "Q": "Д", "K": "К"}
CARDS = {
    f"{suit}{rank}": {
        "id": f"{suit}{rank}", "rank": rank, "suit": suit,
        "value": 1 if rank == "A" else int(rank) if rank.isdigit() else 0,
        "label": LABELS.get(rank, rank), "suit_symbol": symbol, "red": red,
    }
    for suit, (symbol, red) in SUITS.items()
    for rank in RANKS
}


class GameError(Exception):
    def __init__(self, message: str, code: str = "invalid_move", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def opponent(actor: str) -> str:
    return "bot" if actor == "player" else "player"


def card_view(card_id: str) -> dict[str, Any]:
    return dict(CARDS[card_id])


def _name(actor: str) -> str:
    return "Вы" if actor == "player" else "Бот"


def _card_name(card_id: str) -> str:
    card = CARDS[card_id]
    return card["label"] + card["suit_symbol"]


def _log(game: dict, message: str) -> None:
    game["log"] = (game["log"] + [message])[-12:]


def _capture_weight(card_ids: tuple[str, ...] | list[str]) -> int:
    # Only the cards in the proposed capture enter this visible-information heuristic.
    return sum(20 + (8 if card[0] == "C" else 0) + (60 if card in ("C2", "D10") else 0)
               for card in card_ids)


def best_capture(card_id: str, table: list[str]) -> list[str] | None:
    """Find one valuable legal subset, in O(table size * 10) space/time.

    Faces match exactly one identical rank. Positive numeric values prevent empty
    or zero-valued subsets from being used as captures.
    """
    card = CARDS[card_id]
    target = card["value"]
    if target == 0:
        options = [(item,) for item in table if CARDS[item]["rank"] == card["rank"]]
        return list(max(options, key=_capture_weight)) if options else None
    subsets: dict[int, tuple[str, ...]] = {0: ()}
    for item in table:
        value = CARDS[item]["value"]
        if value <= 0 or value > target:
            continue
        # Snapshot is essential: each physical card can be used only once.
        for subtotal, selected in tuple(subsets.items()):
            total = subtotal + value
            if total > target:
                continue
            candidate = selected + (item,)
            if total not in subsets or _capture_weight(candidate) > _capture_weight(subsets[total]):
                subsets[total] = candidate
    return list(subsets[target]) if target in subsets else None


def _deal(game: dict, include_table: bool = False) -> None:
    first = opponent(game["dealer"])
    counts = {"player": 0, "bot": 0}
    for _ in range(4):
        for actor in (first, game["dealer"]):
            if not game["deck"]:
                raise RuntimeError("A complete four-card deal was expected")
            game["hands"][actor].append(game["deck"].pop())
            counts[actor] += 1
    if include_table:
        game["table"] = [game["deck"].pop() for _ in range(4)]
    game["events"].append({"type": "deal", "player_count": counts["player"],
                           "bot_count": counts["bot"], "table_count": 4 if include_table else 0})


def _start_round(game: dict, rng: random.Random | None = None) -> None:
    deck = list(CARDS)
    (rng or random.SystemRandom()).shuffle(deck)
    game.update(deck=deck, hands={"player": [], "bot": []}, table=[],
                captured={"player": [], "bot": []}, last_capture=None,
                status="playing", turn=opponent(game["dealer"]),
                round_result=None, winner=None)
    _deal(game, include_table=True)
    _log(game, f"Кон {game['round']}. Сдатчик: {'вы' if game['dealer'] == 'player' else 'бот'}. Раздано по 4 карты.")


def new_game(*, rng: random.Random | None = None, target: int = 21) -> dict:
    game = {"id": uuid.uuid4().hex, "revision": 1, "target": target, "round": 1,
            "dealer": "bot", "scores": {"player": 0, "bot": 0}, "log": [], "events": []}
    _start_round(game, rng)
    return game


def score_captured(captured: dict[str, list[str]]) -> dict:
    """Calculate a finished round; also kept independently testable."""
    counts = {actor: len(captured[actor]) for actor in PLAYERS}
    clubs = {actor: sum(card[0] == "C" for card in captured[actor]) for actor in PLAYERS}
    majority = {"player": 0, "bot": 0}
    if counts["player"] == counts["bot"]:
        majority = {"player": 1, "bot": 1}
    else:
        majority[max(PLAYERS, key=counts.get)] = 2
    club_majority = {"player": 0, "bot": 0}
    if clubs["player"] != clubs["bot"]:
        club_majority[max(PLAYERS, key=clubs.get)] = 1
    rows = [
        {"label": "Большинство карт" if counts["player"] != counts["bot"] else "Поровну карт",
         **majority},
        {"label": "Большинство треф", **club_majority},
        {"label": "Двойка треф (2♣)", **{actor: int("C2" in captured[actor]) for actor in PLAYERS}},
        {"label": "Десятка бубен (10♦)", **{actor: int("D10" in captured[actor]) for actor in PLAYERS}},
    ]
    return {"rows": rows, "points": {actor: sum(row[actor] for row in rows) for actor in PLAYERS},
            "cards": counts, "clubs": clubs}


def _finish_round(game: dict) -> None:
    remaining_count = len(game["table"])
    remaining_to = (game["last_capture"] or game["dealer"]) if remaining_count else None
    if remaining_to:
        game["captured"][remaining_to].extend(game["table"])
        game["table"] = []
        _log(game, f"Остаток стола ({remaining_count} карт) получает {'игрок' if remaining_to == 'player' else 'бот'}.")
    result = score_captured(game["captured"])
    for actor in PLAYERS:
        game["scores"][actor] += result["points"][actor]
    result.update(total=dict(game["scores"]), remaining_to=remaining_to, remaining_count=remaining_count)
    game["round_result"] = result
    game["turn"] = None
    game["status"] = "round_over"
    _log(game, f"Кон завершён: вы +{result['points']['player']}, бот +{result['points']['bot']}.")
    if max(game["scores"].values()) >= game["target"] and game["scores"]["player"] != game["scores"]["bot"]:
        game["status"] = "match_over"
        game["winner"] = max(PLAYERS, key=game["scores"].get)
        _log(game, "Матч завершён. Вы победили!" if game["winner"] == "player" else "Матч завершён. Победил бот.")
    elif max(game["scores"].values()) >= game["target"]:
        _log(game, "Равный счёт после достижения цели: играем ещё один кон.")
    game["events"].append({"type": "round_end"})


def play_card(game: dict, actor: str, card_id: Any, take_ids: Any) -> None:
    """Validate fully before mutating, then perform exactly one card play."""
    if actor not in PLAYERS or game["status"] != "playing":
        raise GameError("Этот кон уже завершён.", "round_finished", 409)
    if game["turn"] != actor:
        raise GameError("Сейчас ход другого игрока.", "wrong_turn", 409)
    if not isinstance(card_id, str) or card_id not in game["hands"][actor]:
        raise GameError("Выберите карту из своей руки.", "invalid_card")
    if not isinstance(take_ids, list) or len(take_ids) > 52 or any(not isinstance(item, str) for item in take_ids):
        raise GameError("Карты взятки должны быть списком идентификаторов.", "invalid_selection")
    if len(set(take_ids)) != len(take_ids) or any(item not in game["table"] for item in take_ids):
        raise GameError("Взятка содержит повторные карты или карты, которых нет на столе.", "invalid_selection")
    played = CARDS[card_id]
    if take_ids:
        if played["value"] == 0:
            valid = len(take_ids) == 1 and CARDS[take_ids[0]]["rank"] == played["rank"]
        else:
            valid = all(CARDS[item]["value"] > 0 for item in take_ids) and sum(CARDS[item]["value"] for item in take_ids) == played["value"]
        if not valid:
            raise GameError("Выбранные карты не подходят для этой взятки.", "invalid_capture")
    elif best_capture(card_id, game["table"]) is not None:
        raise GameError("Этой картой можно взять взятку. Выберите подходящие карты стола.", "capture_required")

    taken = [item for item in game["table"] if item in set(take_ids)]
    game["events"] = [{"type": "play", "actor": actor, "card": card_view(card_id),
                       "take": [card_view(item) for item in taken], "capture": bool(taken)}]
    game["hands"][actor].remove(card_id)
    if taken:
        game["table"] = [item for item in game["table"] if item not in set(take_ids)]
        game["captured"][actor].extend([card_id] + taken)
        game["last_capture"] = actor
        _log(game, f"{_name(actor)}: {_card_name(card_id)} — взятка, {len(taken) + 1} карт.")
    else:
        game["table"].append(card_id)
        _log(game, f"{_name(actor)}: {_card_name(card_id)} на стол.")
    game["turn"] = opponent(actor)
    if not any(game["hands"].values()):
        if game["deck"]:
            _deal(game)
            _log(game, "Карты на руках закончились. Новая сдача по 4 карты.")
        else:
            _finish_round(game)
    game["revision"] += 1


def choose_bot_move(hand: list[str], table: list[str]) -> tuple[str, list[str]]:
    """The strategy has no access to the deck, human hand, or future cards."""
    captures = []
    for card_id in hand:
        take = best_capture(card_id, table)
        if take is not None:
            captures.append((_capture_weight([card_id] + take), card_id, take))
    if captures:
        _, card_id, take = max(captures, key=lambda item: item[0])
        return card_id, take
    # Preserve point-bearing cards, and discard smaller numeric/face cards first.
    card_id = min(hand, key=lambda item: (_capture_weight([item]), CARDS[item]["value"]))
    return card_id, []


def bot_turn(game: dict) -> None:
    if game["status"] != "playing" or game["turn"] != "bot":
        raise GameError("Сейчас не ход бота.", "wrong_turn", 409)
    card_id, take = choose_bot_move(game["hands"]["bot"], game["table"])
    play_card(game, "bot", card_id, take)


def next_round(game: dict, rng: random.Random | None = None) -> None:
    if game["status"] != "round_over":
        raise GameError("Начать новый кон можно только после завершения текущего.", "wrong_phase", 409)
    game["round"] += 1
    game["dealer"] = opponent(game["dealer"])
    game["events"] = []
    _start_round(game, rng)
    game["revision"] += 1


def public_state(game: dict | None) -> dict | None:
    if game is None:
        return None
    result = {key: deepcopy(game[key]) for key in ("id", "revision", "status", "target", "round", "dealer",
              "turn", "scores", "last_capture", "round_result", "winner", "log", "events")}
    result.update(hand=[card_view(item) for item in game["hands"]["player"]],
                  bot_hand_count=len(game["hands"]["bot"]),
                  table=[card_view(item) for item in game["table"]], deck_count=len(game["deck"]),
                  captured={actor: {"count": len(game["captured"][actor]),
                                    "clubs": sum(item[0] == "C" for item in game["captured"][actor])}
                            for actor in PLAYERS}, hints={})
    if game["status"] == "playing":
        for item in game["hands"]["player"]:
            take = best_capture(item, game["table"])
            if take is not None:
                result["hints"][item] = take
    return result
