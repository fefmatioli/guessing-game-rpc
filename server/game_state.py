from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARACTER_DATA_PATH = os.path.join(PROJECT_ROOT, "assets", "data", "characters.json")

# Quantos ciclos de dica por sessão (cada jogador dá N dicas por sessão)
HINTS_PER_SESSION = 3

# Chance de ser pego espionando
SPY_CATCH_CHANCE = 0.30

# Pontos por ordem de acerto
GUESS_POINTS = {1: 15, 2: 10, 3: 7}
GUESS_POINTS_DEFAULT = 4  # 4° em diante

# Pontos de bonus/penalidade para o dono do personagem
OWNER_POINTS_ONE    = 12  # exatamente 1 acertou
OWNER_POINTS_TWO    = 8   # exatamente 2 acertaram
OWNER_POINTS_THREE  = 4   # 3 ou mais acertaram
OWNER_POINTS_NONE   = 0   # ninguém acertou
OWNER_POINTS_ALL    = -5  # todos acertaram (penalidade)

SOLO_BONUS          = 5   # bônus para quem foi o único a acertar
SPY_REWARD          = 3   # pontos por espionagem bem-sucedida
SPY_PENALTY         = -5  # penalidade por ser pego espiando


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
    hint_cycle: int       # ciclo atual dentro da sessão (1 a HINTS_PER_SESSION)
    session_number: int   # qual sessão (1 a max_rounds)
    phase: "TurnPhase"


@dataclass
class CharacterReveal:
    player: PlayerInfo
    character: CharacterInfo


@dataclass
class ScoreChange:
    player_id: str
    reason: str
    points_delta: int


@dataclass
class RoundEndResult:
    score_deltas: dict[str, int]
    reveals: list[CharacterReveal]
    score_changes: list[ScoreChange]
    is_final: bool  # True = fim do jogo, sem votação


@dataclass
class VoteResult:
    votes_continue: int
    votes_end: int
    total_players: int
    is_complete: bool
    continue_playing: Optional[bool]


@dataclass
class PendingGuess:
    guess_id: str
    guesser: PlayerInfo
    owner: PlayerInfo
    guess_text: str


@dataclass
class ValidationResult:
    guess_id: str
    guesser: PlayerInfo
    owner: PlayerInfo
    guess_text: str
    accepted: bool
    score_delta: int
    scores: dict[str, int]
    guess_order: int


@dataclass
class GuessResult:
    guess_id: str
    guesser: PlayerInfo
    owner: PlayerInfo
    guess: str
    next_turn: Optional[TurnInfo] = None
    is_session_over: bool = False
    round_end: Optional["RoundEndResult"] = None


@dataclass
class ExchangeResult:
    requester: PlayerInfo
    responder: PlayerInfo
    requester_hint: str
    responder_hint: str
    spy_results: list[tuple[PlayerInfo, bool]]  # (spy, foi_pego)


class TurnPhase(Enum):
    PRE_HINT_GUESS = "pre_hint_guess"
    HINT = "hint"
    POST_HINT_GUESSES = "post_hint_guesses"


class GameState:
    def __init__(self, data_path: str = CHARACTER_DATA_PATH) -> None:
        self._categories = load_character_catalog(data_path)
        self._players: dict[str, PlayerInfo] = {}
        self._room_owner_id: Optional[str] = None

        self._game_subscribers: dict[str, queue.Queue] = {}
        self._chat_subscribers: dict[str, queue.Queue] = {}

        # Estado da sessão atual
        self._game_started = False
        self._voting_phase = False
        self._current_category: Optional[CharacterCategory] = None
        self._characters_by_player_id: dict[str, CharacterInfo] = {}
        self._turn_order: list[str] = []
        self._turn_index = 0
        self._hint_cycle = 1          # 1 a HINTS_PER_SESSION
        self._session_number = 0      # qual sessão estamos (1 a max_rounds)
        self._max_rounds = 1          # total de sessões a jogar
        self._phase = TurnPhase.HINT
        self._waiting_guessers: set[str] = set()
        self._public_hints: list[tuple[str, str]] = []

        # Pontuação acumulada (persiste entre sessões)
        self._scores: dict[str, int] = {}

        # Controle de acertos — por sessão (reset a cada sessão)
        self._correct_guess_order: dict[str, list[str]] = {}   # owner_id -> [guesser_id em ordem]
        self._already_scored: dict[str, set[str]] = {}          # owner_id -> {guesser_ids que já pontuaram}

        # Palpites pendentes de validação manual pelo dono
        self._pending_guesses: dict[str, PendingGuess] = {}

        # Votação de nova sessão
        self._votes: dict[str, bool] = {}

        # Trocas privadas
        self._exchange_used: set[str] = set()
        self._pending_exchange: Optional[tuple[str, str, str]] = None

        # Espionagem: frozenset({A,B}) -> [spy_ids]
        self._spies: dict[frozenset, list[str]] = {}

        self._lock = threading.Lock()

    # ─────────────────────────── Jogadores ────────────────────────────

    def add_player(self, name: str) -> tuple[PlayerInfo, list[PlayerInfo], bool]:
        clean_name = name.strip() or "Jogador"
        with self._lock:
            for player in self._players.values():
                if player.name.lower() == clean_name.lower():
                    return player, list(self._players.values()), False
            player = PlayerInfo(player_id=str(uuid.uuid4()), name=clean_name)
            self._players[player.player_id] = player
            self._scores[player.player_id] = 0
            if self._room_owner_id is None:
                self._room_owner_id = player.player_id
            players = list(self._players.values())
        return player, players, True

    def get_player(self, player_id: str) -> Optional[PlayerInfo]:
        with self._lock:
            return self._players.get(player_id)

    def get_players(self) -> list[PlayerInfo]:
        with self._lock:
            return list(self._players.values())

    def get_room_owner_id(self) -> Optional[str]:
        with self._lock:
            return self._room_owner_id

    def get_scores(self) -> dict[str, int]:
        with self._lock:
            return dict(self._scores)

    def get_current_category(self) -> Optional[CharacterCategory]:
        with self._lock:
            return self._current_category

    def get_max_rounds(self) -> int:
        with self._lock:
            return self._max_rounds

    def get_session_number(self) -> int:
        with self._lock:
            return self._session_number

    def get_hint_cycle(self) -> int:
        with self._lock:
            return self._hint_cycle

    def is_voting_phase(self) -> bool:
        with self._lock:
            return self._voting_phase

    def get_game_snapshot_for_player(
        self, player_id: str
    ) -> tuple[bool, Optional[CharacterCategory], Optional[CharacterInfo], Optional[TurnInfo], list[PlayerInfo]]:
        with self._lock:
            return (
                self._game_started,
                self._current_category,
                self._characters_by_player_id.get(player_id),
                self._current_turn_locked(),
                list(self._players.values()),
            )

    # ─────────────────────────── Início de partida ────────────────────

    def start_game(
        self, requesting_player_id: str, max_rounds: int
    ) -> tuple[bool, str, Optional[CharacterCategory], list[CharacterAssignment], Optional[TurnInfo]]:
        with self._lock:
            if self._game_started:
                return False, "A partida já foi iniciada.", self._current_category, [], self._current_turn_locked()
            if requesting_player_id != self._room_owner_id:
                return False, "Apenas o dono da sala pode iniciar a partida.", None, [], None
            if max_rounds <= 0:
                return False, "O número de rodadas deve ser maior que zero.", None, [], None
            player_count = len(self._players)
            if player_count < 2:
                return False, "São necessários pelo menos 2 jogadores.", None, [], None

            self._max_rounds = max_rounds
            self._session_number = 0
            # Zera placar ao iniciar nova partida
            for pid in self._players:
                self._scores[pid] = 0

            possible = [c for c in self._categories if len(c.characters) >= player_count]
            if not possible:
                return False, "Nenhuma categoria com personagens suficientes.", None, [], None
            return self._setup_session_locked(possible)

    def _setup_session_locked(
        self, possible_categories: Optional[list] = None
    ) -> tuple[bool, str, Optional[CharacterCategory], list[CharacterAssignment], Optional[TurnInfo]]:
        player_count = len(self._players)
        if possible_categories is None:
            possible_categories = [c for c in self._categories if len(c.characters) >= player_count]
            if not possible_categories:
                return False, "Nenhuma categoria disponível.", None, [], None

        # Evita repetir a categoria da sessão anterior
        if self._current_category is not None and len(possible_categories) > 1:
            possible_categories = [
                c for c in possible_categories
                if c.category_id != self._current_category.category_id
            ] or possible_categories

        players = list(self._players.values())
        category = random.choice(possible_categories)
        characters = random.sample(list(category.characters), player_count)

        self._current_category = category
        self._characters_by_player_id = {p.player_id: ch for p, ch in zip(players, characters)}
        self._turn_order = [p.player_id for p in players]
        random.shuffle(self._turn_order)
        self._turn_index = 0
        self._hint_cycle = 1
        self._session_number += 1
        self._phase = TurnPhase.HINT
        self._waiting_guessers.clear()
        self._public_hints.clear()
        self._correct_guess_order.clear()
        self._already_scored.clear()
        self._pending_guesses.clear()
        self._exchange_used.clear()
        self._pending_exchange = None
        self._spies.clear()
        self._game_started = True
        self._voting_phase = False
        self._votes.clear()

        assignments = [
            CharacterAssignment(player=p, character=self._characters_by_player_id[p.player_id])
            for p in players
        ]
        return (
            True,
            f"Sessão {self._session_number}/{self._max_rounds} iniciada.",
            category, assignments, self._current_turn_locked(),
        )

    # ─────────────────────────── Dica pública ─────────────────────────

    def register_public_hint(
        self, player_id: str, hint: str
    ) -> tuple[bool, str, Optional[PlayerInfo], list[PlayerInfo], Optional[TurnInfo], bool, Optional[RoundEndResult]]:
        clean_hint = hint.strip()
        if not clean_hint:
            return False, "A dica não pode ser vazia.", None, [], None, False, None

        with self._lock:
            if not self._game_started:
                return False, "A partida ainda não foi iniciada.", None, [], None, False, None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Não há turno ativo.", None, [], None, False, None
            if self._phase != TurnPhase.HINT:
                return False, "Ainda não é a fase de enviar dica.", None, [], current_turn, False, None
            if current_turn.player.player_id != player_id:
                return False, f"A dica deve ser enviada por {current_turn.player.name}.", None, [], current_turn, False, None

            self._public_hints.append((player_id, clean_hint))
            actor = current_turn.player

            # Ciclo 1: apenas dicas, sem palpites pós-dica
            if self._hint_cycle == 1:
                self._advance_turn_locked()
                self._phase = TurnPhase.HINT if self._hint_cycle == 1 else TurnPhase.PRE_HINT_GUESS
                self._normalize_pre_hint_phase_locked()
                is_over, end_result = self._check_session_over_locked()
                return True, "Dica pública enviada.", actor, [], None if is_over else self._current_turn_locked(), is_over, end_result

            # Ciclos 2+: abre fase de palpites para os elegíveis
            waiting_ids = self._eligible_guessers_for_owner_locked(actor.player_id)
            if not waiting_ids:
                # Ninguém pode palpitar, avança direto
                self._advance_turn_locked()
                self._phase = TurnPhase.PRE_HINT_GUESS
                self._normalize_pre_hint_phase_locked()
                is_over, end_result = self._check_session_over_locked()
                return True, "Dica pública enviada.", actor, [], None if is_over else self._current_turn_locked(), is_over, end_result

            waiting_players = [self._players[pid] for pid in waiting_ids]
            self._waiting_guessers = set(waiting_ids)
            self._phase = TurnPhase.POST_HINT_GUESSES
            return True, "Dica pública enviada.", actor, waiting_players, self._current_turn_locked(), False, None

    # ─────────────────────────── Palpite (pendente) ───────────────────

    def submit_guess(
        self, guesser_player_id: str, owner_player_id: str, guess: str
    ) -> tuple[bool, str, Optional[GuessResult]]:
        clean_guess = guess.strip()
        if not clean_guess:
            return False, "O palpite não pode ser vazio.", None

        with self._lock:
            if not self._game_started:
                return False, "A partida ainda não foi iniciada.", None

            guesser = self._players.get(guesser_player_id)
            owner = self._players.get(owner_player_id)
            if guesser is None or owner is None:
                return False, "Jogador não encontrado.", None
            if guesser.player_id == owner.player_id:
                return False, "Você não pode adivinhar o próprio personagem.", None
            if guesser.player_id in self._already_scored.get(owner.player_id, set()):
                return False, "Você já pontuou pelo personagem deste jogador.", None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Não há turno ativo.", None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if guesser.player_id != current_turn.player.player_id:
                    return False, "Apenas o jogador do turno pode agir agora.", None
                guess_id = str(uuid.uuid4())
                self._pending_guesses[guess_id] = PendingGuess(
                    guess_id=guess_id, guesser=guesser, owner=owner, guess_text=clean_guess,
                )
                self._phase = TurnPhase.HINT
                return True, "Palpite enviado. Aguarde validação do dono.", GuessResult(
                    guess_id=guess_id, guesser=guesser, owner=owner, guess=clean_guess,
                    next_turn=self._current_turn_locked(),
                )

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if owner.player_id != current_turn.player.player_id:
                    return False, f"Agora os palpites devem ser sobre {current_turn.player.name}.", None
                if guesser.player_id not in self._waiting_guessers:
                    return False, "Você já respondeu esta oportunidade.", None

                guess_id = str(uuid.uuid4())
                self._pending_guesses[guess_id] = PendingGuess(
                    guess_id=guess_id, guesser=guesser, owner=owner, guess_text=clean_guess,
                )
                self._waiting_guessers.discard(guesser.player_id)
                next_turn = self._advance_if_everyone_answered_locked()
                is_session_over, round_end = False, None
                if next_turn is not None:
                    is_session_over, round_end = self._check_session_over_locked()
                    if is_session_over:
                        next_turn = None
                return True, "Palpite enviado. Aguarde validação do dono.", GuessResult(
                    guess_id=guess_id, guesser=guesser, owner=owner, guess=clean_guess,
                    next_turn=next_turn, is_session_over=is_session_over, round_end=round_end,
                )

            return False, "Agora é a fase de dica pública.", None

    # ─────────────────────────── Validação manual ─────────────────────

    def validate_guess(
        self, owner_player_id: str, guess_id: str, accepted: bool
    ) -> tuple[bool, str, Optional[ValidationResult]]:
        with self._lock:
            pending = self._pending_guesses.get(guess_id)
            if pending is None:
                return False, "Palpite não encontrado.", None
            if pending.owner.player_id != owner_player_id:
                return False, "Você não é o dono deste personagem.", None

            del self._pending_guesses[guess_id]

            if not accepted:
                return True, f"Palpite de {pending.guesser.name} rejeitado.", ValidationResult(
                    guess_id=guess_id, guesser=pending.guesser, owner=pending.owner,
                    guess_text=pending.guess_text, accepted=False,
                    score_delta=0, scores=dict(self._scores), guess_order=0,
                )

            # Já pontuou por este personagem?
            if pending.guesser.player_id in self._already_scored.get(pending.owner.player_id, set()):
                return True, "Palpite aceito, mas jogador já pontuou por este personagem.", ValidationResult(
                    guess_id=guess_id, guesser=pending.guesser, owner=pending.owner,
                    guess_text=pending.guess_text, accepted=True,
                    score_delta=0, scores=dict(self._scores), guess_order=0,
                )

            # Verifica se a resposta bate com as accepted_answers do personagem
            if not self._is_correct_guess_locked(pending.owner.player_id, pending.guess_text):
                # Dono aceitou mas a resposta não bate — o dono decide, então aceita de qualquer forma
                pass

            order_list = self._correct_guess_order.setdefault(pending.owner.player_id, [])
            order = len(order_list) + 1
            delta = _calculate_guess_points(order)
            self._add_score_locked(pending.guesser.player_id, delta)
            order_list.append(pending.guesser.player_id)
            self._already_scored.setdefault(pending.owner.player_id, set()).add(pending.guesser.player_id)

            return True, f"Palpite aceito! {pending.guesser.name} ganhou {delta} pontos (#{order}).", ValidationResult(
                guess_id=guess_id, guesser=pending.guesser, owner=pending.owner,
                guess_text=pending.guess_text, accepted=True,
                score_delta=delta, scores=dict(self._scores), guess_order=order,
            )

    # ─────────────────────────── Passar oportunidade ──────────────────

    def pass_guess_opportunity(
        self, player_id: str
    ) -> tuple[bool, str, Optional[PlayerInfo], Optional[TurnInfo], bool, Optional[RoundEndResult]]:
        with self._lock:
            if not self._game_started:
                return False, "A partida ainda não foi iniciada.", None, None, False, None

            player = self._players.get(player_id)
            if player is None:
                return False, "Jogador não encontrado.", None, None, False, None

            current_turn = self._current_turn_locked()
            if current_turn is None:
                return False, "Não há turno ativo.", None, None, False, None

            if self._phase == TurnPhase.PRE_HINT_GUESS:
                if player.player_id != current_turn.player.player_id:
                    return False, "Apenas o jogador do turno pode passar agora.", None, current_turn, False, None
                self._phase = TurnPhase.HINT
                return True, "Oportunidade passada. Envie sua dica pública.", player, self._current_turn_locked(), False, None

            if self._phase == TurnPhase.POST_HINT_GUESSES:
                if player.player_id not in self._waiting_guessers:
                    return False, "Você já respondeu esta oportunidade.", None, current_turn, False, None
                self._waiting_guessers.discard(player.player_id)
                next_turn = self._advance_if_everyone_answered_locked()
                if next_turn is not None:
                    is_over, end_result = self._check_session_over_locked()
                    if is_over:
                        return True, "Oportunidade passada.", player, None, True, end_result
                return True, "Oportunidade passada.", player, next_turn, False, None

            return False, "Não há oportunidade de palpite para passar agora.", None, current_turn, False, None

    # ─────────────────────────── Votação ──────────────────────────────

    def cast_vote(
        self, player_id: str, continue_playing: bool
    ) -> tuple[bool, str, Optional[VoteResult], Optional[tuple]]:
        with self._lock:
            if not self._voting_phase:
                return False, "Não há votação ativa.", None, None
            player = self._players.get(player_id)
            if player is None:
                return False, "Jogador não encontrado.", None, None
            if player_id in self._votes:
                return False, "Você já votou.", None, None

            self._votes[player_id] = continue_playing
            total = len(self._players)
            votes_continue = sum(1 for v in self._votes.values() if v)
            votes_end = sum(1 for v in self._votes.values() if not v)
            is_complete = len(self._votes) >= total

            result = VoteResult(
                votes_continue=votes_continue, votes_end=votes_end,
                total_players=total, is_complete=is_complete, continue_playing=None,
            )
            if not is_complete:
                return True, "Voto registrado.", result, None

            do_continue = votes_continue >= votes_end
            result.continue_playing = do_continue

            if do_continue and self._session_number < self._max_rounds:
                ok, msg, category, assignments, turn = self._setup_session_locked()
                if not ok:
                    self._voting_phase = False
                    return False, msg, result, None
                return True, "Nova sessão iniciando!", result, (category, assignments, turn)
            else:
                self._voting_phase = False
                self._game_started = False
                return True, "Fim de jogo.", result, None

    # ─────────────────────────── Troca de dicas ───────────────────────

    def request_hint_exchange(
        self, requester_id: str, target_id: str, hint: str
    ) -> tuple[bool, str, Optional[PlayerInfo], Optional[PlayerInfo]]:
        clean_hint = hint.strip()
        if not clean_hint:
            return False, "A dica não pode ser vazia.", None, None
        if len(clean_hint.split()) > 1:
            return False, "A dica privada deve ser uma única palavra.", None, None

        with self._lock:
            if not self._game_started:
                return False, "A partida ainda não foi iniciada.", None, None
            requester = self._players.get(requester_id)
            target = self._players.get(target_id)
            if requester is None or target is None:
                return False, "Jogador não encontrado.", None, None
            if requester_id == target_id:
                return False, "Você não pode trocar dicas consigo mesmo.", None, None
            if requester_id in self._exchange_used:
                return False, "Você já usou sua troca de dicas nesta sessão.", None, None
            if self._pending_exchange is not None:
                return False, "Já existe uma troca pendente.", None, None

            self._pending_exchange = (requester_id, target_id, clean_hint)
            return True, "Solicitação de troca enviada.", requester, target

    def respond_hint_exchange(
        self, responder_id: str, requester_id: str, accepted: bool, hint: str
    ) -> tuple[bool, str, Optional[ExchangeResult]]:
        with self._lock:
            if self._pending_exchange is None:
                return False, "Não há troca pendente.", None
            req_id, tgt_id, req_hint = self._pending_exchange
            if tgt_id != responder_id or req_id != requester_id:
                return False, "Esta troca não é destinada a você.", None

            requester = self._players.get(req_id)
            responder = self._players.get(responder_id)
            if requester is None or responder is None:
                self._pending_exchange = None
                return False, "Jogador não encontrado.", None

            self._pending_exchange = None
            if not accepted:
                return True, f"{responder.name} recusou a troca.", None

            clean_hint = hint.strip()
            if not clean_hint or len(clean_hint.split()) > 1:
                return False, "A dica de resposta deve ser uma única palavra.", None

            self._exchange_used.add(req_id)
            self._exchange_used.add(responder_id)

            pair_key = frozenset({req_id, responder_id})
            spy_ids = self._spies.pop(pair_key, [])
            spy_results: list[tuple[PlayerInfo, bool]] = []
            for spy_id in spy_ids:
                spy = self._players.get(spy_id)
                if spy is None:
                    continue
                caught = random.random() < SPY_CATCH_CHANCE
                if caught:
                    self._add_score_locked(spy_id, SPY_PENALTY)
                else:
                    self._add_score_locked(spy_id, SPY_REWARD)
                spy_results.append((spy, caught))

            return True, f"{requester.name} e {responder.name} trocaram dicas privadas.", ExchangeResult(
                requester=requester, responder=responder,
                requester_hint=req_hint, responder_hint=clean_hint,
                spy_results=spy_results,
            )

    def spy_on_exchange(self, spy_id: str, player_a_id: str, player_b_id: str) -> tuple[bool, str]:
        with self._lock:
            if not self._game_started:
                return False, "A partida ainda não foi iniciada."
            spy = self._players.get(spy_id)
            player_a = self._players.get(player_a_id)
            player_b = self._players.get(player_b_id)
            if spy is None or player_a is None or player_b is None:
                return False, "Jogador não encontrado."
            if spy_id in {player_a_id, player_b_id}:
                return False, "Você não pode espionar uma troca que envolve você."
            pair_key = frozenset({player_a_id, player_b_id})
            spies = self._spies.setdefault(pair_key, [])
            if spy_id in spies:
                return False, "Você já está espiando esta dupla."
            spies.append(spy_id)
            return True, f"Você está espiando a troca entre {player_a.name} e {player_b.name}."

    # ─────────────────────────── Subscribers ──────────────────────────

    def add_game_subscriber(self, player_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._game_subscribers[player_id] = q
        return q

    def remove_game_subscriber(self, player_id: str) -> None:
        with self._lock:
            self._game_subscribers.pop(player_id, None)

    def add_chat_subscriber(self, player_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._chat_subscribers[player_id] = q
        return q

    def remove_chat_subscriber(self, player_id: str) -> None:
        with self._lock:
            self._chat_subscribers.pop(player_id, None)

    def publish_game_event(self, event) -> None:
        with self._lock:
            subscribers = list(self._game_subscribers.values())
        for q in subscribers:
            q.put(event)

    def publish_game_event_to_player(self, player_id: str, event) -> None:
        with self._lock:
            q = self._game_subscribers.get(player_id)
        if q is not None:
            q.put(event)

    def publish_chat_event(self, event) -> None:
        with self._lock:
            subscribers = list(self._chat_subscribers.values())
        for q in subscribers:
            q.put(event)

    # ─────────────────────────── Helpers internos ─────────────────────

    def _current_turn_locked(self) -> Optional[TurnInfo]:
        if not self._turn_order:
            return None
        player_id = self._turn_order[self._turn_index]
        player = self._players.get(player_id)
        if player is None:
            return None
        return TurnInfo(
            player=player,
            hint_cycle=self._hint_cycle,
            session_number=self._session_number,
            phase=self._phase,
        )

    def _advance_if_everyone_answered_locked(self) -> Optional[TurnInfo]:
        if self._waiting_guessers:
            return None
        self._advance_turn_locked()
        self._phase = TurnPhase.PRE_HINT_GUESS
        self._normalize_pre_hint_phase_locked()
        return self._current_turn_locked()

    def _advance_turn_locked(self) -> None:
        if not self._turn_order:
            return
        self._turn_index = (self._turn_index + 1) % len(self._turn_order)
        if self._turn_index == 0:
            self._hint_cycle += 1

    def _normalize_pre_hint_phase_locked(self) -> None:
        if self._phase != TurnPhase.PRE_HINT_GUESS:
            return
        # Ciclo 1: nada de pré-palpite
        if self._hint_cycle == 1:
            self._phase = TurnPhase.HINT

    def _eligible_guessers_for_owner_locked(self, owner_player_id: str) -> list[str]:
        scored_set = self._already_scored.get(owner_player_id, set())
        return [
            pid for pid in self._turn_order
            if pid != owner_player_id and pid not in scored_set
        ]

    def _check_session_over_locked(self) -> tuple[bool, Optional[RoundEndResult]]:
        if not self._is_session_over_locked():
            return False, None
        return True, self._end_session_locked()

    def _is_session_over_locked(self) -> bool:
        # Sessão acaba quando os ciclos de dicas se esgotam
        return self._hint_cycle > HINTS_PER_SESSION

    def _end_session_locked(self) -> RoundEndResult:
        # Auto-rejeita palpites ainda pendentes
        self._pending_guesses.clear()

        score_deltas: dict[str, int] = {pid: 0 for pid in self._players}
        changes: list[ScoreChange] = []
        total_others = len(self._players) - 1

        for owner_id in self._players:
            guessers = self._correct_guess_order.get(owner_id, [])
            n = len(guessers)

            # Bônus solo para o único que acertou
            if n == 1:
                solo_id = guessers[0]
                self._add_score_locked(solo_id, SOLO_BONUS)
                score_deltas[solo_id] = score_deltas.get(solo_id, 0) + SOLO_BONUS
                changes.append(ScoreChange(solo_id, "SOLO_BONUS", SOLO_BONUS))

            # Pontos do dono baseado em quantos acertaram
            if total_others > 0:
                if n == 0:
                    owner_delta = OWNER_POINTS_NONE
                elif n >= total_others:  # todos os outros acertaram — penalidade prevalece
                    owner_delta = OWNER_POINTS_ALL
                elif n == 1:
                    owner_delta = OWNER_POINTS_ONE
                elif n == 2:
                    owner_delta = OWNER_POINTS_TWO
                else:
                    owner_delta = OWNER_POINTS_THREE

                if owner_delta != 0:
                    self._add_score_locked(owner_id, owner_delta)
                    score_deltas[owner_id] = score_deltas.get(owner_id, 0) + owner_delta
                    reason = "OWNER_" + ("ALL" if n >= total_others else ("ONE" if n == 1 else ("TWO" if n == 2 else "THREE")))
                    changes.append(ScoreChange(owner_id, reason, owner_delta))

        reveals = [
            CharacterReveal(player=self._players[pid], character=ch)
            for pid, ch in self._characters_by_player_id.items()
            if pid in self._players
        ]

        is_final = self._session_number >= self._max_rounds

        self._game_started = False
        if not is_final:
            self._voting_phase = True
            self._votes.clear()

        return RoundEndResult(
            score_deltas=score_deltas,
            reveals=reveals,
            score_changes=changes,
            is_final=is_final,
        )

    def _add_score_locked(self, player_id: str, points: int) -> None:
        self._scores[player_id] = self._scores.get(player_id, 0) + points

    def _is_correct_guess_locked(self, owner_player_id: str, guess: str) -> bool:
        character = self._characters_by_player_id.get(owner_player_id)
        if character is None:
            return False
        normalized = normalize_answer(guess)
        answers = character.accepted_answers or (character.name,)
        return normalized in {normalize_answer(a) for a in answers}


# ─────────────────────────── Utilitários ──────────────────────────────

def _calculate_guess_points(order: int) -> int:
    return GUESS_POINTS.get(order, GUESS_POINTS_DEFAULT)


def load_character_catalog(data_path: str) -> tuple[CharacterCategory, ...]:
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    categories: list[CharacterCategory] = []
    for cat in data["categories"]:
        characters = tuple(
            CharacterInfo(
                character_id=ch["id"],
                name=ch["name"],
                image_path=ch["image"],
                accepted_answers=tuple(ch.get("accepted_answers", [])),
            )
            for ch in cat["characters"]
        )
        categories.append(CharacterCategory(
            category_id=cat["id"], name=cat["name"], characters=characters,
        ))
    return tuple(categories)


def now_unix_ms() -> int:
    return int(time.time() * 1000)


def normalize_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.strip().lower())
    without_accents = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return " ".join(without_accents.replace("-", " ").split())
