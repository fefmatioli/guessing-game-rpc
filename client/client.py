from __future__ import annotations

import os
import sys
import threading

import grpc

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from generated import game_pb2  # noqa: E402
from generated import game_pb2_grpc  # noqa: E402


def listen_game_events(game_stub, player_id: str) -> None:
    try:
        events = game_stub.SubscribeToGameEvents(
            game_pb2.SubscribeRequest(player_id=player_id)
        )
        for event in events:
            print(f"\n[JOGO] {event.message}")
            print("> ", end="", flush=True)
    except grpc.RpcError as error:
        print(f"\n[JOGO] stream encerrado: {error.details()}")


def listen_chat_events(chat_stub, player_id: str) -> None:
    try:
        events = chat_stub.SubscribeToChatEvents(
            game_pb2.SubscribeRequest(player_id=player_id)
        )
        for event in events:
            print(f"\n[CHAT] {event.player_name}: {event.text}")
            print("> ", end="", flush=True)
    except grpc.RpcError as error:
        print(f"\n[CHAT] stream encerrado: {error.details()}")


def main() -> None:
    print("=== Guessing Game RPC ===")
    player_name = input("Nome do jogador: ").strip()

    channel = grpc.insecure_channel("localhost:50051")
    game_stub = game_pb2_grpc.GameServiceStub(channel)
    chat_stub = game_pb2_grpc.ChatServiceStub(channel)

    response = game_stub.JoinGame(game_pb2.JoinGameRequest(player_name=player_name))
    if not response.success:
        print(f"Falha ao entrar: {response.message}")
        return

    player_id = response.player_id
    print(response.message)
    print("Jogadores na partida:")
    for player in response.players:
        print(f"- {player.name}")

    game_thread = threading.Thread(
        target=listen_game_events,
        args=(game_stub, player_id),
        daemon=True,
    )
    chat_thread = threading.Thread(
        target=listen_chat_events,
        args=(chat_stub, player_id),
        daemon=True,
    )
    game_thread.start()
    chat_thread.start()

    print("\nDigite mensagens de chat. Use /sair para encerrar.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando cliente.")
            break

        if text.lower() in {"/sair", "/exit", "/quit"}:
            print("Encerrando cliente.")
            break

        if not text:
            continue

        response = chat_stub.SendChatMessage(
            game_pb2.ChatMessageRequest(player_id=player_id, text=text)
        )
        if not response.success:
            print(f"[ERRO] {response.message}")

    channel.close()


if __name__ == "__main__":
    main()
