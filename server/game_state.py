from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from enum import Enum


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_DATA_PATH = os.path.join(PROJECT_ROOT, "assets", "data", "characters.json")


@dataclass(frozen=True)
class PlayerInfo:
    player_id: str
    name: str


@dataclass(frozen=True)
class CharacterInfo:
    character_id: str
    name: str
    image_path: str
    accepted_answers: tuple[str, ...]


@dataclass(frozen=True)
class CharacterCategory:
    category_id: str
    name: str
    characters: tuple[CharacterInfo, ...]


@dataclass(frozen=True)
class CharacterAssignment:
    player: PlayerInfo
    character: CharacterInfo


@dataclass(frozen=True)
class TurnInfo:
    player: PlayerInfo
    round_number: int
    phase: "TurnPhase"


@dataclass(frozen=True)
class GuessResult:
    guess_id: str
    guesser: PlayerInfo
    owner: PlayerInfo
    guess: str
    accepted: bool
    scores: dict[str, int]
    remaining_guesses: dict[str, int]
    next_turn: TurnInfo | None = None
    is_game_over: bool = False
    game_over_reason: str | None = None


class TurnPhase(Enum):
    PRE_HINT_GUESS = "pre_hint_guess"
    HINT = "hint"
    POST_HINT_GUESSES = "post_hint_guesses"


class GameState:
    """Estado em memoria da partida e dos personagens sorteados."""

    def __init__(self, data_path: str = CHARACTER_DATA_PATH) -> None:
        self._categories = load_character_catalog(data_path)
        self._players: dict[str, PlayerInfo] = {}
        self._game_subscribers: dict[str, queue.Queue] = {}
        self._chat_subscribers: dict[str, queue.Queue] = {}
        self._game_started = False
        self._current_category: CharacterCategory | None = None
        self._characters_by_player_id: dict[str, CharacterInfo] = {}
        self._turn_order: list[str] = []
        self._turn_index = 0
        self._round_number = 1
        self._phase = TurnPhase.PRE_HINT_GUESS
        self._waiting_guessers: set[str] = set()
        self._public_hints: list[tuple[str, str]] = []
        self._scores: dict[str, int] = {}
        self._discovered_players: set[str] = set()
        self._guessing_blocked_players: set[str] = set()
        self._max_guesses_per_player = 0
        self._remaining_guesses: dict[str, int] = {}
        self._lock = threading.Lock()

    def add_player(self, name: str) -> tuple[PlayerInfo, list[PlayerInfo], bool]:
        clean_name = name.strip() or "Jogador"

        with self._lock:
            for player in self._players.values():
                if player.name.lower() == clean_name.lower():
                    return player, list(self._players.values()), False

            player = PlayerInfo(player_id=str(uuid.uuid4()), name=clean_name)
            self._players[player.player_id] = player
            self._scores[player.player_id] = 0
            players = list(self._players.values())

        return player, players, True

    def get_player(self, player_id: str) -> PlayerInfo | None:
        with self._lock:
            return self._players.get(player_id)

    def get_players(self) -> list[PlayerInfo]:
        with self._lock:
            return list(self._players.values())

    def get_current_category(self) -> CharacterCategory | None:
        with self._lock:
            return self._current_category

    def get_max_guesses_per_player(self) -> int:
        with self._lock:
            return self._max_guesses_per_player

    def get_remaining_guesses(self) -> dict[str, int]:
        with self._lock:
            return dict(self._remaining_guesses)

    def get_scores(self) -> dict[str, int]:
        with self._lock:
            return dict(self._scores)

    def get_game_snapshot_for_player(
        self,
        player_id: str,
    ) -> tuple[
        bool,
        CharacterCategory | None,
        CharacterInfo | None,
        TurnInfo | None,
        list[PlayerInfo],
    ]:
        with self._lock:
            return (
                self._game_started,
                self._current_category,
                self._characters_by_player_id.get(player_id),
                self._current_turn_locked(),
                list(self._players.values()),
            )

    def start_game(
        self,
        max_guesses_per_player: int,
    ) -> tuple[
        bool,
        str,
        CharacterCategory | None,
        list[CharacterAssignment],
        TurnInfo | None,
    ]:
        with self._lock:
            if self._game_started:
                return (
                    False,
                    "A partida ja foi iniciada.",
                    self._current_category,
                    [],
                    self._current_turn_locked(),
                )

            if max_guesses_per_player <= 0:
                return (
                    False,
                    "O numero de palpites por jogador deve ser maior que zero.",
                    None,
                    [],
                    None,
                )

            player_count = len(self._players)
            if player_count < 2:
                return False, "Sao necessarios pelo menos 2 jogadores.", None, [], None

            possible_categories = [
                category
                for category in self._categories
                if len(category.characters) >= player_count
            ]
            if not possible_categories:
                return (
                    False,
                    "Nao ha categoria com personagens suficientes para todos os jogadores.",
                    None,
                    [],
                    None,
                )

            players = list(self._players.values())
            category = random.choice(possible_categories)
            characters = random.sample(list(category.characters), player_count)
            self._current_category = category
            self._characters_by_player_id = {
                player.player_id: character
                for player, character in zip(players, characters)
            }
            self._turn_order = [player.player_id for player in players]
            self._turn_index = 0
            self._round_number = 1
            self._phase = TurnPhase.HINT
            self._waiting_guessers.clear()
            self._public_hints.clear()
            self._discovered_players.clear()
            self._guessing_blocked_players.clear()
            self._max_guesses_per_player = max_guesses_per_player
            self._remaining_guesses = {
                player.player_id: max_guesses_per_player for player in players
            }
            self._scores = {player.player_id: 0 for player in players}
            self._game_started = True

            assignments = [
                CharacterAssignment(
                    player=player,
                    character=self._characters_by_player_id[player.player_id],
                )
                for player in players
            ]
            return (
                True,
                f"Partida iniciada com {max_guesses_per_player} palpites por jogador.",
                category,
                assignments,
                self._current_turn_locked(),
            )

    def register_public_hint(
        self,
        player_id: str,
        hint: str,
    ) -> tuple[
        bool,
        str,
        PlayerInfo | None,
        list[PlayerInfo],
        TurnInfo | None,
        bool,
        str | None,
    ]:
        clean_hint = hint.strip()
        if not clean_hint:
            return False, "A dica nao pode ser vazia.", None, [], None, False, None

        with self._lock:
            if not self._game_started:
                return (
                    False,
                    "A partida ainda nao foi iniciada.",
                    None,
                    [],
                    None,
                    False,
                    None,
                )

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None, [], None, False, None

            if self._phase != TurnPhase.HINT:
                return (
                    False,
                    "Ainda nao e a fase de enviar dica.",
                    None,
                    [],
                    current_turn,
                    False,
                    None,
                )

            if current_turn.player.player_id != player_id:
                return (
                    False,
                    f"A dica agora deve ser enviada por {current_turn.player.name}.",
                    None,
                    [],
                    current_turn,
                    False,
                    None,
                )

            self._public_hints.append((player_id, clean_hint))
            actor = current_turn.player
            if self._round_number == 1:
                self._advance_turn_locked()
                self._phase = (
                    TurnPhase.HINT
                    if self._round_number == 1
                    else TurnPhase.PRE_HINT_GUESS
                )
                self._normalize_pre_hint_phase_locked()
                is_game_over, reason = self._finalize_if_game_over_locked()
                next_turn = None if is_game_over else self._current_turn_locked()
                return (
                    True,
                    "Dica publica enviada.",
                    actor,
                    [],
                    next_turn,
                    is_game_over,
                    reason,
                )

            if actor.player_id in self._discovered_players:
                self._waiting_guessers.clear()
                self._advance_turn_locked()
                self._phase = TurnPhase.PRE_HINT_GUESS
                self._normalize_pre_hint_phase_locked()
                is_game_over, reason = self._finalize_if_game_over_locked()
                next_turn = None if is_game_over else self._current_turn_locked()
                return (
                    True,
                    "Dica publica enviada.",
                    actor,
                    [],
                    next_turn,
                    is_game_over,
                    reason,
                )

            waiting_player_ids = self._eligible_guessers_for_owner_locked(actor.player_id)
            if not waiting_player_ids:
                self._waiting_guessers.clear()
                self._advance_turn_locked()
                self._phase = TurnPhase.PRE_HINT_GUESS
                self._normalize_pre_hint_phase_locked()
                is_game_over, reason = self._finalize_if_game_over_locked()
                next_turn = None if is_game_over else self._current_turn_locked()
                return (
                    True,
                    "Dica publica enviada.",
                    actor,
                    [],
                    next_turn,
                    is_game_over,
                    reason,
                )

            waiting_players = [
                self._players[player_id]
                for player_id in waiting_player_ids
            ]
            self._waiting_guessers = set(waiting_player_ids)
            self._phase = TurnPhase.POST_HINT_GUESSES
            updated_turn = self._current_turn_locked()

        return True, "Dica publica enviada.", actor, waiting_players, updated_turn, False, None

    def submit_guess(
        self,
        guesser_player_id: str,
        owner_player_id: str,
        guess: str,
    ) -> tuple[bool, str, GuessResult | None]:
        clean_guess = guess.strip()
        if not clean_guess:
            return False, "O palpite nao pode ser vazio.", None

        with self._lock:
            if not self._game_started:
                return False, "A partida ainda nao foi iniciada.", None

            guesser = self._players.get(guesser_player_id)
            owner = self._players.get(owner_player_id)
            if guesser is None or owner is None:
                return False, "Jogador nao encontrado.", None

            if guesser.player_id == owner.player_id:
                return False, "Voce nao pode adivinhar seu proprio personagem.", None

            if guesser.player_id in self._guessing_blocked_players:
                return (
                    False,
                    "Voce ja acertou um personagem e nao pode mais palpitar.",
                    None,
                )

            if self._remaining_guesses.get(guesser.player_id, 0) <= 0:
                return False, "Voce esgotou seus palpites nesta partida.", None

            if owner.player_id in self._discovered_players:
                return False, f"O personagem de {owner.name} ja foi descoberto!", None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if guesser.player_id != current_turn.player.player_id:
                    return False, "Apenas o jogador do turno pode agir agora.", None

                self._consume_guess_attempt_locked(guesser.player_id)
                accepted = self._is_correct_guess_locked(owner.player_id, clean_guess)
                if accepted:
                    self._add_score_locked(guesser.player_id, 10)
                    self._discovered_players.add(owner.player_id)
                    self._mark_player_as_successful_guesser_locked(guesser.player_id)

                is_game_over, reason = self._finalize_if_game_over_locked()
                next_turn = None
                if is_game_over:
                    next_turn = None
                else:
                    self._phase = TurnPhase.HINT
                    next_turn = self._current_turn_locked()

                return True, "Palpite enviado. Agora envie sua dica publica.", GuessResult(
                    guess_id=str(uuid.uuid4()),
                    guesser=guesser,
                    owner=owner,
                    guess=clean_guess,
                    accepted=accepted,
                    scores=dict(self._scores),
                    remaining_guesses=dict(self._remaining_guesses),
                    next_turn=next_turn,
                    is_game_over=is_game_over,
                    game_over_reason=reason,
                )

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if owner.player_id != current_turn.player.player_id:
                    return (
                        False,
                        f"Agora os palpites devem ser sobre o personagem de {current_turn.player.name}.",
                        None,
                    )
                if guesser.player_id not in self._waiting_guessers:
                    return False, "Voce ja respondeu esta oportunidade.", None

                self._consume_guess_attempt_locked(guesser.player_id)
                accepted = self._is_correct_guess_locked(owner.player_id, clean_guess)
                if accepted:
                    self._add_score_locked(guesser.player_id, 10)
                    self._discovered_players.add(owner.player_id)
                    self._mark_player_as_successful_guesser_locked(guesser.player_id)
                    self._waiting_guessers.clear()

                self._waiting_guessers.discard(guesser.player_id)
                is_game_over, reason = self._finalize_if_game_over_locked()
                next_turn = None
                if is_game_over:
                    next_turn = None
                else:
                    next_turn = self._advance_if_everyone_answered_locked()

                return True, "Palpite enviado.", GuessResult(
                    guess_id=str(uuid.uuid4()),
                    guesser=guesser,
                    owner=owner,
                    guess=clean_guess,
                    accepted=accepted,
                    scores=dict(self._scores),
                    remaining_guesses=dict(self._remaining_guesses),
                    next_turn=next_turn,
                    is_game_over=is_game_over,
                    game_over_reason=reason,
                )

            return False, "Agora e a fase de dica publica.", None

    def validate_guess(
        self,
        owner_player_id: str,
        guesser_player_id: str,
        guess_id: str,
        accepted: bool,
    ) -> tuple[bool, str, None]:
        return (
            False,
            "A validacao e automatica pelo servidor em SubmitGuess.",
            None,
        )

    def pass_guess_opportunity(
        self,
        player_id: str,
    ) -> tuple[
        bool,
        str,
        PlayerInfo | None,
        TurnInfo | None,
        bool,
        str | None,
    ]:
        with self._lock:
            if not self._game_started:
                return (
                    False,
                    "A partida ainda nao foi iniciada.",
                    None,
                    None,
                    False,
                    None,
                )

            player = self._players.get(player_id)
            if player is None:
                return False, "Jogador nao encontrado.", None, None, False, None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None, None, False, None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if player.player_id != current_turn.player.player_id:
                    return (
                        False,
                        "Apenas o jogador do turno pode passar agora.",
                        None,
                        current_turn,
                        False,
                        None,
                    )
                if not self._can_player_attempt_guess_locked(player.player_id):
                    return (
                        False,
                        "Voce nao pode mais palpitar; sua fase de palpite e pulada automaticamente.",
                        None,
                        current_turn,
                        False,
                        None,
                    )

                self._consume_guess_attempt_locked(player.player_id)
                is_game_over, reason = self._finalize_if_game_over_locked()
                if is_game_over:
                    return True, "Oportunidade passada.", player, None, True, reason

                self._phase = TurnPhase.HINT
                return (
                    True,
                    "Oportunidade passada. Agora envie sua dica publica.",
                    player,
                    self._current_turn_locked(),
                    False,
                    None,
                )

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if player.player_id not in self._waiting_guessers:
                    return (
                        False,
                        "Voce ja respondeu esta oportunidade.",
                        None,
                        current_turn,
                        False,
                        None,
                    )

                self._consume_guess_attempt_locked(player.player_id)
                self._waiting_guessers.remove(player.player_id)

                is_game_over, reason = self._finalize_if_game_over_locked()
                if is_game_over:
                    return True, "Oportunidade passada.", player, None, True, reason

                next_turn = self._advance_if_everyone_answered_locked()
                return True, "Oportunidade passada.", player, next_turn, False, None

            return (
                False,
                "Nao ha oportunidade de palpite para passar agora.",
                None,
                current_turn,
                False,
                None,
            )

    def add_game_subscriber(self, player_id: str) -> queue.Queue:
        subscriber_queue: queue.Queue = queue.Queue()
        with self._lock:
            self._game_subscribers[player_id] = subscriber_queue
        return subscriber_queue

    def remove_game_subscriber(self, player_id: str) -> None:
        with self._lock:
            self._game_subscribers.pop(player_id, None)

    def add_chat_subscriber(self, player_id: str) -> queue.Queue:
        subscriber_queue: queue.Queue = queue.Queue()
        with self._lock:
            self._chat_subscribers[player_id] = subscriber_queue
        return subscriber_queue

    def remove_chat_subscriber(self, player_id: str) -> None:
        with self._lock:
            self._chat_subscribers.pop(player_id, None)

    def publish_game_event(self, event) -> None:
        with self._lock:
            subscribers = list(self._game_subscribers.values())

        for subscriber_queue in subscribers:
            subscriber_queue.put(event)

    def publish_game_event_to_player(self, player_id: str, event) -> None:
        with self._lock:
            subscriber_queue = self._game_subscribers.get(player_id)

        if subscriber_queue is not None:
            subscriber_queue.put(event)

    def publish_chat_event(self, event) -> None:
        with self._lock:
            subscribers = list(self._chat_subscribers.values())

        for subscriber_queue in subscribers:
            subscriber_queue.put(event)

    def _current_turn_locked(self) -> TurnInfo | None:
        if not self._turn_order:
            return None

        player_id = self._turn_order[self._turn_index]
        player = self._players.get(player_id)
        if player is None:
            return None

        return TurnInfo(player=player, round_number=self._round_number, phase=self._phase)

    def _advance_if_everyone_answered_locked(self) -> TurnInfo | None:
        if self._waiting_guessers:
            return None

        self._advance_turn_locked()
        self._phase = TurnPhase.PRE_HINT_GUESS
        self._normalize_pre_hint_phase_locked()
        return self._current_turn_locked()

    def _advance_turn_locked(self) -> None:
        if not self._turn_order:
            return

        if self._turn_index < 0 or self._turn_index >= len(self._turn_order):
            self._turn_index = self._turn_index % len(self._turn_order)

        self._turn_index = (self._turn_index + 1) % len(self._turn_order)
        if self._turn_index == 0:
            self._round_number += 1

    def _normalize_pre_hint_phase_locked(self) -> None:
        if self._phase != TurnPhase.PRE_HINT_GUESS:
            return

        current_turn = self._current_turn_locked()
        if current_turn is None:
            return

        if not self._can_player_attempt_guess_locked(current_turn.player.player_id):
            self._phase = TurnPhase.HINT

    def _can_player_attempt_guess_locked(self, player_id: str) -> bool:
        if player_id in self._guessing_blocked_players:
            return False
        return self._remaining_guesses.get(player_id, 0) > 0

    def _eligible_guessers_for_owner_locked(self, owner_player_id: str) -> list[str]:
        return [
            player_id
            for player_id in self._turn_order
            if player_id != owner_player_id
            and self._can_player_attempt_guess_locked(player_id)
        ]

    def _mark_player_as_successful_guesser_locked(self, player_id: str) -> None:
        self._guessing_blocked_players.add(player_id)
        self._remaining_guesses[player_id] = 0

    def _finalize_if_game_over_locked(self) -> tuple[bool, str | None]:
        is_game_over, reason = self._compute_game_over_locked()
        if is_game_over:
            self._finish_game_locked()
        return is_game_over, reason

    def _add_score_locked(self, player_id: str, points: int) -> None:
        self._scores[player_id] = self._scores.get(player_id, 0) + points

    def _consume_guess_attempt_locked(self, player_id: str) -> None:
        self._remaining_guesses[player_id] = max(
            0,
            self._remaining_guesses.get(player_id, 0) - 1,
        )

    def _compute_game_over_locked(self) -> tuple[bool, str | None]:
        if len(self._discovered_players) >= len(self._players):
            return True, "all_discovered"

        if self._players and all(
            self._remaining_guesses.get(player_id, 0) <= 0
            for player_id in self._players
        ):
            return True, "all_guesses_exhausted"

        return False, None

    def _finish_game_locked(self) -> None:
        self._game_started = False
        self._waiting_guessers.clear()

    def _is_correct_guess_locked(self, owner_player_id: str, guess: str) -> bool:
        character = self._characters_by_player_id.get(owner_player_id)
        if character is None:
            return False

        normalized_guess = normalize_answer(guess)
        accepted_answers = character.accepted_answers or (character.name,)
        return normalized_guess in {
            normalize_answer(answer)
            for answer in accepted_answers
        }


def load_character_catalog(data_path: str) -> tuple[CharacterCategory, ...]:
    with open(data_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    categories: list[CharacterCategory] = []
    for category_data in data["categories"]:
        characters = tuple(
            CharacterInfo(
                character_id=character_data["id"],
                name=character_data["name"],
                image_path=character_data["image"],
                accepted_answers=tuple(character_data.get("accepted_answers", [])),
            )
            for character_data in category_data["characters"]
        )
        categories.append(
            CharacterCategory(
                category_id=category_data["id"],
                name=category_data["name"],
                characters=characters,
            )
        )
    return tuple(categories)


def now_unix_ms() -> int:
    return int(time.time() * 1000)


def normalize_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.strip().lower())
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.replace("-", " ").split())
