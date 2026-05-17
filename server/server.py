from __future__ import annotations

import os
import sys
from concurrent import futures

import grpc

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
GENERATED_DIR = os.path.join(PROJECT_ROOT, "generated")
sys.path.insert(0, GENERATED_DIR)

import game_pb2  # noqa: E402
import game_pb2_grpc  # noqa: E402
from game_state import (  # noqa: E402
    GameState, TurnPhase, RoundEndResult, ExchangeResult, now_unix_ms,
)

class GameService(game_pb2_grpc.GameServiceServicer):
    def __init__(self, state: GameState) -> None:
        self._state = state

    # JoinGame
    def JoinGame(self, request, context):
        player, players, created = self._state.add_player(request.player_name)
        owner_id = self._state.get_room_owner_id() or ""

        if created:
            event = game_pb2.GameEvent(
                type=game_pb2.PLAYER_JOINED,
                message=f"{player.name} entrou na partida.",
                actor_player_id=player.player_id,
                players=self._players_to_proto(players),
                room_owner_id=owner_id,
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(event)
            print(f"[GAME] {event.message}")

        return game_pb2.JoinGameResponse(
            success=True,
            message="Entrada realizada com sucesso." if created else "Nome ja conectado; reutilizando jogador.",
            player_id=player.player_id,
            players=[game_pb2.Player(player_id=p.player_id, name=p.name) for p in players],
            room_owner_id=owner_id,
        )

    # LeaveGame
    def LeaveGame(self, request, context):
        (
            success, message, player, players, owner_id,
            current_turn, waiting_players, is_round_over, round_end,
        ) = self._state.remove_player(request.player_id)
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        event = game_pb2.GameEvent(
            type=game_pb2.PLAYER_LEFT,
            message=message,
            actor_player_id=player.player_id,
            players=self._players_to_proto(players),
            room_owner_id=owner_id or "",
            scores=self._scores_to_proto(self._state.get_scores()),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

        if is_round_over and round_end is not None:
            self._publish_round_ended(round_end)
        elif current_turn is not None:
            if current_turn.phase == TurnPhase.POST_HINT_GUESSES and waiting_players:
                self._publish_guess_phase_started(current_turn, waiting_players)
            else:
                self._publish_hint_phase_started(current_turn)

        return game_pb2.CommandResponse(success=True, message=message)

    # Subscribe
    def SubscribeToGameEvents(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Jogador nao encontrado.")

        q = self._state.add_game_subscriber(request.player_id)
        print(f"[STREAM] {player.name} inscrito nos eventos de jogo.")
        context.add_callback(lambda: q.put(None))
        self._enqueue_snapshot_for_player(request.player_id, q)

        try:
            while context.is_active():
                event = q.get()
                if event is None:
                    break
                yield event
        finally:
            self._state.remove_game_subscriber(request.player_id)
            print(f"[STREAM] {player.name} saiu dos eventos de jogo.")

    # StartGame
    def StartGame(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            return game_pb2.CommandResponse(success=False, message="Jogador nao encontrado.")

        max_rounds = request.max_rounds or 3
        max_turns = request.max_turns or 3
        success, message, category, assignments, current_turn = self._state.start_game(
            request.player_id, max_rounds, max_turns,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        owner_id = self._state.get_room_owner_id() or ""
        self._publish_session_start_events(player.player_id, max_rounds, category, assignments, current_turn, owner_id, is_new_session=False)
        print(f"[GAME] {player.name} iniciou a partida.")
        return game_pb2.CommandResponse(success=True, message=message)

    def _publish_session_start_events(self, actor_id, max_rounds, category, assignments, current_turn, owner_id, is_new_session: bool):
        event_type = game_pb2.NEW_ROUND_STARTED if is_new_session else game_pb2.GAME_STARTED
        session_number = self._state.get_session_number()

        started_event = game_pb2.GameEvent(
            type=event_type,
            message=(
                f"Sessao {session_number}/{max_rounds} iniciando!"
                if is_new_session else
                f"Partida iniciada! {max_rounds} sessao(oes) no total."
            ),
            actor_player_id=actor_id,
            max_rounds=max_rounds,
            session_number=session_number,
            is_final_session=(session_number >= max_rounds),
            room_owner_id=owner_id,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(started_event)

        round_event = game_pb2.GameEvent(
            type=game_pb2.ROUND_STARTED,
            message=f"Sessao {session_number}/{max_rounds} — Categoria: {category.name}.",
            category_id=category.category_id,
            category_name=category.name,
            theme=category.name,
            max_rounds=max_rounds,
            session_number=session_number,
            is_final_session=(session_number >= max_rounds),
            room_owner_id=owner_id,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(round_event)

        for assignment in assignments:
            private_event = game_pb2.GameEvent(
                type=game_pb2.CHARACTER_ASSIGNED,
                message="Voce recebeu seu personagem secreto.",
                target_player_id=assignment.player.player_id,
                category_id=category.category_id,
                category_name=category.name,
                character_id=assignment.character.character_id,
                object_name=assignment.character.name,
                image_path=assignment.character.image_path,
                theme=category.name,
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event_to_player(assignment.player.player_id, private_event)

        if current_turn is not None:
            self._publish_hint_phase_started(current_turn)

    # SendPublicHint
    def SendPublicHint(self, request, context):
        success, message, actor, waiting_players, current_turn, is_round_over, round_end = (
            self._state.register_public_hint(request.player_id, request.hint)
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        hint = request.hint.strip()
        hint_cycle = self._state.get_hint_cycle()
        hint_event = game_pb2.GameEvent(
            type=game_pb2.PUBLIC_HINT_SENT,
            message=f"{actor.name} deu uma dica publica: {hint}",
            actor_player_id=actor.player_id,
            target_player_id=actor.player_id,
            public_hint=hint,
            current_turn_player_id=actor.player_id,
            current_turn_player_name=actor.name,
            turn_phase=game_pb2.POST_HINT_GUESSES,
            hint_cycle=hint_cycle,
            max_hint_cycles=self._state.get_max_turns(),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(hint_event)
        print(f"[GAME] {hint_event.message}")

        if is_round_over and round_end is not None:
            self._publish_round_ended(round_end)
        elif waiting_players and current_turn is not None:
            self._publish_guess_phase_started(current_turn, waiting_players)
        elif current_turn is not None:
            self._publish_hint_phase_started(current_turn)

        return game_pb2.CommandResponse(success=True, message=message)

    # SubmitGuess
    def SubmitGuess(self, request, context):
        success, message, result = self._state.submit_guess(
            request.guesser_player_id, request.owner_player_id, request.guess,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        guesser = self._state.get_player(request.guesser_player_id)
        owner = self._state.get_player(request.owner_player_id)
        if guesser and owner:
            # notifica todos sem revelar o texto do palpite
            public_event = game_pb2.GameEvent(
                type=game_pb2.GUESS_SUBMITTED,
                message=f"{guesser.name} enviou um palpite para {owner.name}. Aguardando validacao.",
                actor_player_id=guesser.player_id,
                target_player_id=owner.player_id,
                guess_id=result.guess_id,
                guesser_player_name=guesser.name,
                owner_player_name=owner.name,
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(public_event)

            # manda o texto só para o dono validar
            pending_event = game_pb2.GameEvent(
                type=game_pb2.PENDING_GUESS_FOR_OWNER,
                message=f"{guesser.name} tentou adivinhar seu personagem: '{request.guess}'",
                actor_player_id=guesser.player_id,
                target_player_id=owner.player_id,
                guess_id=result.guess_id,
                guess_text=request.guess,
                guesser_player_name=guesser.name,
                owner_player_name=owner.name,
                accepted=self._state.is_guess_text_valid(owner.player_id, request.guess),
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event_to_player(owner.player_id, pending_event)
            print(f"[GAME] {public_event.message}")

        if result.is_session_over and result.round_end is not None:
            self._publish_round_ended(result.round_end)
        elif result.next_turn is not None:
            self._publish_hint_phase_started(result.next_turn)

        return game_pb2.CommandResponse(success=True, message=message)

    # ValidateGuess
    def ValidateGuess(self, request, context):
        success, message, result, is_session_over, round_end = self._state.validate_guess(
            request.owner_player_id, request.guess_id, request.accepted,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        scores_proto = self._scores_to_proto(result.scores)

        if result.accepted:
            event = game_pb2.GameEvent(
                type=game_pb2.GUESS_ACCEPTED,
                message=(
                    f"Palpite de {result.guesser.name} ACEITO! "
                    f"'{result.guess_text}' — +{result.score_delta} pts (#{result.guess_order}° a acertar este objeto)"
                ),
                actor_player_id=result.owner.player_id,
                target_player_id=result.guesser.player_id,
                guess_id=result.guess_id,
                guess_text=result.guess_text,
                guesser_player_name=result.guesser.name,
                owner_player_name=result.owner.name,
                accepted=True,
                scores=scores_proto,
                score_delta=result.score_delta,
                guess_order=result.guess_order,
                timestamp_unix_ms=now_unix_ms(),
            )
        else:
            event = game_pb2.GameEvent(
                type=game_pb2.GUESS_REJECTED,
                message=f"Palpite de {result.guesser.name} REJEITADO por {result.owner.name}.",
                actor_player_id=result.owner.player_id,
                target_player_id=result.guesser.player_id,
                guess_id=result.guess_id,
                guess_text=result.guess_text,
                guesser_player_name=result.guesser.name,
                owner_player_name=result.owner.name,
                accepted=False,
                timestamp_unix_ms=now_unix_ms(),
            )

        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

        if is_session_over and round_end is not None:
            self._publish_round_ended(round_end)

        return game_pb2.CommandResponse(success=True, message=message)

    # PassGuessOpportunity
    def PassGuessOpportunity(self, request, context):
        success, message, player, next_turn, is_round_over, round_end = (
            self._state.pass_guess_opportunity(request.player_id)
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        event = game_pb2.GameEvent(
            type=game_pb2.GUESS_OPPORTUNITY_PASSED,
            message=f"{player.name} passou a oportunidade de palpite.",
            actor_player_id=player.player_id,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)

        if is_round_over and round_end is not None:
            self._publish_round_ended(round_end)
        elif next_turn is not None:
            self._publish_hint_phase_started(next_turn)

        print(f"[GAME] {event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    # VoteForNextRound
    def VoteForNextRound(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            return game_pb2.CommandResponse(success=False, message="Jogador nao encontrado.")

        success, message, vote_result, new_round_data = self._state.cast_vote(
            request.player_id, request.continue_playing,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        vote_event = game_pb2.GameEvent(
            type=game_pb2.VOTE_CAST,
            message=(
                f"{player.name} votou para {'continuar' if request.continue_playing else 'encerrar'}. "
                f"({vote_result.votes_continue} continuar / {vote_result.votes_end} encerrar)"
            ),
            actor_player_id=request.player_id,
            votes_continue=vote_result.votes_continue,
            votes_end=vote_result.votes_end,
            votes_needed=vote_result.votes_needed,
            vote_continue=request.continue_playing,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(vote_event)
        print(f"[GAME] {vote_event.message}")

        if vote_result.is_complete:
            if vote_result.continue_playing and new_round_data is not None:
                category, assignments, current_turn = new_round_data
                owner_id = self._state.get_room_owner_id() or ""
                self._publish_session_start_events(
                    request.player_id, self._state.get_max_rounds(),
                    category, assignments, current_turn, owner_id, is_new_session=True,
                )
            elif vote_result.continue_playing and vote_result.new_game_config:
                self._publish_new_game_approved()
            else:
                self._publish_game_ended(self._state.get_scores())

        return game_pb2.CommandResponse(success=True, message=message)

    # RequestHintExchange
    def RequestHintExchange(self, request, context):
        success, message, requester, target = self._state.request_hint_exchange(
            request.requester_player_id, request.target_player_id, request.private_hint,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        private_event = game_pb2.GameEvent(
            type=game_pb2.HINT_EXCHANGE_REQUESTED,
            message=f"{requester.name} quer trocar dicas com voce. Dica deles: '{request.private_hint}'",
            actor_player_id=requester.player_id,
            target_player_id=target.player_id,
            private_hint=request.private_hint,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event_to_player(target.player_id, private_event)

        public_event = game_pb2.GameEvent(
            type=game_pb2.HINT_EXCHANGE_REQUESTED,
            message=f"{requester.name} solicitou uma troca de dicas privada com {target.name}.",
            actor_player_id=requester.player_id,
            target_player_id=target.player_id,
            timestamp_unix_ms=now_unix_ms(),
        )
        for pid in [p.player_id for p in self._state.get_players()
                    if p.player_id not in {requester.player_id, target.player_id}]:
            self._state.publish_game_event_to_player(pid, public_event)

        print(f"[GAME] {public_event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    # RespondHintExchange
    def RespondHintExchange(self, request, context):
        success, message, result = self._state.respond_hint_exchange(
            request.responder_player_id, request.requester_player_id,
            request.accepted, request.private_hint,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        if result is None:
            reject_event = game_pb2.GameEvent(
                type=game_pb2.HINT_EXCHANGE_RESPONDED,
                message=message,
                actor_player_id=request.responder_player_id,
                target_player_id=request.requester_player_id,
                accepted=False,
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(reject_event)
            print(f"[GAME] {reject_event.message}")
            return game_pb2.CommandResponse(success=True, message=message)

        self._publish_exchange_result(result)
        return game_pb2.CommandResponse(success=True, message=message)

    def _publish_exchange_result(self, result: ExchangeResult) -> None:
        self._state.publish_game_event_to_player(result.requester.player_id, game_pb2.GameEvent(
            type=game_pb2.EXCHANGE_COMPLETED,
            message=f"Troca com {result.responder.name} concluida. Dica deles: '{result.responder_hint}'",
            actor_player_id=result.responder.player_id,
            target_player_id=result.requester.player_id,
            private_hint=result.responder_hint,
            accepted=True,
            timestamp_unix_ms=now_unix_ms(),
        ))

        self._state.publish_game_event_to_player(result.responder.player_id, game_pb2.GameEvent(
            type=game_pb2.EXCHANGE_COMPLETED,
            message=f"Troca com {result.requester.name} concluida. Dica deles: '{result.requester_hint}'",
            actor_player_id=result.requester.player_id,
            target_player_id=result.responder.player_id,
            private_hint=result.requester_hint,
            accepted=True,
            timestamp_unix_ms=now_unix_ms(),
        ))

        public_event = game_pb2.GameEvent(
            type=game_pb2.HINT_EXCHANGE_OCCURRED,
            message=f"{result.requester.name} e {result.responder.name} trocaram dicas privadas.",
            actor_player_id=result.requester.player_id,
            target_player_id=result.responder.player_id,
            accepted=True,
            timestamp_unix_ms=now_unix_ms(),
        )
        for pid in [p.player_id for p in self._state.get_players()
                    if p.player_id not in {result.requester.player_id, result.responder.player_id}]:
            self._state.publish_game_event_to_player(pid, public_event)

        for spy, caught in result.spy_results:
            scores = self._state.get_scores()
            if caught:
                event = game_pb2.GameEvent(
                    type=game_pb2.SPY_DISCOVERED,
                    message=f"{spy.name} foi pego espiando a troca de {result.requester.name} e {result.responder.name}! -5 pontos.",
                    actor_player_id=spy.player_id,
                    spy_caught=True,
                    scores=self._scores_to_proto(scores),
                    score_delta=-5,
                    timestamp_unix_ms=now_unix_ms(),
                )
                self._state.publish_game_event(event)
                print(f"[GAME] {event.message}")
            else:
                self._state.publish_game_event_to_player(spy.player_id, game_pb2.GameEvent(
                    type=game_pb2.SPY_SUCCESSFUL,
                    message=(
                        f"Espionagem bem-sucedida! +3 pts. "
                        f"{result.requester.name} disse '{result.requester_hint}', "
                        f"{result.responder.name} disse '{result.responder_hint}'."
                    ),
                    actor_player_id=spy.player_id,
                    spy_caught=False,
                    scores=self._scores_to_proto(scores),
                    score_delta=3,
                    private_hint=(
                        f"{result.requester.name}:'{result.requester_hint}' "
                        f"/ {result.responder.name}:'{result.responder_hint}'"
                    ),
                    timestamp_unix_ms=now_unix_ms(),
                ))

    # SpyOnExchange
    def SpyOnExchange(self, request, context):
        success, message = self._state.spy_on_exchange(
            request.spy_player_id, request.player_a_id, request.player_b_id,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        player_a = self._state.get_player(request.player_a_id)
        player_b = self._state.get_player(request.player_b_id)
        names = f"{player_a.name} e {player_b.name}" if player_a and player_b else "dois jogadores"
        spy = self._state.get_player(request.spy_player_id)
        if spy:
            print(f"[GAME] {spy.name} esta espiando {names}.")
        return game_pb2.CommandResponse(success=True, message=message)

    # Publish helpers
    def _publish_turn_started(self, turn) -> None:
        max_turns = self._state.get_max_turns()
        event = game_pb2.GameEvent(
            type=game_pb2.TURN_STARTED,
            message=self._turn_started_message(turn, max_turns),
            actor_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=self._phase_to_proto(turn.phase),
            players=self._players_to_proto(self._state.get_players()),
            hint_cycle=turn.hint_cycle,
            max_hint_cycles=max_turns,
            session_number=turn.session_number,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    @staticmethod
    def _turn_started_message(turn, max_turns: int) -> str:
        prefix = f"Sessao {turn.session_number} · Ciclo {turn.hint_cycle}/{max_turns}"
        if turn.phase == TurnPhase.HINT:
            return f"{prefix}: {turn.player.name} deve dar uma dica."
        return f"{prefix}: turno de {turn.player.name}."

    def _publish_hint_phase_started(self, turn) -> None:
        max_turns = self._state.get_max_turns()
        event = game_pb2.GameEvent(
            type=game_pb2.HINT_PHASE_STARTED,
            message=f"{turn.player.name} deve enviar uma dica publica (ciclo {turn.hint_cycle}/{max_turns}).",
            actor_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=self._phase_to_proto(turn.phase),
            hint_cycle=turn.hint_cycle,
            max_hint_cycles=max_turns,
            session_number=turn.session_number,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    def _publish_guess_phase_started(self, turn, waiting_players) -> None:
        max_turns = self._state.get_max_turns()
        event = game_pb2.GameEvent(
            type=game_pb2.GUESS_PHASE_STARTED,
            message=f"Todos podem tentar adivinhar o personagem de {turn.player.name} ou passar.",
            actor_player_id=turn.player.player_id,
            target_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=game_pb2.POST_HINT_GUESSES,
            players=self._players_to_proto(waiting_players),
            hint_cycle=turn.hint_cycle,
            max_hint_cycles=max_turns,
            session_number=turn.session_number,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    def _publish_round_ended(self, round_end: RoundEndResult) -> None:
        scores = self._state.get_scores()
        players_by_id = {p.player_id: p for p in self._state.get_players()}

        reveals_proto = [
            game_pb2.CharacterReveal(
                player_id=r.player.player_id,
                player_name=r.player.name,
                character_name=r.character.name,
                character_id=r.character.character_id,
            )
            for r in round_end.reveals
        ]

        deltas_proto = [
            game_pb2.PlayerScore(
                player_id=pid,
                player_name=players_by_id[pid].name if pid in players_by_id else pid,
                score=delta,
            )
            for pid, delta in round_end.score_deltas.items()
            if delta != 0
        ]

        round_end_event = game_pb2.GameEvent(
            type=game_pb2.ROUND_ENDED,
            message="Sessao encerrada! Veja os personagens revelados e os pontos ganhos.",
            scores=self._scores_to_proto(scores),
            score_deltas=deltas_proto,
            character_reveals=reveals_proto,
            is_final_session=round_end.is_final,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(round_end_event)
        print("[GAME] Sessao encerrada.")

        if round_end.score_changes:
            summary_parts = []
            for sc in round_end.score_changes:
                name = players_by_id[sc.player_id].name if sc.player_id in players_by_id else sc.player_id
                sign = "+" if sc.points_delta > 0 else ""
                summary_parts.append(f"{name} {sign}{sc.points_delta} ({sc.reason})")
            summary_event = game_pb2.GameEvent(
                type=game_pb2.ROUND_SCORE_SUMMARY,
                message="Resumo de pontuacao: " + "; ".join(summary_parts),
                scores=self._scores_to_proto(scores),
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(summary_event)

        vote_message = (
            "Limite de sessoes atingido. Votem para abrir uma nova partida ou encerrar."
            if round_end.is_final
            else "Votem: continuar com uma nova sessao ou encerrar o jogo?"
        )
        vote_event = game_pb2.GameEvent(
            type=game_pb2.VOTE_STARTED,
            message=vote_message,
            votes_continue=0,
            votes_end=0,
            votes_needed=len(self._state.get_players()) // 2 + 1,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(vote_event)
        print("[GAME] Votacao iniciada.")

    def _publish_new_game_approved(self) -> None:
        owner_id = self._state.get_room_owner_id() or ""
        event = game_pb2.GameEvent(
            type=game_pb2.NEW_GAME_APPROVED,
            message="Maioria decidiu continuar. O dono da sala pode configurar a proxima partida.",
            room_owner_id=owner_id,
            scores=self._scores_to_proto(self._state.get_scores()),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print("[GAME] Nova partida aprovada por votacao.")

    def _publish_game_ended(self, scores: dict) -> None:
        players_by_id = {p.player_id: p for p in self._state.get_players()}
        tiebreak_stats = self._state.get_tiebreak_stats()
        sorted_players = sorted(
            players_by_id.values(),
            key=lambda p: (
                scores.get(p.player_id, 0),
                tiebreak_stats.get(p.player_id, (0, 0))[0],
                tiebreak_stats.get(p.player_id, (0, 0))[1],
                p.name.lower(),
            ),
            reverse=True,
        )

        if sorted_players:
            leader = sorted_players[0]
            leader_key = (
                scores.get(leader.player_id, 0),
                *tiebreak_stats.get(leader.player_id, (0, 0)),
            )
            winners = [
                p.name for p in sorted_players
                if (
                    scores.get(p.player_id, 0),
                    *tiebreak_stats.get(p.player_id, (0, 0)),
                ) == leader_key
            ]
        else:
            leader = None
            leader_key = (0, 0, 0)
            winners = []

        max_score = leader_key[0]
        if len(winners) > 1:
            msg = f"Fim de jogo! Empate entre {', '.join(winners)} com {max_score} pontos!"
        elif leader is None:
            msg = "Fim de jogo! Nenhum vencedor."
        else:
            first_guesses, correct_guesses = tiebreak_stats.get(leader.player_id, (0, 0))
            tied_on_score = sum(1 for p in sorted_players if scores.get(p.player_id, 0) == max_score) > 1
            if tied_on_score:
                msg = (
                    f"Fim de jogo! Vencedor: {leader.name} com {max_score} pontos "
                    f"(desempate: {first_guesses} primeiros acertos, {correct_guesses} acertos no total)!"
                )
            else:
                msg = f"Fim de jogo! Vencedor: {leader.name} com {max_score} pontos!"

        ranking = [
            game_pb2.RankingEntry(
                position=i + 1,
                player_id=p.player_id,
                player_name=p.name,
                score=scores.get(p.player_id, 0),
            )
            for i, p in enumerate(sorted_players)
        ]

        end_event = game_pb2.GameEvent(
            type=game_pb2.GAME_ENDED,
            message=msg,
            scores=self._scores_to_proto(scores),
            ranking=ranking,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(end_event)

        final_ranking_event = game_pb2.GameEvent(
            type=game_pb2.FINAL_RANKING,
            message="Ranking final da partida.",
            scores=self._scores_to_proto(scores),
            ranking=ranking,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(final_ranking_event)
        print(f"[GAME] {msg}")

    def _enqueue_snapshot_for_player(self, player_id: str, q) -> None:
        game_started, category, character, current_turn, players = (
            self._state.get_game_snapshot_for_player(player_id)
        )
        owner_id = self._state.get_room_owner_id() or ""
        session_number = self._state.get_session_number()
        max_rounds = self._state.get_max_rounds()

        if not game_started and not self._state.is_voting_phase():
            return

        if category is not None:
            q.put(game_pb2.GameEvent(
                type=game_pb2.ROUND_STARTED,
                message=f"Sessao {session_number}/{max_rounds} — Categoria: {category.name}.",
                category_id=category.category_id,
                category_name=category.name,
                theme=category.name,
                max_rounds=max_rounds,
                session_number=session_number,
                room_owner_id=owner_id,
                timestamp_unix_ms=now_unix_ms(),
            ))

        if category is not None and character is not None:
            q.put(game_pb2.GameEvent(
                type=game_pb2.CHARACTER_ASSIGNED,
                message="Voce recebeu seu personagem secreto.",
                target_player_id=player_id,
                category_id=category.category_id,
                category_name=category.name,
                character_id=character.character_id,
                object_name=character.name,
                image_path=character.image_path,
                theme=category.name,
                timestamp_unix_ms=now_unix_ms(),
            ))

        if current_turn is not None:
            max_turns = self._state.get_max_turns()
            q.put(game_pb2.GameEvent(
                type=game_pb2.TURN_STARTED,
                message=self._turn_started_message(current_turn, max_turns),
                actor_player_id=current_turn.player.player_id,
                current_turn_player_id=current_turn.player.player_id,
                current_turn_player_name=current_turn.player.name,
                turn_phase=self._phase_to_proto(current_turn.phase),
                players=self._players_to_proto(players),
                hint_cycle=current_turn.hint_cycle,
                max_hint_cycles=max_turns,
                session_number=current_turn.session_number,
                room_owner_id=owner_id,
                timestamp_unix_ms=now_unix_ms(),
            ))

        if self._state.is_voting_phase():
            q.put(game_pb2.GameEvent(
                type=game_pb2.VOTE_STARTED,
                message="Votem: continuar com uma nova sessao ou encerrar o jogo?",
                votes_continue=0, votes_end=0,
                votes_needed=len(players) // 2 + 1,
                timestamp_unix_ms=now_unix_ms(),
            ))

    # Proto helpers
    @staticmethod
    def _phase_to_proto(phase: TurnPhase):
        mapping = {
            TurnPhase.HINT: game_pb2.HINT,
            TurnPhase.POST_HINT_GUESSES: game_pb2.POST_HINT_GUESSES,
        }
        return mapping.get(phase, game_pb2.TURN_PHASE_UNKNOWN)

    @staticmethod
    def _players_to_proto(players):
        return [game_pb2.Player(player_id=p.player_id, name=p.name) for p in players]

    def _scores_to_proto(self, scores):
        players_by_id = {p.player_id: p for p in self._state.get_players()}
        return [
            game_pb2.PlayerScore(player_id=pid, player_name=players_by_id[pid].name, score=s)
            for pid, s in scores.items() if pid in players_by_id
        ]


class ChatService(game_pb2_grpc.ChatServiceServicer):
    def __init__(self, state: GameState) -> None:
        self._state = state

    def SendChatMessage(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            return game_pb2.CommandResponse(success=False, message="Jogador nao encontrado.")

        text = request.text.strip()
        if not text:
            return game_pb2.CommandResponse(success=False, message="Mensagem vazia.")

        event = game_pb2.ChatEvent(
            player_id=player.player_id,
            player_name=player.name,
            text=text,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_chat_event(event)
        print(f"[CHAT] {player.name}: {text}")
        return game_pb2.CommandResponse(success=True, message="Mensagem enviada.")

    def SubscribeToChatEvents(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Jogador nao encontrado.")

        q = self._state.add_chat_subscriber(request.player_id)
        print(f"[STREAM] {player.name} inscrito no chat.")
        context.add_callback(lambda: q.put(None))

        try:
            while context.is_active():
                event = q.get()
                if event is None:
                    break
                yield event
        finally:
            self._state.remove_chat_subscriber(request.player_id)
            print(f"[STREAM] {player.name} saiu do chat.")


def serve() -> None:
    state = GameState()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    game_pb2_grpc.add_GameServiceServicer_to_server(GameService(state), server)
    game_pb2_grpc.add_ChatServiceServicer_to_server(ChatService(state), server)

    address = "[::]:50051"
    server.add_insecure_port(address)
    server.start()
    print(f"Servidor gRPC ouvindo em {address}")
    print("Pressione Ctrl+C para encerrar.")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
