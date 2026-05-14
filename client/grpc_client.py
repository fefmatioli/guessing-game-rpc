from __future__ import annotations

import os
import sys

import grpc

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
GENERATED_DIR = os.path.join(PROJECT_ROOT, "generated")
sys.path.insert(0, GENERATED_DIR)

import game_pb2  # noqa: E402
import game_pb2_grpc  # noqa: E402


class GameRpcClient:
    """Camada fina entre a interface grafica e os stubs gRPC."""

    def __init__(self, server_address: str = "localhost:50051") -> None:
        self._channel = grpc.insecure_channel(server_address)
        self.game = game_pb2_grpc.GameServiceStub(self._channel)
        self.chat = game_pb2_grpc.ChatServiceStub(self._channel)
        self.player_id = ""
        self.player_name = ""
        self.room_owner_id = ""
        self.players: list[game_pb2.Player] = []

    def join_game(self, player_name: str):
        response = self.game.JoinGame(game_pb2.JoinGameRequest(player_name=player_name))
        if response.success:
            self.player_id = response.player_id
            self.player_name = player_name.strip()
            self.players = list(response.players)
            self.room_owner_id = response.room_owner_id
        return response

    def subscribe_to_game_events(self):
        return self.game.SubscribeToGameEvents(
            game_pb2.SubscribeRequest(player_id=self.player_id)
        )

    def subscribe_to_chat_events(self):
        return self.chat.SubscribeToChatEvents(
            game_pb2.SubscribeRequest(player_id=self.player_id)
        )

    def send_chat_message(self, text: str):
        return self.chat.SendChatMessage(
            game_pb2.ChatMessageRequest(player_id=self.player_id, text=text)
        )

    def start_game(self, max_rounds: int = 3):
        return self.game.StartGame(
            game_pb2.StartGameRequest(
                player_id=self.player_id,
                max_rounds=max_rounds,
            )
        )

    def validate_guess(self, guess_id: str, accepted: bool):
        return self.game.ValidateGuess(
            game_pb2.ValidateGuessRequest(
                owner_player_id=self.player_id,
                guess_id=guess_id,
                accepted=accepted,
            )
        )

    def send_public_hint(self, hint: str):
        return self.game.SendPublicHint(
            game_pb2.SendPublicHintRequest(player_id=self.player_id, hint=hint)
        )

    def submit_guess(self, owner_player_id: str, guess: str):
        return self.game.SubmitGuess(
            game_pb2.SubmitGuessRequest(
                guesser_player_id=self.player_id,
                owner_player_id=owner_player_id,
                guess=guess,
            )
        )

    def pass_guess_opportunity(self):
        return self.game.PassGuessOpportunity(
            game_pb2.PassGuessOpportunityRequest(player_id=self.player_id)
        )

    def vote_for_next_round(self, continue_playing: bool):
        return self.game.VoteForNextRound(
            game_pb2.VoteForNextRoundRequest(
                player_id=self.player_id,
                continue_playing=continue_playing,
            )
        )

    def request_hint_exchange(self, target_player_id: str, private_hint: str):
        return self.game.RequestHintExchange(
            game_pb2.RequestHintExchangeRequest(
                requester_player_id=self.player_id,
                target_player_id=target_player_id,
                private_hint=private_hint,
            )
        )

    def respond_hint_exchange(self, requester_player_id: str, accepted: bool, private_hint: str = ""):
        return self.game.RespondHintExchange(
            game_pb2.RespondHintExchangeRequest(
                responder_player_id=self.player_id,
                requester_player_id=requester_player_id,
                accepted=accepted,
                private_hint=private_hint,
            )
        )

    def spy_on_exchange(self, player_a_id: str, player_b_id: str):
        return self.game.SpyOnExchange(
            game_pb2.SpyOnExchangeRequest(
                spy_player_id=self.player_id,
                player_a_id=player_a_id,
                player_b_id=player_b_id,
            )
        )

    def close(self) -> None:
        self._channel.close()
