from __future__ import annotations

import queue
import random
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class PlayerInfo:
    player_id: str
    name: str


@dataclass(frozen=True)
class TurnInfo:
    player: PlayerInfo
    round_number: int
    phase: "TurnPhase"


@dataclass(frozen=True)
class GuessResult:
    guesser: PlayerInfo
    owner: PlayerInfo
    guess: str
    next_turn: TurnInfo | None = None


class TurnPhase(Enum):
    PRE_HINT_GUESS = "pre_hint_guess"
    HINT = "hint"
    POST_HINT_GUESSES = "post_hint_guesses"


class GameState:
    """Estado em memoria da partida.

    Os streams nao fazem polling: cada inscrito recebe uma Queue propria e fica
    bloqueado em queue.get() ate que um novo evento seja publicado.
    """

    def __init__(self) -> None:
        self._players: dict[str, PlayerInfo] = {}
        self._game_subscribers: dict[str, queue.Queue] = {}
        self._chat_subscribers: dict[str, queue.Queue] = {}
        self._game_started = False
        self._theme = "Objetos do cotidiano"
        self._objects_by_player_id: dict[str, str] = {}
        self._turn_order: list[str] = []
        self._turn_index = 0
        self._round_number = 1
        self._phase = TurnPhase.PRE_HINT_GUESS
        self._waiting_guessers: set[str] = set()
        self._public_hints: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def add_player(self, name: str) -> tuple[PlayerInfo, list[PlayerInfo], bool]:
        clean_name = name.strip() or "Jogador"

        with self._lock:
            for player in self._players.values():
                if player.name.lower() == clean_name.lower():
                    return player, list(self._players.values()), False

            player = PlayerInfo(player_id=str(uuid.uuid4()), name=clean_name)
            self._players[player.player_id] = player
            players = list(self._players.values())

        return player, players, True

    def get_player(self, player_id: str) -> PlayerInfo | None:
        with self._lock:
            return self._players.get(player_id)

    def get_players(self) -> list[PlayerInfo]:
        with self._lock:
            return list(self._players.values())

    def get_theme(self) -> str:
        with self._lock:
            return self._theme

    def get_game_snapshot_for_player(
        self,
        player_id: str,
    ) -> tuple[bool, str | None, str, TurnInfo | None, list[PlayerInfo]]:
        with self._lock:
            return (
                self._game_started,
                self._objects_by_player_id.get(player_id),
                self._theme,
                self._current_turn_locked(),
                list(self._players.values()),
            )

    def start_game(self) -> tuple[bool, str, list[tuple[PlayerInfo, str]], TurnInfo | None]:
        with self._lock:
            if self._game_started:
                return False, "A partida ja foi iniciada.", [], self._current_turn_locked()

            if len(self._players) < 2:
                return False, "Sao necessarios pelo menos 2 jogadores.", [], None

            players = list(self._players.values())
            objects = random.sample(OBJECT_CATALOG[self._theme], len(players))
            self._objects_by_player_id = {
                player.player_id: object_name
                for player, object_name in zip(players, objects)
            }
            self._turn_order = [player.player_id for player in players]
            self._turn_index = 0
            self._round_number = 1
            self._phase = TurnPhase.PRE_HINT_GUESS
            self._waiting_guessers.clear()
            self._public_hints.clear()
            self._game_started = True

            assignments = [
                (player, self._objects_by_player_id[player.player_id])
                for player in players
            ]
            return True, "Partida iniciada.", assignments, self._current_turn_locked()

    def register_public_hint(
        self,
        player_id: str,
        hint: str,
    ) -> tuple[bool, str, PlayerInfo | None, list[PlayerInfo], TurnInfo | None]:
        clean_hint = hint.strip()
        if not clean_hint:
            return False, "A dica nao pode ser vazia.", None, [], None

        with self._lock:
            if not self._game_started:
                return False, "A partida ainda nao foi iniciada.", None, [], None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None, [], None

            if self._phase != TurnPhase.HINT:
                return False, "Ainda nao e a fase de enviar dica.", None, [], current_turn

            if current_turn.player.player_id != player_id:
                return (
                    False,
                    f"A dica agora deve ser enviada por {current_turn.player.name}.",
                    None,
                    [],
                    current_turn,
                )

            self._public_hints.append((player_id, clean_hint))
            actor = current_turn.player
            waiting_players = [
                player
                for player in self._players.values()
                if player.player_id != actor.player_id
            ]
            self._waiting_guessers = {player.player_id for player in waiting_players}
            self._phase = TurnPhase.POST_HINT_GUESSES
            updated_turn = self._current_turn_locked()

        return True, "Dica publica enviada.", actor, waiting_players, updated_turn

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
                return False, "Voce nao pode adivinhar o proprio objeto.", None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if guesser.player_id != current_turn.player.player_id:
                    return False, "Apenas o jogador do turno pode agir agora.", None
                self._phase = TurnPhase.HINT
                return True, "Palpite enviado. Agora envie sua dica publica.", GuessResult(
                    guesser=guesser,
                    owner=owner,
                    guess=clean_guess,
                    next_turn=self._current_turn_locked(),
                )

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if owner.player_id != current_turn.player.player_id:
                    return (
                        False,
                        f"Agora os palpites devem ser sobre o objeto de {current_turn.player.name}.",
                        None,
                    )
                if guesser.player_id not in self._waiting_guessers:
                    return False, "Voce ja respondeu esta oportunidade.", None

                self._waiting_guessers.remove(guesser.player_id)
                next_turn = self._advance_if_everyone_answered_locked()
                return True, "Palpite enviado.", GuessResult(
                    guesser=guesser,
                    owner=owner,
                    guess=clean_guess,
                    next_turn=next_turn,
                )

            return False, "Agora e a fase de dica publica.", None

    def pass_guess_opportunity(
        self,
        player_id: str,
    ) -> tuple[bool, str, PlayerInfo | None, TurnInfo | None]:
        with self._lock:
            if not self._game_started:
                return False, "A partida ainda nao foi iniciada.", None, None

            player = self._players.get(player_id)
            if player is None:
                return False, "Jogador nao encontrado.", None, None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Nao ha turno ativo.", None, None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if player.player_id != current_turn.player.player_id:
                    return False, "Apenas o jogador do turno pode passar agora.", None, current_turn
                self._phase = TurnPhase.HINT
                return True, "Oportunidade passada. Agora envie sua dica publica.", player, self._current_turn_locked()

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if player.player_id not in self._waiting_guessers:
                    return False, "Voce ja respondeu esta oportunidade.", None, current_turn
                self._waiting_guessers.remove(player.player_id)
                next_turn = self._advance_if_everyone_answered_locked()
                return True, "Oportunidade passada.", player, next_turn

            return False, "Nao ha oportunidade de palpite para passar agora.", None, current_turn

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

        return TurnInfo(
            player=player,
            round_number=self._round_number,
            phase=self._phase,
        )

    def _advance_if_everyone_answered_locked(self) -> TurnInfo | None:
        if self._waiting_guessers:
            return None

        self._advance_turn_locked()
        self._phase = TurnPhase.PRE_HINT_GUESS
        return self._current_turn_locked()

    def _advance_turn_locked(self) -> None:
        if not self._turn_order:
            return

        self._turn_index = (self._turn_index + 1) % len(self._turn_order)
        if self._turn_index == 0:
            self._round_number += 1


def now_unix_ms() -> int:
    return int(time.time() * 1000)


OBJECT_CATALOG = {
    "Objetos do cotidiano": [
        "Chave",
        "Guarda-chuva",
        "Relogio",
        "Mochila",
        "Caneca",
        "Bicicleta",
        "Oculos",
        "Violao",
        "Caderno",
        "Abajur",
        "Controle remoto",
        "Escova de dentes",
    ]
}
