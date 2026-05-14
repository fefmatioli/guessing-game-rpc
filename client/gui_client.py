from __future__ import annotations

import os
import threading
import tkinter.simpledialog as simpledialog

import customtkinter as ctk
import grpc
from PIL import Image, ImageDraw

from grpc_client import GameRpcClient, game_pb2


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLORS = {
    "bg":            "#1a1b1e",
    "surface":       "#25262b",
    "surface_alt":   "#2c2d33",
    "border":        "#373a40",
    "accent":        "#5c7cfa",
    "accent_dim":    "#3d5cf5",
    "accent_muted":  "#1e2a5e",
    "text_primary":  "#e8eaed",
    "text_secondary":"#9da5b4",
    "text_muted":    "#5a6370",
    "success":       "#40c057",
    "warning":       "#fab005",
    "danger":        "#fa5252",
    "gold":          "#ffd700",
}

FONTS: dict = {}
BTN_PRIMARY: dict = {}
BTN_GHOST: dict = {}
BTN_DANGER: dict = {}
BTN_SUCCESS: dict = {}


def _init_theme() -> None:
    global FONTS, BTN_PRIMARY, BTN_GHOST, BTN_DANGER, BTN_SUCCESS
    FONTS = {
        "title":     ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
        "heading":   ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        "body":      ctk.CTkFont(family="Segoe UI", size=13),
        "small":     ctk.CTkFont(family="Segoe UI", size=11),
        "mono":      ctk.CTkFont(family="Consolas",  size=11),
        "char_name": ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
    }
    BTN_PRIMARY = dict(
        corner_radius=8, height=36,
        fg_color=COLORS["accent"], hover_color=COLORS["accent_dim"],
        text_color=COLORS["text_primary"], font=FONTS["body"],
    )
    BTN_GHOST = dict(
        corner_radius=8, height=36,
        fg_color=COLORS["surface_alt"], hover_color=COLORS["border"],
        text_color=COLORS["text_secondary"], font=FONTS["body"],
        border_width=1, border_color=COLORS["border"],
    )
    BTN_DANGER = dict(
        corner_radius=8, height=36,
        fg_color=COLORS["danger"], hover_color="#e03131",
        text_color=COLORS["text_primary"], font=FONTS["body"],
    )
    BTN_SUCCESS = dict(
        corner_radius=8, height=36,
        fg_color=COLORS["success"], hover_color="#2f9e44",
        text_color=COLORS["text_primary"], font=FONTS["body"],
    )


def lbl(parent, text, style="body", color=None, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=FONTS.get(style, FONTS["body"]),
        text_color=color or COLORS["text_primary"],
        **kw,
    )


def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10, **kw)


def btn(parent, text, command, style="primary", **kw) -> ctk.CTkButton:
    base = {"primary": BTN_PRIMARY, "ghost": BTN_GHOST, "danger": BTN_DANGER, "success": BTN_SUCCESS}.get(style, BTN_PRIMARY)
    return ctk.CTkButton(parent, text=text, command=command, **{**base, **kw})


def hsep(parent, row: int, col: int = 0, colspan: int = 4,
         padx=(12, 12), pady=(4, 4)) -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"])
    f.grid(row=row, column=col, columnspan=colspan, sticky="ew", padx=padx, pady=pady)
    return f


def placeholder_image(size=(260, 260)) -> Image.Image:
    img = Image.new("RGBA", size, (44, 45, 51, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=12, outline=(87, 92, 107, 255), width=2)
    return img


class PlayerCard(ctk.CTkFrame):
    def __init__(self, parent, name: str, short_id: str, is_me: bool = False, is_owner: bool = False):
        super().__init__(
            parent,
            fg_color=COLORS["accent_muted"] if is_me else COLORS["surface_alt"],
            corner_radius=8,
        )
        dot_color = COLORS["accent"] if is_me else COLORS["text_muted"]
        ctk.CTkLabel(self, text="●", font=FONTS["small"],
                     text_color=dot_color, width=16).pack(side="left", padx=(10, 6), pady=8)
        name_text = f"👑 {name}" if is_owner else name
        ctk.CTkLabel(self, text=name_text, font=FONTS["body"],
                     text_color=COLORS["gold"] if is_owner else COLORS["text_primary"]).pack(side="left", pady=8)
        ctk.CTkLabel(self, text=f"#{short_id}", font=FONTS["mono"],
                     text_color=COLORS["text_muted"]).pack(side="right", padx=(4, 10), pady=8)


class GuessingGameApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        _init_theme()

        self.title("Guessing Game RPC")
        self.geometry("1200x740")
        self.minsize(1000, 620)
        self.configure(fg_color=COLORS["bg"])

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Estado do jogo
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
        self.voting_phase = False
        self.already_voted = False
        self.choosing_guess = False
        self.responded_this_opportunity = False
        self.target_var = ctk.StringVar(value="Selecione jogador")
        self.game_end_window: ctk.CTkToplevel | None = None
        self.exchange_request_window: ctk.CTkToplevel | None = None
        self.round_number = 1
        self.room_owner_id = ""
        self.session_number = 0
        self.max_rounds = 1
        self.hint_cycle = 1
        self.max_hint_cycles = 3

        # Palpites pendentes de validação manual (só o dono vê)
        # guess_id -> {"guesser_name": str, "guess_text": str}
        self._pending_to_validate: dict[str, dict] = {}

        # Troca pendente para responder
        self._pending_exchange_requester_id = ""
        self._pending_exchange_requester_name = ""
        self._pending_exchange_hint = ""

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=210)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=255)

        self._build_topbar()
        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()
        self._set_connected_state(False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════
    # TOPBAR
    # ═══════════════════════════════════════════
    def _build_topbar(self) -> None:
        tb = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=54)
        tb.grid(row=0, column=0, columnspan=3, sticky="ew")
        tb.grid_propagate(False)
        tb.grid_columnconfigure(1, weight=1)

        lbl(tb, "Guessing Game", style="title").grid(row=0, column=0, padx=(20, 2), sticky="w")
        lbl(tb, "RPC", style="small", color=COLORS["accent"]).grid(row=0, column=0, padx=(172, 0), sticky="w")

        login = ctk.CTkFrame(tb, fg_color="transparent")
        login.grid(row=0, column=2, padx=12, sticky="e")

        self.name_entry = ctk.CTkEntry(
            login, placeholder_text="Seu nome", width=180, height=32,
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=FONTS["body"], corner_radius=8,
        )
        self.name_entry.grid(row=0, column=0, padx=(0, 8))
        self.name_entry.bind("<Return>", lambda _: self.join_game())

        self.join_button = btn(login, "Entrar", self.join_game, width=90, height=32)
        self.join_button.grid(row=0, column=1)

        self.connection_dot = lbl(tb, "●", style="body", color=COLORS["text_muted"])
        self.connection_dot.grid(row=0, column=3, padx=(12, 4))

        self.connection_label = lbl(tb, "Desconectado", style="small", color=COLORS["text_muted"])
        self.connection_label.grid(row=0, column=4, padx=(0, 20))

    # ═══════════════════════════════════════════
    # PAINEL ESQUERDO — Jogadores + Placar
    # ═══════════════════════════════════════════
    def _build_left_panel(self) -> None:
        panel = card(self)
        panel.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=12)
        panel.grid_rowconfigure(2, weight=2)
        panel.grid_rowconfigure(5, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        lbl(panel, "Jogadores", style="heading",
            color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        hsep(panel, row=1, padx=(12, 12), pady=(0, 8))

        self.players_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.players_scroll.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))

        hsep(panel, row=3, padx=(12, 12), pady=(0, 4))
        lbl(panel, "Placar", style="heading",
            color=COLORS["text_secondary"]).grid(row=4, column=0, sticky="w", padx=16, pady=(4, 4))

        self.scores_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", height=100,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.scores_scroll.grid(row=5, column=0, sticky="nsew", padx=8, pady=(0, 12))

    # ═══════════════════════════════════════════
    # PAINEL CENTRAL
    # ═══════════════════════════════════════════
    def _build_center_panel(self) -> None:
        panel = card(self)
        panel.grid(row=1, column=1, sticky="nsew", padx=6, pady=12)
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Linha categoria + sessão/ciclo
        top_row = ctk.CTkFrame(panel, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        top_row.grid_columnconfigure(1, weight=1)

        lbl(top_row, "Categoria:", style="small", color=COLORS["text_muted"]).grid(row=0, column=0, padx=(0, 8))
        badge = ctk.CTkFrame(top_row, fg_color=COLORS["accent_muted"], corner_radius=6)
        badge.grid(row=0, column=1, sticky="w")
        self.category_label = lbl(badge, "Aguardando inicio", style="small", color=COLORS["accent"])
        self.category_label.grid(row=0, column=0, padx=10, pady=4)

        self.session_label = lbl(top_row, "", style="small", color=COLORS["text_muted"])
        self.session_label.grid(row=0, column=2, padx=(12, 0))

        self.turn_label = lbl(panel, "Turno: aguardando", style="small", color=COLORS["text_muted"])
        self.turn_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        hsep(panel, row=2, padx=(12, 12), pady=(0, 6))

        img_card = ctk.CTkFrame(panel, fg_color=COLORS["surface_alt"], corner_radius=12)
        img_card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        img_card.grid_rowconfigure(0, weight=1)
        img_card.grid_columnconfigure(0, weight=1)

        self.character_label = ctk.CTkLabel(img_card, text="", width=260, height=260)
        self.character_label.grid(row=0, column=0, padx=20, pady=20)
        self._load_placeholder_image()

        char_row = ctk.CTkFrame(panel, fg_color="transparent")
        char_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 4))
        char_row.grid_columnconfigure(1, weight=1)
        lbl(char_row, "Seu personagem:", style="small", color=COLORS["text_muted"]).grid(row=0, column=0, padx=(0, 8))
        self.char_name_label = lbl(char_row, "-", style="char_name", color=COLORS["text_primary"])
        self.char_name_label.grid(row=0, column=1, sticky="w")

        hsep(panel, row=5, padx=(12, 12), pady=(4, 6))

        self.action_label = lbl(panel, "Acoes: entre na partida.", style="small", color=COLORS["text_muted"])
        self.action_label.grid(row=6, column=0, sticky="w", padx=16, pady=(0, 6))

        self.action_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self.action_frame.grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 4))
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.action_frame.grid_columnconfigure(1, weight=1)

        # Painel de palpites pendentes (visível apenas ao dono quando há palpites para validar)
        self.pending_frame = ctk.CTkScrollableFrame(
            panel, fg_color=COLORS["surface_alt"], corner_radius=8, height=120,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
            label_text="Palpites para validar",
            label_font=FONTS["small"],
            label_text_color=COLORS["warning"],
            label_fg_color=COLORS["surface_alt"],
        )
        self.pending_frame.grid(row=8, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.pending_frame.grid_columnconfigure(0, weight=1)
        self.pending_frame.grid_remove()

        # Botões de jogo
        self.start_button      = btn(self.action_frame, "Iniciar Partida", self.start_game)
        self.make_guess_button = btn(self.action_frame, "Fazer Palpite", self.start_guess_choice)
        self.no_guess_button   = btn(self.action_frame, "Pular", self.pass_guess_opportunity, style="ghost")
        self.hint_button       = btn(self.action_frame, "Enviar Dica", self.send_public_hint)
        self.guess_button      = btn(self.action_frame, "Confirmar Palpite", self.submit_guess)
        self.pass_button       = btn(self.action_frame, "Passar", self.pass_guess_opportunity, style="ghost")
        self.exchange_button   = btn(self.action_frame, "Troca Privada", self.request_hint_exchange, style="ghost")
        self.spy_button        = btn(self.action_frame, "Espionar Troca", self.spy_on_exchange, style="ghost")
        self.vote_continue_button = btn(self.action_frame, "Continuar Jogando", self.vote_continue, style="success")
        self.vote_end_button      = btn(self.action_frame, "Encerrar Jogo", self.vote_end, style="danger")

        self.target_menu = ctk.CTkOptionMenu(
            self.action_frame, variable=self.target_var,
            values=["Selecione jogador"],
            fg_color=COLORS["surface_alt"], button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_dim"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text_primary"], font=FONTS["body"], corner_radius=8,
        )
        self.guess_entry = ctk.CTkEntry(
            self.action_frame, placeholder_text="Seu palpite...",
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=FONTS["body"], height=36, corner_radius=8,
        )

    # ═══════════════════════════════════════════
    # PAINEL DIREITO — Eventos + Chat
    # ═══════════════════════════════════════════
    def _build_right_panel(self) -> None:
        panel = card(self)
        panel.grid(row=1, column=2, sticky="nsew", padx=(6, 12), pady=12)
        panel.grid_rowconfigure(1, weight=2)
        panel.grid_rowconfigure(4, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        lbl(panel, "Eventos", style="heading",
            color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 4))

        self.events_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.events_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 4))

        hsep(panel, row=2, padx=(10, 10), pady=(4, 4))

        lbl(panel, "Chat", style="heading",
            color=COLORS["text_secondary"]).grid(row=3, column=0, sticky="w", padx=14, pady=(8, 4))

        self.chat_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.chat_scroll.grid(row=4, column=0, sticky="nsew", padx=6, pady=(0, 4))

        chat_input = ctk.CTkFrame(panel, fg_color="transparent")
        chat_input.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 12))
        chat_input.grid_columnconfigure(0, weight=1)

        self.chat_entry = ctk.CTkEntry(
            chat_input, placeholder_text="Mensagem...",
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=FONTS["body"], height=32, corner_radius=8,
        )
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.chat_entry.bind("<Return>", lambda _: self.send_chat_message())

        self.chat_button = btn(chat_input, "->", self.send_chat_message, width=36, height=32)
        self.chat_button.grid(row=0, column=1)

    # ═══════════════════════════════════════════
    # LOGICA DE CONEXAO
    # ═══════════════════════════════════════════
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

        self.room_owner_id = response.room_owner_id
        self._set_connected_state(True)
        self.connection_dot.configure(text_color=COLORS["success"])
        self.connection_label.configure(
            text=f"{player_name} · #{self.rpc_client.player_id[:8]}",
            text_color=COLORS["text_secondary"],
        )
        self._refresh_players()
        self._update_action_state()
        self._append_event(response.message)
        if self.rpc_client.player_id == self.room_owner_id:
            self._append_event("Voce e o dono da sala. Inicie a partida quando quiser.")
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
            self.after(0, self._append_event, f"Stream de jogo encerrado: {error.details()}")

    def _listen_chat_events(self) -> None:
        try:
            for event in self.rpc_client.subscribe_to_chat_events():
                self.after(0, self._append_chat, f"{event.player_name}: {event.text}")
        except grpc.RpcError as error:
            self.after(0, self._append_chat, f"Stream de chat encerrado: {error.details()}")

    # ═══════════════════════════════════════════
    # ACOES DE JOGO
    # ═══════════════════════════════════════════
    def start_game(self) -> None:
        max_rounds = simpledialog.askinteger(
            "Iniciar partida", "Numero de rodadas (sessoes de jogo com temas diferentes):",
            parent=self, minvalue=1, maxvalue=20,
        )
        if max_rounds is None:
            return
        self._run_command("StartGame", lambda: self.rpc_client.start_game(max_rounds))

    def send_public_hint(self) -> None:
        hint = self._ask_text("Dica publica", "Digite uma dica curta (uma palavra):")
        if hint:
            self._run_command("SendPublicHint", lambda: self.rpc_client.send_public_hint(hint))

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
        sent = self._run_command("SubmitGuess", lambda: self.rpc_client.submit_guess(owner_id, guess))
        if sent:
            self.responded_this_opportunity = True
            self.choosing_guess = False
            self._update_action_state()

    def pass_guess_opportunity(self) -> None:
        sent = self._run_command("PassGuessOpportunity", lambda: self.rpc_client.pass_guess_opportunity())
        if sent:
            self.responded_this_opportunity = True
            self.choosing_guess = False
            self._update_action_state()

    def start_guess_choice(self) -> None:
        self.choosing_guess = True
        self._update_action_state()

    def vote_continue(self) -> None:
        self._run_command("VoteForNextRound", lambda: self.rpc_client.vote_for_next_round(True))
        self.already_voted = True
        self._update_action_state()

    def vote_end(self) -> None:
        self._run_command("VoteForNextRound", lambda: self.rpc_client.vote_for_next_round(False))
        self.already_voted = True
        self._update_action_state()

    def _accept_guess(self, guess_id: str) -> None:
        self._run_command("ValidateGuess", lambda: self.rpc_client.validate_guess(guess_id, True))

    def _reject_guess(self, guess_id: str) -> None:
        self._run_command("ValidateGuess", lambda: self.rpc_client.validate_guess(guess_id, False))

    def request_hint_exchange(self) -> None:
        target_name = self.target_var.get()
        target_id = self.players_by_name.get(target_name, "")
        if not target_id:
            self._append_event("Selecione um jogador alvo para a troca.")
            return
        hint = self._ask_text("Troca privada", "Sua dica privada (uma palavra):")
        if not hint:
            return
        self._run_command(
            "RequestHintExchange",
            lambda: self.rpc_client.request_hint_exchange(target_id, hint),
        )

    def spy_on_exchange(self) -> None:
        others = [p.name for p in self.rpc_client.players if p.player_id != self.rpc_client.player_id]
        if len(others) < 2:
            self._append_event("Precisam de pelo menos 2 outros jogadores para espionar.")
            return
        name_a = self._ask_text("Espionar", f"Nome do primeiro jogador a espionar:\n{', '.join(others)}")
        if not name_a:
            return
        name_b = self._ask_text("Espionar", f"Nome do segundo jogador a espionar:\n{', '.join(others)}")
        if not name_b:
            return
        id_a = self.players_by_name.get(name_a, "")
        id_b = self.players_by_name.get(name_b, "")
        if not id_a or not id_b:
            self._append_event("Jogador nao encontrado.")
            return
        self._run_command("SpyOnExchange", lambda: self.rpc_client.spy_on_exchange(id_a, id_b))

    def send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        self.chat_entry.delete(0, "end")
        self._run_command("SendChatMessage", lambda: self.rpc_client.send_chat_message(text), show_success=False)

    def _run_command(self, label: str, command, show_success: bool = True):
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
        self._append_event(f"{label}: {response.message}")
        return False

    def _ask_text(self, title: str, prompt: str) -> str:
        value = simpledialog.askstring(title, prompt, parent=self)
        return value.strip() if value else ""

    # ═══════════════════════════════════════════
    # TRATAMENTO DE EVENTOS
    # ═══════════════════════════════════════════
    def _handle_game_event(self, event) -> None:
        etype = event.type

        # Atualiza lista completa de jogadores apenas em eventos que a carregam completa
        if etype in {game_pb2.PLAYER_JOINED, game_pb2.TURN_STARTED} and event.players:
            self._set_players(list(event.players))

        if event.room_owner_id:
            self.room_owner_id = event.room_owner_id
            if self.rpc_client:
                self.rpc_client.room_owner_id = event.room_owner_id

        if event.max_rounds > 0:
            self.max_rounds = event.max_rounds

        if event.session_number > 0:
            self.session_number = event.session_number
            self._update_session_label()

        if event.hint_cycle > 0:
            self.hint_cycle = event.hint_cycle
            if event.max_hint_cycles > 0:
                self.max_hint_cycles = event.max_hint_cycles
            self._update_session_label()

        if etype in {game_pb2.GAME_STARTED, game_pb2.NEW_ROUND_STARTED}:
            self.game_started = True
            self.voting_phase = False
            self.already_voted = False
            self._pending_to_validate.clear()
            self._refresh_pending_guesses()

        if etype == game_pb2.ROUND_STARTED:
            self.game_started = True
            self.voting_phase = False
            self.already_voted = False
            self.category_name = event.category_name
            self.category_label.configure(text=event.category_name)
            self._load_placeholder_image()
            self.char_name_label.configure(text="-")
            self._pending_to_validate.clear()
            self._refresh_pending_guesses()

        if etype == game_pb2.CHARACTER_ASSIGNED:
            self.game_started = True
            self.character_image_path = event.image_path
            self._load_character_image(event.image_path)
            if event.object_name:
                self.char_name_label.configure(text=event.object_name)

        elif etype in {game_pb2.TURN_STARTED, game_pb2.HINT_PHASE_STARTED, game_pb2.GUESS_PHASE_STARTED}:
            self.choosing_guess = False
            self.responded_this_opportunity = False
            self.game_started = True
            self.current_turn = event.current_turn_player_name
            self.current_turn_player_id = event.current_turn_player_id
            self.turn_phase = event.turn_phase
            is_my_turn = self.rpc_client is not None and event.current_turn_player_id == self.rpc_client.player_id
            suffix = " (sua vez)" if is_my_turn else ""
            self.turn_label.configure(
                text=f"Turno de {event.current_turn_player_name}{suffix}",
                text_color=COLORS["accent"] if is_my_turn else COLORS["text_muted"],
            )

        elif etype == game_pb2.ROUND_ENDED:
            self.game_started = False
            self.turn_label.configure(text="Sessao encerrada", text_color=COLORS["warning"])
            self._show_round_end_window(event)

        elif etype == game_pb2.VOTE_STARTED:
            self.voting_phase = True
            self.already_voted = False
            self.game_started = False
            self.turn_label.configure(text="Votacao em andamento", text_color=COLORS["warning"])

        elif etype == game_pb2.VOTE_CAST:
            pass

        elif etype == game_pb2.GAME_ENDED:
            self.game_started = False
            self.voting_phase = False
            self.current_turn = "Partida encerrada"
            self.current_turn_player_id = ""
            self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
            self.choosing_guess = False
            self.responded_this_opportunity = False
            self.turn_label.configure(text="Partida encerrada", text_color=COLORS["warning"])
            self._show_game_end_window(event)

        elif etype == game_pb2.FINAL_RANKING:
            pass  # já tratado em GAME_ENDED

        elif etype == game_pb2.PENDING_GUESS_FOR_OWNER:
            # Evento privado: o dono recebe para validar
            if self.rpc_client and event.target_player_id == self.rpc_client.player_id:
                self._pending_to_validate[event.guess_id] = {
                    "guesser_name": event.guesser_player_name,
                    "guess_text": event.guess_text,
                }
                self._refresh_pending_guesses()

        elif etype in {game_pb2.GUESS_ACCEPTED, game_pb2.GUESS_REJECTED}:
            # Remove da lista de pendentes (pode ter sido validado pelo dono)
            self._pending_to_validate.pop(event.guess_id, None)
            self._refresh_pending_guesses()

        elif etype == game_pb2.HINT_EXCHANGE_REQUESTED:
            if self.rpc_client and event.target_player_id == self.rpc_client.player_id and event.private_hint:
                self._pending_exchange_requester_id = event.actor_player_id
                self._pending_exchange_requester_name = self._player_name_by_id(event.actor_player_id)
                self._pending_exchange_hint = event.private_hint
                self.after(100, self._show_exchange_request_window)

        elif etype == game_pb2.EXCHANGE_COMPLETED:
            pass  # mensagem já diz a dica

        elif etype == game_pb2.ROUND_SCORE_SUMMARY:
            pass  # mensagem já contém o resumo

        self._update_action_state()

        # Log de eventos
        if etype == game_pb2.PUBLIC_HINT_SENT and event.public_hint:
            self._append_public_hint_event(event)
        elif etype == game_pb2.SCORE_UPDATED:
            pass  # evitar duplicação
        elif etype == game_pb2.FINAL_RANKING:
            pass  # já mostrado na janela GAME_ENDED
        else:
            if event.message.strip():
                color = None
                if etype in {game_pb2.SPY_DISCOVERED}:
                    color = COLORS["danger"]
                elif etype in {game_pb2.SPY_SUCCESSFUL}:
                    color = COLORS["success"]
                elif etype in {game_pb2.EXCHANGE_COMPLETED, game_pb2.HINT_EXCHANGE_OCCURRED, game_pb2.SPY_ATTEMPTED}:
                    color = COLORS["warning"]
                elif etype == game_pb2.GUESS_ACCEPTED:
                    color = COLORS["success"]
                elif etype == game_pb2.GUESS_REJECTED:
                    color = COLORS["danger"]
                elif etype == game_pb2.PENDING_GUESS_FOR_OWNER:
                    color = COLORS["warning"]
                self._append_event(event.message, text_color=color)

        if event.scores:
            self._refresh_scores(event.scores)

    def _player_name_by_id(self, player_id: str) -> str:
        if self.rpc_client:
            for p in self.rpc_client.players:
                if p.player_id == player_id:
                    return p.name
        return player_id[:8]

    def _update_session_label(self) -> None:
        if self.session_number > 0 and self.max_rounds > 0:
            self.session_label.configure(
                text=f"Sessao {self.session_number}/{self.max_rounds} · Ciclo {self.hint_cycle}/{self.max_hint_cycles}"
            )

    # ═══════════════════════════════════════════
    # PAINEL DE PALPITES PENDENTES
    # ═══════════════════════════════════════════
    def _refresh_pending_guesses(self) -> None:
        for w in self.pending_frame.winfo_children():
            w.destroy()

        is_owner = (self.rpc_client is not None and self.rpc_client.player_id == self.room_owner_id)
        if not is_owner or not self._pending_to_validate:
            self.pending_frame.grid_remove()
            return

        self.pending_frame.grid(row=8, column=0, sticky="ew", padx=16, pady=(0, 14))

        for guess_id, info in list(self._pending_to_validate.items()):
            row_frame = ctk.CTkFrame(self.pending_frame, fg_color=COLORS["surface"], corner_radius=6)
            row_frame.pack(fill="x", pady=3, padx=2)
            row_frame.grid_columnconfigure(0, weight=1)

            lbl(row_frame,
                f"{info['guesser_name']}: \"{info['guess_text']}\"",
                style="small", color=COLORS["text_primary"]).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))

            btn_row = ctk.CTkFrame(row_frame, fg_color="transparent")
            btn_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
            btn_row.grid_columnconfigure(0, weight=1)
            btn_row.grid_columnconfigure(1, weight=1)

            gid = guess_id  # capture for closure
            btn(btn_row, "Aceitar", lambda g=gid: self._accept_guess(g), style="success", height=28).grid(
                row=0, column=0, sticky="ew", padx=(0, 3))
            btn(btn_row, "Rejeitar", lambda g=gid: self._reject_guess(g), style="danger", height=28).grid(
                row=0, column=1, sticky="ew", padx=(3, 0))

    # ═══════════════════════════════════════════
    # POPUPS
    # ═══════════════════════════════════════════
    def _show_exchange_request_window(self) -> None:
        if self.exchange_request_window is not None and self.exchange_request_window.winfo_exists():
            self.exchange_request_window.destroy()

        win = ctk.CTkToplevel(self)
        self.exchange_request_window = win
        win.title("Troca de Dica Privada")
        win.geometry("480x260")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        requester = self._pending_exchange_requester_name
        hint = self._pending_exchange_hint

        lbl(body, "Solicitacao de Troca Privada", style="heading", color=COLORS["warning"]).pack(anchor="w", padx=14, pady=(14, 4))
        lbl(body, f"{requester} quer trocar dicas com voce.", style="body", color=COLORS["text_secondary"]).pack(anchor="w", padx=14, pady=(0, 2))
        lbl(body, f"Dica deles: \"{hint}\"", style="body", color=COLORS["accent"]).pack(anchor="w", padx=14, pady=(0, 8))

        hint_entry = ctk.CTkEntry(
            body, placeholder_text="Sua dica (uma palavra)...",
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=FONTS["body"], height=36, corner_radius=8,
        )
        hint_entry.pack(fill="x", padx=14, pady=(0, 8))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        def accept():
            h = hint_entry.get().strip()
            if not h:
                return
            requester_id = self._pending_exchange_requester_id
            self._run_command(
                "RespondHintExchange",
                lambda: self.rpc_client.respond_hint_exchange(requester_id, True, h),
            )
            win.destroy()

        def reject():
            requester_id = self._pending_exchange_requester_id
            self._run_command(
                "RespondHintExchange",
                lambda: self.rpc_client.respond_hint_exchange(requester_id, False),
            )
            win.destroy()

        btn(btn_row, "Aceitar e Trocar", accept, style="success").grid(row=0, column=0, sticky="ew", padx=(0, 4))
        btn(btn_row, "Recusar", reject, style="danger").grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _show_round_end_window(self, event) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Fim de Sessao")
        win.geometry("560x480")
        win.resizable(True, True)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        title_text = "Sessao Encerrada — Jogo Finalizado!" if event.is_final_session else "Sessao Encerrada!"
        title_color = COLORS["gold"] if event.is_final_session else COLORS["warning"]
        lbl(body, title_text, style="heading", color=title_color).pack(anchor="w", padx=14, pady=(14, 8))

        if event.character_reveals:
            lbl(body, "Personagens revelados:", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14)
            for reveal in event.character_reveals:
                lbl(body, f"  {reveal.player_name} tinha: {reveal.character_name}",
                    style="body", color=COLORS["text_secondary"]).pack(anchor="w", padx=20)

        if event.score_deltas:
            lbl(body, "Pontos nesta sessao:", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(8, 0))
            for delta in sorted(event.score_deltas, key=lambda d: d.score, reverse=True):
                if delta.score != 0:
                    sign = "+" if delta.score > 0 else ""
                    color = COLORS["success"] if delta.score > 0 else COLORS["danger"]
                    lbl(body, f"  {delta.player_name}: {sign}{delta.score} pts",
                        style="body", color=color).pack(anchor="w", padx=20)

        if event.scores:
            lbl(body, "Placar acumulado:", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(8, 0))
            for i, score in enumerate(sorted(event.scores, key=lambda s: s.score, reverse=True)):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
                lbl(body, f"  {medal} {score.player_name}: {score.score} pts",
                    style="body", color=COLORS["text_primary"]).pack(anchor="w", padx=20)

        if event.is_final_session:
            lbl(body, "Esta foi a ultima sessao.", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(12, 4))
        else:
            lbl(body, "Votacao iniciada automaticamente.", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(12, 4))

        btn(body, "Fechar", win.destroy, style="ghost").pack(fill="x", padx=14, pady=(0, 14))

    def _show_game_end_window(self, event) -> None:
        if self.game_end_window is not None and self.game_end_window.winfo_exists():
            self.game_end_window.destroy()

        win = ctk.CTkToplevel(self)
        self.game_end_window = win
        win.title("Fim de Jogo")
        win.geometry("520x420")
        win.resizable(True, True)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Fim de Jogo!", style="heading", color=COLORS["warning"]).pack(anchor="w", padx=14, pady=(14, 8))
        lbl(body, event.message, style="body", color=COLORS["text_secondary"],
            wraplength=460, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        # Usa ranking se disponível, senão fallback em scores
        if event.ranking:
            lbl(body, "Ranking Final:", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(4, 0))
            for entry in event.ranking:
                medals = ["🥇", "🥈", "🥉"]
                medal = medals[entry.position - 1] if entry.position <= 3 else f"{entry.position}."
                color = COLORS["gold"] if entry.position == 1 else COLORS["text_primary"]
                lbl(body, f"  {medal} {entry.player_name}: {entry.score} pts",
                    style="body", color=color).pack(anchor="w", padx=20)
        elif event.scores:
            lbl(body, "Ranking Final:", style="small", color=COLORS["text_muted"]).pack(anchor="w", padx=14, pady=(4, 0))
            for i, score in enumerate(sorted(event.scores, key=lambda s: s.score, reverse=True)):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
                color = COLORS["gold"] if i == 0 else COLORS["text_primary"]
                lbl(body, f"  {medal} {score.player_name}: {score.score} pts",
                    style="body", color=color).pack(anchor="w", padx=20)

        btn(body, "Nova Partida", self._restart_from_game_end).pack(fill="x", padx=14, pady=(12, 6))
        btn(body, "Fechar", win.destroy, style="ghost").pack(fill="x", padx=14, pady=(0, 14))

    def _restart_from_game_end(self) -> None:
        if self.game_end_window is not None and self.game_end_window.winfo_exists():
            self.game_end_window.destroy()
        self.start_game()

    # ═══════════════════════════════════════════
    # UI HELPERS
    # ═══════════════════════════════════════════
    def _update_action_state(self) -> None:
        connected = self.rpc_client is not None and bool(self.rpc_client.player_id)
        self._hide_action_widgets()

        if not connected:
            self.action_label.configure(text="Entre na partida para jogar.")
            return

        if self.voting_phase:
            if self.already_voted:
                self.action_label.configure(text="Aguardando outros jogadores votarem...")
            else:
                self.action_label.configure(text="Continuar jogando ou encerrar?")
                self._show(self.vote_continue_button, 0, 0)
                self._show(self.vote_end_button, 0, 1)
            return

        if not self.game_started:
            is_owner = (self.rpc_client is not None and self.rpc_client.player_id == self.room_owner_id)
            if is_owner:
                self.start_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=4)
                self.start_button.configure(state="normal")
                self.action_label.configure(text="Voce e o dono. Inicie quando quiser.")
            else:
                self.action_label.configure(text="Aguarde o dono da sala iniciar a partida.")
            return

        is_my_turn = (self.rpc_client is not None and self.current_turn_player_id == self.rpc_client.player_id)
        can_pre  = self.turn_phase == game_pb2.PRE_HINT_GUESS and is_my_turn
        can_hint = self.turn_phase == game_pb2.HINT and is_my_turn
        can_post = self.turn_phase == game_pb2.POST_HINT_GUESSES and not is_my_turn
        can_guess = (can_pre or can_post) and not self.responded_this_opportunity

        # Troca disponível sempre que o jogo estiver ativo e não for sua vez de dar dica
        show_exchange = self.game_started and not (self.turn_phase == game_pb2.HINT and is_my_turn)
        show_spy = self.game_started and len(self.players_by_name) >= 2

        if can_pre and not self.choosing_guess:
            self.action_label.configure(text="Voce pode fazer um palpite antes da dica.")
            self._show(self.make_guess_button, 0, 0)
            self._show(self.no_guess_button,   0, 1)
            if show_exchange:
                self._show(self.exchange_button, 1, 0, span=2)

        elif can_pre and self.choosing_guess:
            self.action_label.configure(text="Escolha um jogador e envie um palpite.")
            self._show(self.target_menu,  0, 0, span=2)
            self._show(self.guess_entry,  1, 0, span=2)
            self._show(self.guess_button, 2, 0)
            self._show(self.pass_button,  2, 1)

        elif can_hint:
            self.action_label.configure(text="Agora envie sua dica publica.")
            self._show(self.hint_button, 0, 0, span=2)

        elif can_post and can_guess and not self.choosing_guess:
            self.action_label.configure(text=f"Quer adivinhar o personagem de {self.current_turn}?")
            self._show(self.make_guess_button, 0, 0)
            self._show(self.no_guess_button,   0, 1)
            if show_exchange:
                self._show(self.exchange_button, 1, 0, span=2)
            if show_spy:
                row = 2 if show_exchange else 1
                self._show(self.spy_button, row, 0, span=2)

        elif can_post and can_guess and self.choosing_guess:
            self.action_label.configure(text=f"Digite seu palpite para {self.current_turn}.")
            self._show(self.guess_entry,  0, 0, span=2)
            self._show(self.guess_button, 1, 0)
            self._show(self.pass_button,  1, 1)

        elif self.responded_this_opportunity:
            self.action_label.configure(text="Voce ja respondeu esta oportunidade.")
            if show_exchange:
                self._show(self.exchange_button, 0, 0, span=2)
            if show_spy:
                row = 1 if show_exchange else 0
                self._show(self.spy_button, row, 0, span=2)
        else:
            self.action_label.configure(text="Aguarde os outros jogadores.")
            if show_spy:
                self._show(self.spy_button, 0, 0, span=2)
            if show_exchange:
                row = 1 if show_spy else 0
                self._show(self.exchange_button, row, 0, span=2)

    def _hide_action_widgets(self) -> None:
        for w in [
            self.start_button, self.make_guess_button, self.no_guess_button,
            self.target_menu, self.guess_entry, self.guess_button,
            self.pass_button, self.hint_button, self.exchange_button,
            self.spy_button, self.vote_continue_button, self.vote_end_button,
        ]:
            try:
                w.configure(state="disabled")
            except Exception:
                pass
            w.grid_remove()

    @staticmethod
    def _show(widget, row: int, col: int, span: int = 1) -> None:
        px = (0, 4) if (col == 0 and span == 1) else (0, 0)
        widget.grid(row=row, column=col, columnspan=span, sticky="ew", padx=px, pady=4)
        try:
            widget.configure(state="normal")
        except Exception:
            pass

    def _append_event(self, text: str, text_color: str | None = None) -> None:
        if not text.strip():
            return
        row_frame = ctk.CTkFrame(self.events_scroll, fg_color="transparent")
        row_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(row_frame, text=">", font=FONTS["body"],
                     text_color=COLORS["accent"], width=14).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row_frame, text=text, font=FONTS["small"],
                     text_color=text_color or COLORS["text_secondary"],
                     anchor="w", justify="left", wraplength=210).pack(side="left", fill="x", expand=True)
        try:
            self.events_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _append_public_hint_event(self, event) -> None:
        actor_name = event.current_turn_player_name or "Jogador"
        hint = event.public_hint.strip()
        if not hint:
            self._append_event(event.message)
            return
        row_frame = ctk.CTkFrame(self.events_scroll, fg_color="transparent")
        row_frame.pack(fill="x", pady=1)
        ctk.CTkLabel(row_frame, text=">", font=FONTS["body"],
                     text_color=COLORS["accent"], width=14).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row_frame, text=f"{actor_name} deu dica: ",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     anchor="w").pack(side="left")
        ctk.CTkLabel(row_frame, text=hint, font=FONTS["small"],
                     text_color=COLORS["accent"], anchor="w").pack(side="left", fill="x", expand=True)
        try:
            self.events_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _append_chat(self, text: str) -> None:
        if not text.strip():
            return
        ctk.CTkLabel(self.chat_scroll, text=text, font=FONTS["small"],
                     text_color=COLORS["text_secondary"],
                     anchor="w", justify="left", wraplength=210).pack(fill="x", padx=4, pady=1)
        try:
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _refresh_players(self) -> None:
        if self.rpc_client is None:
            return
        self._set_players(self.rpc_client.players)

    def _set_players(self, players) -> None:
        if self.rpc_client is None:
            return
        self.rpc_client.players = list(players)
        self.players_by_name = {p.name: p.player_id for p in players}
        for w in self.players_scroll.winfo_children():
            w.destroy()
        for player in players:
            is_me = player.player_id == self.rpc_client.player_id
            is_owner = player.player_id == self.room_owner_id
            PlayerCard(self.players_scroll, name=player.name,
                       short_id=player.player_id[:8], is_me=is_me,
                       is_owner=is_owner).pack(fill="x", pady=3, padx=2)
        self._refresh_target_menu()

    def _refresh_scores(self, scores) -> None:
        for w in self.scores_scroll.winfo_children():
            w.destroy()
        for i, score in enumerate(sorted(scores, key=lambda s: s.score, reverse=True)):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            color = COLORS["gold"] if i == 0 else COLORS["text_secondary"]
            ctk.CTkLabel(
                self.scores_scroll,
                text=f"{medal} {score.player_name}: {score.score}",
                font=FONTS["small"], text_color=color, anchor="w",
            ).pack(fill="x", padx=4, pady=1)

    def _set_connected_state(self, connected: bool) -> None:
        login_state   = "disabled" if connected else "normal"
        command_state = "normal"   if connected else "disabled"
        self.name_entry.configure(state=login_state)
        self.join_button.configure(state=login_state)
        self.chat_entry.configure(state=command_state)
        self.chat_button.configure(state=command_state)
        if not connected:
            self.connection_dot.configure(text_color=COLORS["text_muted"])
            self.connection_label.configure(text="Desconectado", text_color=COLORS["text_muted"])
        self._update_action_state()

    def _refresh_target_menu(self) -> None:
        if self.rpc_client is None:
            values = ["Selecione jogador"]
        else:
            values = [p.name for p in self.rpc_client.players if p.player_id != self.rpc_client.player_id] or ["Selecione jogador"]
        self.target_menu.configure(values=values)
        if self.target_var.get() not in values:
            self.target_var.set(values[0])

    def _selected_guess_owner_id(self) -> str:
        if self.turn_phase == game_pb2.POST_HINT_GUESSES:
            return self.current_turn_player_id
        return self.players_by_name.get(self.target_var.get(), "")

    def _load_placeholder_image(self) -> None:
        img = placeholder_image(size=(260, 260))
        self.character_image = ctk.CTkImage(light_image=img, dark_image=img, size=(260, 260))
        self.character_label.configure(image=self.character_image, text="")

    def _load_character_image(self, image_path: str) -> None:
        absolute_path = os.path.join(PROJECT_ROOT, image_path)
        if not os.path.exists(absolute_path):
            self.character_label.configure(image=None, text=f"Imagem nao encontrada:\n{image_path}")
            return
        image = Image.open(absolute_path)
        self.character_image = ctk.CTkImage(light_image=image, dark_image=image, size=(260, 260))
        self.character_label.configure(image=self.character_image, text="")

    def _on_close(self) -> None:
        if self.rpc_client is not None:
            self.rpc_client.close()
        self.destroy()


if __name__ == "__main__":
    app = GuessingGameApp()
    app.mainloop()
