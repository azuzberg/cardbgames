"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let state = {
    game: null,
    stats: { played: 0, wins: 0, losses: 0 },
    history: [],
  };
  let selectedCard = null;
  let selectedTable = new Set();
  let busy = false;
  let botTimer = null;
  let toastTimer = null;
  let retryAction = null;

  const wait = (milliseconds) =>
    new Promise((resolve) => setTimeout(resolve, milliseconds));
  const cardName = (card) => `${card.label}${card.suit_symbol}`;
  const cardById = (id) => state.game?.hand.find((card) => card.id === id);
  const playerCanAct = () =>
    !busy && state.game?.status === "playing" && state.game.turn === "player";

  function announce(message) {
    $("announcements").textContent = message;
  }

  function showToast(message, retry = null) {
    clearTimeout(toastTimer);
    $("toast-message").textContent = message;
    $("toast-retry").hidden = !retry;
    retryAction = retry;
    $("toast").hidden = false;
    if (!retry)
      toastTimer = setTimeout(() => {
        $("toast").hidden = true;
      }, 5500);
    announce(message);
  }

  async function api(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        credentials: "same-origin",
        headers:
          body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(result.error || "Не удалось выполнить ход.");
        error.code = result.code;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) {
        throw new Error(
          "Нет связи с сервером. Проверьте, запущена ли игра, и повторите запрос.",
        );
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function setView(view) {
    document.body.dataset.view = view;
    $("loading-screen").hidden = true;
    $("lobby-view").hidden = view !== "lobby";
    $("game-view").hidden = view !== "game";
    $("header-game-info").hidden = view !== "game";
    $("lobby-button").hidden = view !== "game";
    if (view === "game") scheduleBot();
    else clearTimeout(botTimer);
  }

  function showDialog(id) {
    const dialog = $(id);
    if (!dialog.open) dialog.showModal();
  }

  function clearSelection() {
    selectedCard = null;
    selectedTable.clear();
  }

  function cardElement(card, place, interactive = true) {
    const element = document.createElement(interactive ? "button" : "div");
    element.className = `playing-card ${place === "table" ? "table-card" : "hand-card"}${card.red ? " red-card" : ""}`;
    element.dataset.cardId = card.id;
    if (interactive) {
      element.type = "button";
      element.setAttribute(
        "aria-label",
        `${card.label} ${{ C: "треф", D: "бубен", H: "червей", S: "пик" }[card.suit]}${place === "table" ? ", на столе" : ", на руке"}`,
      );
      element.setAttribute("aria-pressed", "false");
    }
    for (const bottom of [false, true]) {
      const corner = document.createElement("span");
      corner.className = "card-corner" + (bottom ? " bottom-corner" : "");
      const rank = document.createElement("span");
      rank.className = "card-rank";
      rank.textContent = card.label;
      const suit = document.createElement("span");
      suit.className = "card-suit";
      suit.textContent = card.suit_symbol;
      corner.append(rank, suit);
      element.append(corner);
    }
    if (card.value === 1) {
      const center = document.createElement("span");
      center.className = "card-pips ace" + (card.suit === "S" ? " spade" : "");
      center.textContent = card.suit_symbol;
      element.append(center);
    } else if (card.value > 1) {
      const pips = document.createElement("span");
      pips.className = "card-pips";
      const positions = {
        2: [
          [50, 5],
          [50, 95],
        ],
        3: [
          [50, 5],
          [50, 50],
          [50, 95],
        ],
        4: [
          [15, 5],
          [85, 5],
          [15, 95],
          [85, 95],
        ],
        5: [
          [15, 5],
          [85, 5],
          [50, 50],
          [15, 95],
          [85, 95],
        ],
        6: [
          [15, 5],
          [85, 5],
          [15, 50],
          [85, 50],
          [15, 95],
          [85, 95],
        ],
        7: [
          [15, 5],
          [85, 5],
          [50, 27],
          [15, 50],
          [85, 50],
          [15, 95],
          [85, 95],
        ],
        8: [
          [15, 5],
          [85, 5],
          [50, 27],
          [15, 50],
          [85, 50],
          [50, 73],
          [15, 95],
          [85, 95],
        ],
        9: [
          [15, 5],
          [85, 5],
          [15, 35],
          [85, 35],
          [50, 50],
          [15, 65],
          [85, 65],
          [15, 95],
          [85, 95],
        ],
        10: [
          [15, 5],
          [85, 5],
          [50, 20],
          [15, 35],
          [85, 35],
          [15, 65],
          [85, 65],
          [50, 80],
          [15, 95],
          [85, 95],
        ],
      };
      for (const [x, y] of positions[card.value]) {
        const pip = document.createElement("span");
        pip.className = "pip" + (y > 50 ? " inverted" : "");
        pip.textContent = card.suit_symbol;
        pip.style.left = `${x}%`;
        pip.style.top = `${y}%`;
        pips.append(pip);
      }
      element.append(pips);
    } else {
      const face = document.createElement("span");
      face.className = "face-art";
      const crown = document.createElement("span");
      crown.className = "face-crown";
      crown.textContent = card.rank === "J" ? "✦" : "♛";
      const monogram = document.createElement("span");
      monogram.className = "face-monogram";
      monogram.textContent = card.label;
      const suit = document.createElement("span");
      suit.className = "face-suit";
      suit.textContent = card.suit_symbol;
      face.append(crown, monogram, suit);
      element.append(face);
    }
    if (card.id === "C2" || card.id === "D10") {
      const bonus = document.createElement("span");
      bonus.className = "card-bonus";
      bonus.textContent = "+1 очко";
      element.append(bonus);
    }
    if (interactive)
      element.addEventListener("click", () => selectCard(card.id, place));
    return element;
  }

  function backElement() {
    const back = document.createElement("div");
    back.className = "card-back";
    const emblem = document.createElement("span");
    emblem.className = "back-emblem";
    emblem.textContent = "✦";
    back.append(emblem);
    return back;
  }

  function selectCard(id, place) {
    if (!playerCanAct()) return;
    if (place === "hand") {
      selectedCard = selectedCard === id ? null : id;
      selectedTable.clear();
    } else {
      if (!selectedCard) {
        showToast("Сначала выберите карту из своей руки.");
        return;
      }
      if (selectedTable.has(id)) selectedTable.delete(id);
      else selectedTable.add(id);
    }
    renderSelection();
  }

  function moveValidity() {
    const card = cardById(selectedCard);
    if (!card)
      return {
        valid: false,
        title: "Ваш ход",
        detail: "Выберите карту на руке",
        button: "Выберите карту",
      };
    const taken = state.game.table.filter((item) => selectedTable.has(item.id));
    if (!taken.length) {
      const mandatory = Boolean(state.game.hints[card.id]);
      return {
        valid: !mandatory,
        title: `Выбрана ${cardName(card)}`,
        detail: mandatory
          ? "Взятка обязательна: выберите карты стола"
          : "Взятки нет — выложите карту на стол",
        button: mandatory ? "Выберите взятку" : "Выложить карту",
      };
    }
    const valid =
      card.value === 0
        ? taken.length === 1 && taken[0].rank === card.rank
        : taken.every((item) => item.value > 0) &&
          taken.reduce((sum, item) => sum + item.value, 0) === card.value;
    const description =
      card.value === 0
        ? "Картинка берёт одну карту такого же ранга"
        : `${taken.map(cardName).join(" + ")} = ${taken.reduce((sum, item) => sum + item.value, 0)} · нужно ${card.value}`;
    return {
      valid,
      title: valid ? "Комбинация собрана" : "Проверьте комбинацию",
      detail: description,
      button: valid ? `Забрать ${taken.length + 1} карт` : "Не подходит",
    };
  }

  function renderSelection() {
    const game = state.game;
    if (!game) return;
    const canAct = playerCanAct();
    for (const card of $("player-hand").children) {
      const selected = card.dataset.cardId === selectedCard;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
      card.disabled = !canAct;
    }
    for (const card of $("table-cards").children) {
      const selected = selectedTable.has(card.dataset.cardId);
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
      card.disabled = !canAct;
    }
    $("game-view").setAttribute("aria-busy", String(busy));
    $("hint-button").disabled = !canAct;
    $("play-button").hidden = game.status !== "playing";
    $("hint-button").hidden = game.status !== "playing";
    $("show-result-button").hidden = game.status === "playing";
    $("show-result-button").disabled = busy;
    $("next-round-button").disabled = busy;
    $("new-match-button").disabled = busy;
    $("start-game").disabled = busy;
    if (game.status !== "playing") {
      $("move-title").textContent =
        game.status === "match_over" ? "Партия завершена" : "Кон завершён";
      $("move-detail").textContent = "Все очки подсчитаны — откройте итоги";
      return;
    }
    if (game.turn === "bot" || busy) {
      $("move-title").textContent = busy
        ? "Ход выполняется…"
        : "Бот обдумывает ход";
      $("move-detail").textContent =
        "Карты соперника скрыты. Следующий ход — ваш.";
      $("play-button").disabled = true;
      $("play-button").textContent = "Подождите…";
      return;
    }
    const move = moveValidity();
    $("move-title").textContent = move.title;
    $("move-detail").textContent = move.detail;
    $("play-button").textContent = `${move.button} →`;
    $("play-button").disabled = !move.valid;
  }

  function renderLobby() {
    $("resume-game").hidden = !state.game;
    $("resume-game").textContent =
      state.game?.status === "match_over"
        ? "Посмотреть итог партии →"
        : "Продолжить текущую партию →";
    $("stats-summary").replaceChildren();
    for (const [label, number] of [
      ["Партий", state.stats.played],
      ["Побед", state.stats.wins],
      ["Поражений", state.stats.losses],
    ]) {
      const item = document.createElement("span");
      item.textContent = `${label}: `;
      const value = document.createElement("b");
      value.textContent = number;
      item.append(value);
      $("stats-summary").append(item);
    }
    $("history-list").replaceChildren();
    if (!state.history.length) {
      const empty = document.createElement("p");
      empty.className = "empty-history";
      empty.textContent = "Первая история начинается с первой партии.";
      $("history-list").append(empty);
    }
    for (const match of state.history) {
      const row = document.createElement("div");
      row.className = "history-row";
      const outcome = document.createElement("span");
      outcome.className =
        "history-outcome" + (match.winner === "bot" ? " lost" : "");
      outcome.textContent = match.winner === "player" ? "Победа" : "Поражение";
      const score = document.createElement("span");
      score.className = "history-score";
      score.textContent = `${match.player_score} : ${match.bot_score}`;
      const rounds = document.createElement("span");
      rounds.className = "history-meta";
      rounds.textContent = `Конов: ${match.rounds}`;
      const date = document.createElement("time");
      date.className = "history-time";
      date.dateTime = match.finished_at;
      date.textContent = new Date(match.finished_at).toLocaleString("ru-RU", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
      row.append(outcome, score, rounds, date);
      $("history-list").append(row);
    }
  }

  function renderGame() {
    const game = state.game;
    if (!game) return;
    $("player-score").textContent = game.scores.player;
    $("bot-score").textContent = game.scores.bot;
    $("round-chip").textContent = `Кон ${game.round}`;
    $("deck-count").textContent = game.deck_count;
    $("deck-stack").classList.toggle("empty", game.deck_count === 0);
    $("deck-stack").setAttribute(
      "aria-label",
      `В колоде ${game.deck_count} карт`,
    );
    $("player-dealer").hidden = game.dealer !== "player";
    $("bot-dealer").hidden = game.dealer !== "bot";
    $("player-turn-dot").hidden = game.turn !== "player";
    $("bot-turn-dot").hidden = game.turn !== "bot";
    $("player-status").textContent =
      game.status !== "playing"
        ? "Кон завершён"
        : game.turn === "player"
          ? "Ваш ход"
          : "Ожидаем соперника";
    $("bot-status").textContent =
      game.status !== "playing"
        ? "Кон завершён"
        : game.turn === "bot"
          ? "Думает…"
          : "Ожидает ваш ход";
    $("game-board").classList.toggle(
      "thinking",
      game.turn === "bot" && game.status === "playing",
    );
    $("board-round-note").textContent =
      `КОН ${game.round} · ДО ${game.target} ОЧКОВ`;
    for (const actor of ["player", "bot"]) {
      $(actor + "-captured-count").textContent =
        `${game.captured[actor].count} карт`;
      $(actor + "-captured-clubs").textContent =
        `♣ ${game.captured[actor].clubs}`;
      $(actor + "-pile").classList.toggle(
        "empty",
        game.captured[actor].count === 0,
      );
    }
    $("player-hand").replaceChildren(
      ...game.hand.map((card) => cardElement(card, "hand")),
    );
    $("table-cards").replaceChildren(
      ...game.table.map((card) => cardElement(card, "table")),
    );
    $("bot-hand").replaceChildren(
      ...Array.from({ length: game.bot_hand_count }, backElement),
    );
    $("empty-table").hidden = game.table.length !== 0;
    $("table-caption").textContent =
      game.status !== "playing"
        ? "Все карты разобраны. Пора считать очки."
        : "Выберите карту на руке, затем карты на столе";
    $("log-list").replaceChildren(
      ...game.log.map((message) => {
        const item = document.createElement("li");
        item.textContent = message;
        return item;
      }),
    );
    $("last-log").textContent = game.log.at(-1) || "";
    renderSelection();
  }

  function showResult() {
    const game = state.game;
    if (!game?.round_result) return;
    const result = game.round_result;
    const finished = game.status === "match_over";
    const won = finished && game.winner === "player";
    $("result-dialog").classList.toggle("win", won);
    $("result-dialog").classList.toggle("loss", finished && !won);
    $("result-symbol").textContent = finished ? (won ? "♛" : "♠") : "✦";
    $("result-eyebrow").textContent = finished
      ? "Партия завершена"
      : `Кон ${game.round} завершён`;
    $("result-title").textContent = finished
      ? won
        ? "Вы победили!"
        : "Бот победил"
      : "Считаем очки";
    $("result-description").textContent = finished
      ? won
        ? "Хорошие комбинации и точные решения. Эта партия ваша."
        : "В этот раз соперник набрал больше очков. Новая партия — новый шанс."
      : game.scores.player === game.scores.bot &&
          game.scores.player >= game.target
        ? "Равный счёт после 21 — играем ещё один кон."
        : "Очки добавлены к общему счёту. В следующем коне меняется сдатчик.";
    for (const actor of ["player", "bot"]) {
      $("result-" + actor + "-total").textContent = result.total[actor];
      $("result-" + actor + "-gain").textContent =
        `+${result.points[actor]} за кон`;
    }
    $("result-rows").replaceChildren(
      ...result.rows.map((entry, index) => {
        const row = document.createElement("tr");
        let label = entry.label;
        if (index === 0)
          label += ` (${result.cards.player} : ${result.cards.bot})`;
        if (index === 1)
          label += ` (${result.clubs.player} : ${result.clubs.bot})`;
        for (const value of [label, entry.player || "—", entry.bot || "—"]) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        }
        return row;
      }),
    );
    $("result-remainder").textContent = result.remaining_count
      ? `Остаток стола: ${result.remaining_count} карт ${result.remaining_to === "player" ? "получили вы" : "получил бот"}.`
      : "На столе не осталось карт. Все взятки учтены.";
    $("next-round-button").hidden = finished;
    $("new-match-button").hidden = !finished;
    showDialog("result-dialog");
    announce(
      finished
        ? `${won ? "Вы победили" : "Вы проиграли"}. Счёт ${game.scores.player} — ${game.scores.bot}.`
        : `Кон завершён. Вы получили ${result.points.player}, бот ${result.points.bot} очков.`,
    );
  }

  async function fly(node, from, to, duration, rotation = 0, pause = 0) {
    if (reducedMotion.matches || !from.width || !to.width) return;
    const ghost = node.cloneNode(true);
    ghost.removeAttribute("id");
    ghost.removeAttribute("aria-pressed");
    ghost.classList.remove("selected");
    ghost.classList.add("flying-card");
    Object.assign(ghost.style, {
      left: `${from.x}px`,
      top: `${from.y}px`,
      width: `${from.width}px`,
      height: `${from.height}px`,
      opacity: "1",
      visibility: "visible",
    });
    $("motion-layer").append(ghost);
    try {
      await ghost.animate(
        [
          { transform: "translate(0, 0) rotate(0deg) scale(1)", opacity: 1 },
          {
            transform: `translate(${to.x - from.x}px, ${to.y - from.y}px) rotate(${rotation}deg) scale(${to.width / from.width}, ${to.height / from.height})`,
            opacity: 1,
          },
        ],
        {
          duration,
          delay: pause,
          easing: "cubic-bezier(.22,.75,.24,1)",
          fill: "both",
        },
      ).finished;
    } finally {
      ghost.remove();
    }
  }

  function tableDestination(card) {
    const area = $("table-cards").getBoundingClientRect();
    const existing =
      $("table-cards").firstElementChild?.getBoundingClientRect();
    const hand = $("player-hand").firstElementChild?.getBoundingClientRect();
    const width = existing?.width || hand?.width || 92;
    const height = existing?.height || hand?.height || 132;
    return {
      x: area.x + (area.width - width) / 2,
      y: area.y + (area.height - height) / 2,
      width,
      height,
    };
  }

  async function animatePlay(events) {
    if (reducedMotion.matches || document.body.dataset.view !== "game") return;
    const event = events.find((item) => item.type === "play");
    if (!event) return;
    const source =
      event.actor === "player"
        ? $("player-hand").querySelector(`[data-card-id="${event.card.id}"]`)
        : $("bot-hand").lastElementChild;
    if (!source) return;
    const from = source.getBoundingClientRect();
    const destination = tableDestination(event.card);
    const face = cardElement(event.card, "table", false);
    source.style.visibility = "hidden";
    await fly(face, from, destination, 330, event.actor === "player" ? -6 : 6);
    if (event.capture) {
      const pile = $(event.actor + "-pile").getBoundingClientRect();
      const motions = [fly(face, destination, pile, 320)];
      for (const [index, taken] of event.take.entries()) {
        const original = $("table-cards").querySelector(
          `[data-card-id="${taken.id}"]`,
        );
        if (!original) continue;
        original.style.visibility = "hidden";
        motions.push(
          fly(
            original,
            original.getBoundingClientRect(),
            pile,
            320,
            0,
            index * 25,
          ),
        );
      }
      await Promise.all(motions);
    }
  }

  async function animateDeal(events) {
    if (
      reducedMotion.matches ||
      document.body.dataset.view !== "game" ||
      !events.some((event) => event.type === "deal")
    )
      return;
    const from = $("deck-stack").getBoundingClientRect();
    const cards = [...$("player-hand").children, ...$("bot-hand").children];
    if (events.some((event) => event.type === "deal" && event.table_count))
      cards.push(...$("table-cards").children);
    const motions = cards.map(async (card, index) => {
      const to = card.getBoundingClientRect();
      card.style.visibility = "hidden";
      try {
        await fly(card, from, to, 360, 0, index * 55);
      } finally {
        card.style.visibility = "";
      }
    });
    await Promise.all(motions);
  }

  function scheduleBot() {
    clearTimeout(botTimer);
    botTimer = null;
    if (
      busy ||
      document.body.dataset.view !== "game" ||
      state.game?.status !== "playing" ||
      state.game.turn !== "bot"
    )
      return;
    botTimer = setTimeout(
      () => {
        botTimer = null;
        if (
          !busy &&
          document.body.dataset.view === "game" &&
          state.game?.turn === "bot"
        ) {
          performAction("/api/bot", { revision: state.game.revision });
        }
      },
      reducedMotion.matches ? 60 : 650,
    );
  }

  async function loadState(preserveView = false) {
    if (busy) return;
    const previousView = document.body.dataset.view;
    clearTimeout(botTimer);
    busy = true;
    $("start-game").disabled = true;
    renderSelection();
    try {
      state = await api("/api/state");
      clearSelection();
      renderLobby();
      renderGame();
      setView(
        preserveView && previousView === "lobby"
          ? "lobby"
          : state.game
            ? "game"
            : "lobby",
      );
      $("toast").hidden = true;
      busy = false;
      renderSelection();
      if (
        document.body.dataset.view === "game" &&
        state.game?.status !== "playing"
      )
        showResult();
      scheduleBot();
    } catch (error) {
      if (previousView === "loading") setView("lobby");
      showToast(error.message, () => loadState(preserveView));
    } finally {
      busy = false;
      $("start-game").disabled = false;
      renderSelection();
    }
  }

  async function performAction(path, payload, newGame = false) {
    if (busy) return;
    clearTimeout(botTimer);
    busy = true;
    $("start-game").disabled = true;
    renderSelection();
    let succeeded = false;
    let recovered = false;
    try {
      const result = await api(path, payload);
      // Animations decorate an already validated server move; they cannot change rules.
      try {
        await animatePlay(result.game.events);
      } catch (_) {
        /* Render authoritative state below. */
      }
      state = result;
      clearSelection();
      renderLobby();
      renderGame();
      if (newGame) setView("game");
      try {
        await animateDeal(state.game.events);
      } catch (_) {
        /* Reduced/unsupported animation is harmless. */
      }
      $("toast").hidden = true;
      succeeded = true;
    } catch (error) {
      // Read, rather than repeat, a move whose network response might have been lost.
      try {
        state = await api("/api/state");
        clearSelection();
        renderLobby();
        renderGame();
        recovered = true;
      } catch (_) {
        /* Preserve last visible state until connection returns. */
      }
      showToast(error.message, () => loadState(true));
    } finally {
      busy = false;
      $("start-game").disabled = false;
      renderSelection();
      if (
        (succeeded || recovered) &&
        document.body.dataset.view === "game" &&
        state.game?.status !== "playing"
      )
        showResult();
      if (succeeded || recovered) scheduleBot();
    }
  }

  function startNewGame() {
    if (busy) return;
    if (state.game && state.game.status !== "match_over")
      showDialog("confirm-dialog");
    else performAction("/api/new", {}, true);
  }

  function hint() {
    if (!playerCanAct()) return;
    const game = state.game;
    let id = selectedCard;
    if (!id || !game.hints[id]) {
      id =
        game.hand.find((card) => game.hints[card.id])?.id ||
        selectedCard ||
        game.hand[0]?.id;
    }
    if (!id) return;
    selectedCard = id;
    selectedTable = new Set(game.hints[id] || []);
    renderSelection();
    announce(
      game.hints[id]
        ? "Подходящая комбинация выделена. Подтвердите взятку."
        : "Этой картой нечего взять. Её можно выложить на стол.",
    );
  }

  function goToLobby() {
    $("result-dialog").close();
    setView("lobby");
    renderLobby();
  }

  $("start-game").addEventListener("click", startNewGame);
  $("resume-game").addEventListener("click", () => {
    if (!state.game) return;
    setView("game");
    if (state.game.status !== "playing") showResult();
    else if (!busy) loadState();
  });
  $("play-button").addEventListener("click", () => {
    if (!playerCanAct() || !moveValidity().valid) return;
    performAction("/api/play", {
      card_id: selectedCard,
      take_ids: [...selectedTable],
      revision: state.game.revision,
    });
  });
  $("hint-button").addEventListener("click", hint);
  $("next-round-button").addEventListener("click", () => {
    if (busy || state.game?.status !== "round_over") return;
    $("result-dialog").close();
    performAction("/api/next-round", { revision: state.game.revision });
  });
  $("new-match-button").addEventListener("click", () => {
    if (busy) return;
    $("result-dialog").close();
    performAction("/api/new", {}, true);
  });
  $("show-result-button").addEventListener("click", showResult);
  $("brand-home").addEventListener("click", goToLobby);
  $("lobby-button").addEventListener("click", goToLobby);
  $("result-lobby-button").addEventListener("click", goToLobby);
  $("cancel-new-button").addEventListener("click", () =>
    $("confirm-dialog").close(),
  );
  $("confirm-new-button").addEventListener("click", () => {
    $("confirm-dialog").close();
    performAction("/api/new", {}, true);
  });
  document
    .querySelectorAll(".rules-trigger")
    .forEach((button) =>
      button.addEventListener("click", () => showDialog("rules-dialog")),
    );
  document
    .querySelectorAll("[data-close]")
    .forEach((button) =>
      button.addEventListener("click", () => $(button.dataset.close).close()),
    );
  $("toast-close").addEventListener("click", () => {
    $("toast").hidden = true;
  });
  $("toast-retry").addEventListener("click", () => {
    if (retryAction) retryAction();
  });
  document.addEventListener("keydown", (event) => {
    if (
      document.querySelector("dialog[open]") ||
      document.body.dataset.view !== "game"
    )
      return;
    if (event.key === "Escape") {
      clearSelection();
      renderSelection();
    }
    if (
      (event.key === "h" || event.key === "р") &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    )
      hint();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !busy && state.game) loadState(true);
  });
  loadState();
})();
