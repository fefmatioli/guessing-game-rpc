from __future__ import annotations

import os
import threading
import tkinter.simpledialog as simpledialog

import customtkinter as ctk
import grpc
from PIL import Image

from grpc_client import GameRpcClient, game_pb2


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GuessingGameApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Guessing Game RPC")
        self.geometry("1080x680")
        self.minsize(920, 580)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.rpc_client: GameRpcClient | None = None
        self.stream_threads_started = False
        self.category_name = "Aguardando inicio"
        self.character_image_path = ""
        self.character_image = None
        self.current_turn = "Aguardando inicio"
        self.current_turn_player_id = ""
        self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
        self.players_by_name: dict[str, str] = {}
        self.game_started = False
        self.choosing_guess = False
        self.responded_this_opportunity = False

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_login_bar()
        self._build_player_panel()
        self._build_events_panel()
        self._build_chat_panel()
        self._set_connected_state(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_login_bar(self) -> None:
        self.login_frame = ctk.CTkFrame(self, corner_radius=8)
        self.login_frame.grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 8)
        )
        self.login_frame.grid_columnconfigure(1, weight=1)

        self.name_label = ctk.CTkLabel(self.login_frame, text="Jogador")
        self.name_label.grid(row=0, column=0, padx=(12, 8), pady=10)

        self.name_entry = ctk.CTkEntry(self.login_frame, placeholder_text="Seu nome")
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=10)
        self.name_entry.bind("<Return>", lambda _event: self.join_game())

        self.join_button = ctk.CTkButton(
            self.login_frame, text="Entrar", width=110, command=self.join_game
        )
        self.join_button.grid(row=0, column=2, padx=(8, 12), pady=10)

    def _build_player_panel(self) -> None:
        self.player_frame = ctk.CTkFrame(self, corner_radius=8)
        self.player_frame.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=8)
        self.player_frame.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(
            self.player_frame,
            text="Estado do jogador",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        self.status_label = ctk.CTkLabel(self.player_frame, text="Desconectado")
        self.status_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        self.category_label = ctk.CTkLabel(
            self.player_frame,
            text="Categoria: aguardando",
            anchor="w",
            justify="left",
            wraplength=210,
        )
        self.category_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))

        self.character_label = ctk.CTkLabel(
            self.player_frame,
            text="Imagem: aguardando",
            width=210,
            height=150,
            anchor="center",
        )
        self.character_label.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))

        self.turn_label = ctk.CTkLabel(
            self.player_frame,
            text="Turno: aguardando",
            anchor="w",
            justify="left",
            wraplength=210,
        )
        self.turn_label.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 12))

        self.start_button = ctk.CTkButton(
            self.player_frame, text="Iniciar jogo", command=self.start_game
        )
        self.start_button.grid(row=5, column=0, sticky="ew", padx=14, pady=(4, 8))

        self.action_frame = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        self.action_frame.grid(row=6, column=0, sticky="ew", padx=14, pady=(18, 8))
        self.action_frame.grid_columnconfigure(0, weight=1)

        self.action_label = ctk.CTkLabel(
            self.action_frame,
            text="Acoes: entre na partida",
            anchor="w",
            justify="left",
            wraplength=210,
        )
        self.action_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.target_var = ctk.StringVar(value="Selecione jogador")
        self.make_guess_button = ctk.CTkButton(
            self.action_frame, text="Fazer palpite", command=self.start_guess_choice
        )
        self.make_guess_button.grid(row=1, column=0, sticky="ew", pady=6)

        self.no_guess_button = ctk.CTkButton(
            self.action_frame,
            text="Nao fazer palpite",
            command=self.pass_guess_opportunity,
        )
        self.no_guess_button.grid(row=2, column=0, sticky="ew", pady=6)

        self.target_menu = ctk.CTkOptionMenu(
            self.action_frame,
            variable=self.target_var,
            values=["Selecione jogador"],
        )
        self.target_menu.grid(row=1, column=0, sticky="ew", pady=6)

        self.guess_entry = ctk.CTkEntry(
            self.action_frame,
            placeholder_text="Palpite",
        )
        self.guess_entry.grid(row=2, column=0, sticky="ew", pady=6)

        self.guess_button = ctk.CTkButton(
            self.action_frame, text="Enviar palpite", command=self.submit_guess
        )
        self.guess_button.grid(row=3, column=0, sticky="ew", pady=6)

        self.pass_button = ctk.CTkButton(
            self.action_frame, text="Passar", command=self.pass_guess_opportunity
        )
        self.pass_button.grid(row=4, column=0, sticky="ew", pady=6)

        self.hint_button = ctk.CTkButton(
            self.action_frame, text="Enviar dica publica", command=self.send_public_hint
        )
        self.hint_button.grid(row=5, column=0, sticky="ew", pady=6)

        self.exchange_button = ctk.CTkButton(
            self.action_frame,
            text="Solicitar troca privada",
            command=self.request_hint_exchange,
        )
        self.exchange_button.grid(row=9, column=0, sticky="ew", pady=6)

        self.spy_button = ctk.CTkButton(
            self.action_frame, text="Tentar espionar", command=self.spy_on_exchange
        )
        self.spy_button.grid(row=10, column=0, sticky="ew", pady=6)

        ctk.CTkLabel(
            self.player_frame,
            text="Jogadores conectados",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=7, column=0, sticky="w", padx=14, pady=(18, 6))

        self.players_box = ctk.CTkTextbox(self.player_frame, height=120)
        self.players_box.grid(row=8, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.players_box.configure(state="disabled")

    def _build_events_panel(self) -> None:
        self.events_frame = ctk.CTkFrame(self, corner_radius=8)
        self.events_frame.grid(row=1, column=1, sticky="nsew", padx=6, pady=8)
        self.events_frame.grid_rowconfigure(1, weight=1)
        self.events_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.events_frame,
            text="Eventos do jogo",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        self.events_box = ctk.CTkTextbox(self.events_frame)
        self.events_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.events_box.configure(state="disabled")

    def _build_chat_panel(self) -> None:
        self.chat_frame = ctk.CTkFrame(self, corner_radius=8)
        self.chat_frame.grid(row=1, column=2, sticky="nsew", padx=(6, 12), pady=8)
        self.chat_frame.grid_rowconfigure(1, weight=1)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.chat_frame,
            text="Chat",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 8))

        self.chat_box = ctk.CTkTextbox(self.chat_frame)
        self.chat_box.grid(
            row=1, column=0, columnspan=2, sticky="nsew", padx=14, pady=(0, 8)
        )
        self.chat_box.configure(state="disabled")

        self.chat_entry = ctk.CTkEntry(
            self.chat_frame,
            placeholder_text="Mensagem de chat",
        )
        self.chat_entry.grid(row=2, column=0, sticky="ew", padx=(14, 8), pady=(0, 14))
        self.chat_entry.bind("<Return>", lambda _event: self.send_chat_message())

        self.chat_button = ctk.CTkButton(
            self.chat_frame, text="Enviar", width=90, command=self.send_chat_message
        )
        self.chat_button.grid(row=2, column=1, sticky="e", padx=(0, 14), pady=(0, 14))

    def join_game(self) -> None:
        player_name = self.name_entry.get().strip()
        if not player_name:
            self._append_event("Informe um nome antes de entrar.")
            return

        try:
            self.rpc_client = GameRpcClient()
            response = self.rpc_client.join_game(player_name)
        except grpc.RpcError as error:
            self._append_event(f"Falha ao conectar: {error.details()}")
            return

        if not response.success:
            self._append_event(f"Falha ao entrar: {response.message}")
            return

        self._set_connected_state(True)
        self.status_label.configure(
            text=f"{player_name} conectado\nID: {self.rpc_client.player_id[:8]}"
        )
        self._refresh_players()
        self._update_action_state()
        self._append_event(response.message)
        self._start_stream_threads()

    def _start_stream_threads(self) -> None:
        if self.stream_threads_started or self.rpc_client is None:
            return

        self.stream_threads_started = True
        threading.Thread(target=self._listen_game_events, daemon=True).start()
        threading.Thread(target=self._listen_chat_events, daemon=True).start()

    def _listen_game_events(self) -> None:
        try:
            for event in self.rpc_client.subscribe_to_game_events():
                self.after(0, self._handle_game_event, event)
        except grpc.RpcError as error:
            self.after(
                0,
                self._append_event,
                f"Stream de jogo encerrado: {error.details()}",
            )

    def _listen_chat_events(self) -> None:
        try:
            for event in self.rpc_client.subscribe_to_chat_events():
                text = f"{event.player_name}: {event.text}"
                self.after(0, self._append_chat, text)
        except grpc.RpcError as error:
            self.after(
                0,
                self._append_chat,
                f"Stream de chat encerrado: {error.details()}",
            )

    def start_game(self) -> None:
        self._run_command("StartGame", lambda: self.rpc_client.start_game())

    def send_public_hint(self) -> None:
        hint = self._ask_text("Dica publica", "Digite uma dica curta:")
        if hint:
            self._run_command(
                "SendPublicHint",
                lambda: self.rpc_client.send_public_hint(hint),
            )

    def submit_guess(self) -> None:
        owner_id = self._selected_guess_owner_id()
        if not owner_id:
            self._append_event("Selecione um jogador para o palpite.")
            return
        guess = self.guess_entry.get().strip()
        if not guess:
            self._append_event("Digite o palpite antes de enviar.")
            return
        self.guess_entry.delete(0, "end")
        sent = self._run_command(
            "SubmitGuess",
            lambda: self.rpc_client.submit_guess(owner_id, guess),
        )
        if sent:
            self.responded_this_opportunity = True
            self.choosing_guess = False
            self._update_action_state()

    def pass_guess_opportunity(self) -> None:
        sent = self._run_command(
            "PassGuessOpportunity",
            lambda: self.rpc_client.pass_guess_opportunity(),
        )
        if sent:
            self.responded_this_opportunity = True
            self.choosing_guess = False
            self._update_action_state()

    def start_guess_choice(self) -> None:
        self.choosing_guess = True
        self._update_action_state()

    def request_hint_exchange(self) -> None:
        target_id = self._ask_text("Troca privada", "ID do jogador alvo:")
        if not target_id:
            return
        private_hint = self._ask_text("Troca privada", "Sua dica privada:")
        if private_hint:
            self._run_command(
                "RequestHintExchange",
                lambda: self.rpc_client.request_hint_exchange(target_id, private_hint),
            )

    def spy_on_exchange(self) -> None:
        player_a_id = self._ask_text("Espionagem", "ID do primeiro jogador:")
        if not player_a_id:
            return
        player_b_id = self._ask_text("Espionagem", "ID do segundo jogador:")
        if player_b_id:
            self._run_command(
                "SpyOnExchange",
                lambda: self.rpc_client.spy_on_exchange(player_a_id, player_b_id),
            )

    def send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return

        self.chat_entry.delete(0, "end")
        self._run_command(
            "SendChatMessage",
            lambda: self.rpc_client.send_chat_message(text),
            show_success=False,
        )

    def _run_command(self, label: str, command, show_success: bool = True) -> None:
        if self.rpc_client is None:
            self._append_event("Entre na partida antes de enviar comandos.")
            return False

        try:
            response = command()
        except grpc.RpcError as error:
            self._append_event(f"{label}: erro RPC: {error.details()}")
            return False

        if response.success:
            if show_success:
                self._append_event(f"{label}: {response.message}")
            return True
        else:
            self._append_event(f"{label}: {response.message}")
            return False

    def _ask_text(self, title: str, prompt: str) -> str:
        value = simpledialog.askstring(title, prompt, parent=self)
        return value.strip() if value else ""

    def _handle_game_event(self, event) -> None:
        if event.players:
            self._set_players(list(event.players))

        if event.type == game_pb2.GAME_STARTED:
            self.game_started = True
        if event.type == game_pb2.ROUND_STARTED:
            self.game_started = True
            self.category_name = event.category_name
            self.category_label.configure(text=f"Categoria: {event.category_name}")
        if event.type == game_pb2.CHARACTER_ASSIGNED:
            self.game_started = True
            self.character_image_path = event.image_path
            self._load_character_image(event.image_path)
        elif event.type in {
            game_pb2.TURN_STARTED,
            game_pb2.HINT_PHASE_STARTED,
            game_pb2.GUESS_PHASE_STARTED,
        }:
            self.choosing_guess = False
            self.responded_this_opportunity = False
            self.game_started = True
            self.current_turn = event.current_turn_player_name
            self.current_turn_player_id = event.current_turn_player_id
            self.turn_phase = event.turn_phase
            is_my_turn = (
                self.rpc_client is not None
                and event.current_turn_player_id == self.rpc_client.player_id
            )
            suffix = " (sua vez)" if is_my_turn else ""
            self.turn_label.configure(
                text=f"Turno: {event.current_turn_player_name}{suffix}"
            )
        self._update_action_state()
        self._append_event(event.message)
        if event.scores:
            self._append_event(self._format_scores(event.scores))

    def _append_event(self, text: str) -> None:
        self._append_to_textbox(self.events_box, text)

    def _append_chat(self, text: str) -> None:
        self._append_to_textbox(self.chat_box, text)

    def _append_to_textbox(self, textbox: ctk.CTkTextbox, text: str) -> None:
        textbox.configure(state="normal")
        textbox.insert("end", f"{text}\n")
        textbox.see("end")
        textbox.configure(state="disabled")

    def _refresh_players(self) -> None:
        if self.rpc_client is None:
            return

        self._set_players(self.rpc_client.players)

    def _set_players(self, players) -> None:
        if self.rpc_client is None:
            return

        self.rpc_client.players = list(players)
        self.players_by_name = {
            player.name: player.player_id
            for player in self.rpc_client.players
        }
        lines = [f"{player.name} ({player.player_id[:8]})" for player in players]
        self.players_box.configure(state="normal")
        self.players_box.delete("1.0", "end")
        self.players_box.insert("end", "\n".join(lines))
        self.players_box.configure(state="disabled")
        self._refresh_target_menu()

    def _set_connected_state(self, connected: bool) -> None:
        command_state = "normal" if connected else "disabled"
        login_state = "disabled" if connected else "normal"

        self.name_entry.configure(state=login_state)
        self.join_button.configure(state=login_state)
        self.chat_entry.configure(state=command_state)
        self.chat_button.configure(state=command_state)
        self._update_action_state()

    def _refresh_target_menu(self) -> None:
        if self.rpc_client is None:
            values = ["Selecione jogador"]
        else:
            values = [
                player.name
                for player in self.rpc_client.players
                if player.player_id != self.rpc_client.player_id
            ] or ["Selecione jogador"]

        self.target_menu.configure(values=values)
        if self.target_var.get() not in values:
            self.target_var.set(values[0])

    def _selected_guess_owner_id(self) -> str:
        if self.turn_phase == game_pb2.POST_HINT_GUESSES:
            return self.current_turn_player_id

        selected_name = self.target_var.get()
        return self.players_by_name.get(selected_name, "")

    def _update_action_state(self) -> None:
        connected = self.rpc_client is not None and bool(self.rpc_client.player_id)
        self._hide_action_widgets()

        if not connected:
            self.start_button.configure(state="disabled")
            self.action_label.configure(text="Acoes: entre na partida.")
            return

        if not self.game_started:
            self.start_button.grid()
            self.start_button.configure(state="normal")
            self.action_label.configure(
                text="Acoes: aguarde os jogadores e inicie a partida."
            )
            return

        self.start_button.configure(state="disabled")
        self.start_button.grid_remove()

        is_my_turn = self.current_turn_player_id == self.rpc_client.player_id
        can_pre_hint_guess = self.turn_phase == game_pb2.PRE_HINT_GUESS and is_my_turn
        can_hint = self.turn_phase == game_pb2.HINT and is_my_turn
        can_post_hint_guess = (
            self.turn_phase == game_pb2.POST_HINT_GUESSES and not is_my_turn
        )
        can_choose_guess = (
            can_pre_hint_guess or can_post_hint_guess
        ) and not self.responded_this_opportunity

        if can_pre_hint_guess and not self.choosing_guess:
            self.action_label.configure(
                text="Acao: voce pode fazer um palpite antes da dica."
            )
            self._show_action_widget(self.make_guess_button, row=1)
            self._show_action_widget(self.no_guess_button, row=2)
        elif can_pre_hint_guess and self.choosing_guess:
            self.action_label.configure(
                text="Acao: escolha um jogador e envie um palpite."
            )
            self._show_action_widget(self.target_menu, row=1)
            self._show_action_widget(self.guess_entry, row=2)
            self._show_action_widget(self.guess_button, row=3)
            self._show_action_widget(self.pass_button, row=4)
        elif can_hint:
            self.action_label.configure(text="Acao: envie sua dica publica.")
            self._show_action_widget(self.hint_button, row=1)
        elif can_post_hint_guess and can_choose_guess and not self.choosing_guess:
            self.action_label.configure(
                text=f"Acao: quer tentar adivinhar o personagem de {self.current_turn}?"
            )
            self._show_action_widget(self.make_guess_button, row=1)
            self._show_action_widget(self.no_guess_button, row=2)
        elif can_post_hint_guess and can_choose_guess and self.choosing_guess:
            self.action_label.configure(
                text=f"Acao: digite seu palpite para {self.current_turn}."
            )
            self._show_action_widget(self.guess_entry, row=1)
            self._show_action_widget(self.guess_button, row=2)
            self._show_action_widget(self.pass_button, row=3)
        elif self.responded_this_opportunity:
            self.action_label.configure(
                text="Acao: voce ja respondeu esta oportunidade."
            )
        else:
            self.action_label.configure(text="Acao: aguarde os outros jogadores.")

    def _hide_action_widgets(self) -> None:
        for widget in [
            self.make_guess_button,
            self.no_guess_button,
            self.target_menu,
            self.guess_entry,
            self.guess_button,
            self.pass_button,
            self.hint_button,
            self.exchange_button,
            self.spy_button,
        ]:
            try:
                widget.configure(state="disabled")
            except ValueError:
                pass
            widget.grid_remove()

    @staticmethod
    def _show_action_widget(widget, row: int) -> None:
        widget.grid(row=row, column=0, sticky="ew", pady=6)
        try:
            widget.configure(state="normal")
        except ValueError:
            pass

    @staticmethod
    def _format_scores(scores) -> str:
        ordered_scores = sorted(scores, key=lambda item: item.score, reverse=True)
        score_text = ", ".join(
            f"{item.player_name}: {item.score}" for item in ordered_scores
        )
        return f"Placar: {score_text}"

    def _load_character_image(self, image_path: str) -> None:
        absolute_path = os.path.join(PROJECT_ROOT, image_path)
        if not os.path.exists(absolute_path):
            self.character_image = None
            self.character_label.configure(
                image=None,
                text=f"Imagem nao encontrada:\n{image_path}",
            )
            return

        image = Image.open(absolute_path)
        self.character_image = ctk.CTkImage(
            light_image=image,
            dark_image=image,
            size=(180, 150),
        )
        self.character_label.configure(image=self.character_image, text="")

    def _on_close(self) -> None:
        if self.rpc_client is not None:
            self.rpc_client.close()
        self.destroy()


if __name__ == "__main__":
    app = GuessingGameApp()
    app.mainloop()
