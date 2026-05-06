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
from game_state import GameState, TurnPhase, now_unix_ms  # noqa: E402


class GameService(game_pb2_grpc.GameServiceServicer):
    def __init__(self, state: GameState) -> None:
        self._state = state

    def JoinGame(self, request, context):
        player, players, created = self._state.add_player(request.player_name)

        if created:
            event = game_pb2.GameEvent(
                type=game_pb2.PLAYER_JOINED,
                message=f"{player.name} entrou na partida.",
                actor_player_id=player.player_id,
                players=self._players_to_proto(players),
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(event)
            print(f"[GAME] {event.message}")

        return game_pb2.JoinGameResponse(
            success=True,
            message="Entrada realizada com sucesso."
            if created
            else "Nome ja estava conectado; reutilizando jogador.",
            player_id=player.player_id,
            players=[
                game_pb2.Player(player_id=item.player_id, name=item.name)
                for item in players
            ],
        )

    def SubscribeToGameEvents(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Jogador nao encontrado.")

        subscriber_queue = self._state.add_game_subscriber(request.player_id)
        print(f"[STREAM] {player.name} inscrito nos eventos de jogo.")
        context.add_callback(lambda: subscriber_queue.put(None))
        self._enqueue_snapshot_for_player(request.player_id, subscriber_queue)

        try:
            while context.is_active():
                event = subscriber_queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._state.remove_game_subscriber(request.player_id)
            print(f"[STREAM] {player.name} saiu dos eventos de jogo.")

    def StartGame(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            return game_pb2.CommandResponse(
                success=False,
                message="Jogador nao encontrado.",
            )

        success, message, category, assignments, current_turn = self._state.start_game()
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        started_event = game_pb2.GameEvent(
            type=game_pb2.GAME_STARTED,
            message=f"{player.name} iniciou a partida.",
            actor_player_id=player.player_id,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(started_event)
        round_event = game_pb2.GameEvent(
            type=game_pb2.ROUND_STARTED,
            message=f"Categoria da rodada: {category.name}.",
            category_id=category.category_id,
            category_name=category.name,
            theme=category.name,
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
                image_path=assignment.character.image_path,
                theme=category.name,
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event_to_player(
                assignment.player.player_id,
                private_event,
            )

        if current_turn is not None:
            if current_turn.phase == TurnPhase.HINT:
                self._publish_hint_phase_started(current_turn)
            else:
                self._publish_turn_started(current_turn)

        print(f"[GAME] {started_event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    def SendPublicHint(self, request, context):
        success, message, actor, waiting_players, current_turn = self._state.register_public_hint(
            request.player_id,
            request.hint,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        hint = request.hint.strip()
        hint_event = game_pb2.GameEvent(
            type=game_pb2.PUBLIC_HINT_SENT,
            message=f"{actor.name} deu uma dica publica: {hint}",
            actor_player_id=actor.player_id,
            target_player_id=actor.player_id,
            public_hint=hint,
            current_turn_player_id=actor.player_id,
            current_turn_player_name=actor.name,
            turn_phase=game_pb2.POST_HINT_GUESSES,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(hint_event)

        if waiting_players and current_turn is not None:
            self._publish_guess_phase_started(current_turn, waiting_players)
        elif current_turn is not None:
            if current_turn.phase == TurnPhase.HINT:
                self._publish_hint_phase_started(current_turn)
            else:
                self._publish_turn_started(current_turn)

        print(f"[GAME] {hint_event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    def SubmitGuess(self, request, context):
        success, message, result = self._state.submit_guess(
            request.guesser_player_id,
            request.owner_player_id,
            request.guess,
        )
        if not success:
            return game_pb2.CommandResponse(success=False, message=message)

        event = game_pb2.GameEvent(
            type=game_pb2.GUESS_VALIDATED,
            message=(
                f"{result.guesser.name} tentou adivinhar o personagem de "
                f"{result.owner.name}: {result.guess}. "
                f"Resultado: {'correto' if result.accepted else 'incorreto'}."
            ),
            actor_player_id=result.guesser.player_id,
            target_player_id=result.owner.player_id,
            guess_id=result.guess_id,
            guess_text=result.guess,
            guesser_player_name=result.guesser.name,
            owner_player_name=result.owner.name,
            accepted=result.accepted,
            scores=self._scores_to_proto(result.scores),
            current_turn_player_id=result.owner.player_id,
            current_turn_player_name=result.owner.name,
            turn_phase=game_pb2.TURN_PHASE_UNKNOWN,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)

        if result.accepted:
            score_event = game_pb2.GameEvent(
                type=game_pb2.SCORE_UPDATED,
                message=f"{result.guesser.name} ganhou 10 pontos.",
                actor_player_id=result.guesser.player_id,
                scores=self._scores_to_proto(result.scores),
                timestamp_unix_ms=now_unix_ms(),
            )
            self._state.publish_game_event(score_event)

        if result.next_turn is not None:
            if result.next_turn.phase == TurnPhase.HINT:
                self._publish_hint_phase_started(result.next_turn)
            else:
                self._publish_turn_started(result.next_turn)

        print(f"[GAME] {event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    def ValidateGuess(self, request, context):
        return game_pb2.CommandResponse(
            success=False,
            message="A validacao e automatica pelo servidor em SubmitGuess.",
        )

    def PassGuessOpportunity(self, request, context):
        success, message, player, next_turn = self._state.pass_guess_opportunity(
            request.player_id,
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

        if next_turn is not None:
            if next_turn.phase == TurnPhase.HINT:
                self._publish_hint_phase_started(next_turn)
            else:
                self._publish_turn_started(next_turn)

        print(f"[GAME] {event.message}")
        return game_pb2.CommandResponse(success=True, message=message)

    def RequestHintExchange(self, request, context):
        return self._not_implemented_yet("RequestHintExchange")

    def RespondHintExchange(self, request, context):
        return self._not_implemented_yet("RespondHintExchange")

    def SpyOnExchange(self, request, context):
        return self._not_implemented_yet("SpyOnExchange")

    @staticmethod
    def _not_implemented_yet(method_name: str):
        return game_pb2.CommandResponse(
            success=False,
            message=f"{method_name} sera implementado na proxima etapa.",
        )

    def _publish_turn_started(self, turn) -> None:
        event = game_pb2.GameEvent(
            type=game_pb2.TURN_STARTED,
            message=self._turn_started_message(turn),
            actor_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=self._phase_to_proto(turn.phase),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    @staticmethod
    def _turn_started_message(turn) -> str:
        if turn.phase == TurnPhase.PRE_HINT_GUESS:
            return (
                f"Rodada {turn.round_number}: turno de {turn.player.name}. "
                "Ele pode fazer um palpite ou seguir para a dica."
            )
        if turn.phase == TurnPhase.HINT:
            return f"Rodada {turn.round_number}: {turn.player.name} deve dar uma dica."
        return f"Rodada {turn.round_number}: turno de {turn.player.name}."

    def _publish_hint_phase_started(self, turn) -> None:
        event = game_pb2.GameEvent(
            type=game_pb2.HINT_PHASE_STARTED,
            message=f"{turn.player.name} deve enviar uma dica publica.",
            actor_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=self._phase_to_proto(turn.phase),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    def _publish_guess_phase_started(self, turn, waiting_players) -> None:
        event = game_pb2.GameEvent(
            type=game_pb2.GUESS_PHASE_STARTED,
            message=(
                f"Todos podem tentar adivinhar o personagem de {turn.player.name} "
                "ou passar."
            ),
            actor_player_id=turn.player.player_id,
            target_player_id=turn.player.player_id,
            current_turn_player_id=turn.player.player_id,
            current_turn_player_name=turn.player.name,
            turn_phase=game_pb2.POST_HINT_GUESSES,
            players=self._players_to_proto(waiting_players),
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_game_event(event)
        print(f"[GAME] {event.message}")

    def _enqueue_snapshot_for_player(self, player_id: str, subscriber_queue) -> None:
        game_started, category, character, current_turn, players = (
            self._state.get_game_snapshot_for_player(player_id)
        )
        if not game_started:
            return

        if category is not None:
            subscriber_queue.put(
                game_pb2.GameEvent(
                    type=game_pb2.ROUND_STARTED,
                    message=f"Categoria da rodada: {category.name}.",
                    category_id=category.category_id,
                    category_name=category.name,
                    theme=category.name,
                    timestamp_unix_ms=now_unix_ms(),
                )
            )

        if category is not None and character is not None:
            subscriber_queue.put(
                game_pb2.GameEvent(
                    type=game_pb2.CHARACTER_ASSIGNED,
                    message="Voce recebeu seu personagem secreto.",
                    target_player_id=player_id,
                    category_id=category.category_id,
                    category_name=category.name,
                    character_id=character.character_id,
                    image_path=character.image_path,
                    theme=category.name,
                    timestamp_unix_ms=now_unix_ms(),
                )
            )

        if current_turn is not None:
            subscriber_queue.put(
                game_pb2.GameEvent(
                    type=game_pb2.TURN_STARTED,
                    message=(
                        f"Rodada {current_turn.round_number}: "
                        f"turno de {current_turn.player.name}."
                    ),
                    actor_player_id=current_turn.player.player_id,
                    current_turn_player_id=current_turn.player.player_id,
                    current_turn_player_name=current_turn.player.name,
                    turn_phase=self._phase_to_proto(current_turn.phase),
                    players=self._players_to_proto(players),
                    timestamp_unix_ms=now_unix_ms(),
                )
            )

    @staticmethod
    def _phase_to_proto(phase: TurnPhase):
        if phase == TurnPhase.PRE_HINT_GUESS:
            return game_pb2.PRE_HINT_GUESS
        if phase == TurnPhase.HINT:
            return game_pb2.HINT
        if phase == TurnPhase.POST_HINT_GUESSES:
            return game_pb2.POST_HINT_GUESSES
        return game_pb2.TURN_PHASE_UNKNOWN

    @staticmethod
    def _players_to_proto(players):
        return [
            game_pb2.Player(player_id=player.player_id, name=player.name)
            for player in players
        ]

    def _scores_to_proto(self, scores):
        players_by_id = {
            player.player_id: player
            for player in self._state.get_players()
        }
        return [
            game_pb2.PlayerScore(
                player_id=player_id,
                player_name=players_by_id[player_id].name,
                score=score,
            )
            for player_id, score in scores.items()
            if player_id in players_by_id
        ]


class ChatService(game_pb2_grpc.ChatServiceServicer):
    def __init__(self, state: GameState) -> None:
        self._state = state

    def SendChatMessage(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            return game_pb2.CommandResponse(
                success=False,
                message="Jogador nao encontrado.",
            )

        text = request.text.strip()
        if not text:
            return game_pb2.CommandResponse(
                success=False,
                message="Mensagem vazia.",
            )

        event = game_pb2.ChatEvent(
            player_id=player.player_id,
            player_name=player.name,
            text=text,
            timestamp_unix_ms=now_unix_ms(),
        )
        self._state.publish_chat_event(event)
        print(f"[CHAT] {player.name}: {text}")

        return game_pb2.CommandResponse(
            success=True,
            message="Mensagem enviada.",
        )

    def SubscribeToChatEvents(self, request, context):
        player = self._state.get_player(request.player_id)
        if player is None:
            context.abort(grpc.StatusCode.NOT_FOUND, "Jogador nao encontrado.")

        subscriber_queue = self._state.add_chat_subscriber(request.player_id)
        print(f"[STREAM] {player.name} inscrito no chat.")
        context.add_callback(lambda: subscriber_queue.put(None))

        try:
            while context.is_active():
                event = subscriber_queue.get()
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
