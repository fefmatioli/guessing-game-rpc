from __future__ import annotations

import os
import threading
import tkinter.simpledialog as simpledialog

import customtkinter as ctk
import grpc
from PIL import Image, ImageDraw

from grpc_client import GameRpcClient, game_pb2


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────────
# PALETA DE CORES
# ─────────────────────────────────────────────
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
}

# Fontes e estilos de botao sao inicializados em _init_theme()
# apos a janela tkinter existir (CTkFont requer root window)
FONTS: dict = {}
BTN_PRIMARY: dict = {}
BTN_GHOST: dict = {}


def _init_theme() -> None:
    """Deve ser chamado logo apos super().__init__() na janela principal."""
    global FONTS, BTN_PRIMARY, BTN_GHOST
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


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def lbl(parent, text, style="body", color=None, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=FONTS.get(style, FONTS["body"]),
        text_color=color or COLORS["text_primary"],
        **kw,
    )


def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=COLORS["surface"],
                        corner_radius=10, **kw)


def btn(parent, text, command, style="primary", **kw) -> ctk.CTkButton:
    base = BTN_PRIMARY if style == "primary" else BTN_GHOST
    return ctk.CTkButton(parent, text=text, command=command, **{**base, **kw})


def hsep(parent, row: int, col: int = 0, colspan: int = 4,
         padx=(12, 12), pady=(4, 4)) -> ctk.CTkFrame:
    """Separador horizontal usando grid (nunca pack) para evitar conflito."""
    f = ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"])
    f.grid(row=row, column=col, columnspan=colspan,
           sticky="ew", padx=padx, pady=pady)
    return f


def placeholder_image(size=(260, 260)) -> Image.Image:
    img = Image.new("RGBA", size, (44, 45, 51, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size[0]-1, size[1]-1],
                            radius=12, outline=(87, 92, 107, 255), width=2)
    return img


# ─────────────────────────────────────────────
# PLAYER CARD — painel esquerdo
# Usa pack internamente (e eh colocado no ScrollableFrame com pack)
# ─────────────────────────────────────────────
class PlayerCard(ctk.CTkFrame):
    def __init__(self, parent, name: str, short_id: str, is_me: bool = False):
        super().__init__(
            parent,
            fg_color=COLORS["accent_muted"] if is_me else COLORS["surface_alt"],
            corner_radius=8,
        )
        # Internamente usa pack pois o frame nao mistura com grid externo
        dot_color = COLORS["accent"] if is_me else COLORS["text_muted"]
        ctk.CTkLabel(self, text="●", font=FONTS["small"],
                     text_color=dot_color, width=16).pack(side="left",
                                                          padx=(10, 6), pady=8)
        ctk.CTkLabel(self, text=name, font=FONTS["body"],
                     text_color=COLORS["text_primary"]).pack(side="left", pady=8)
        ctk.CTkLabel(self, text=f"#{short_id}", font=FONTS["mono"],
                     text_color=COLORS["text_muted"]).pack(side="right",
                                                           padx=(4, 10), pady=8)


# ─────────────────────────────────────────────
# APP PRINCIPAL
# ─────────────────────────────────────────────
class GuessingGameApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        _init_theme()  # CTkFont requer root window — inicializar aqui

        self.title("Guessing Game RPC")
        self.geometry("1200x740")
        self.minsize(1000, 620)
        self.configure(fg_color=COLORS["bg"])

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── Estado do jogo (identico ao original) ──
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
        self.target_var = ctk.StringVar(value="Selecione jogador")
        self.max_guesses_per_player = 0
        self.remaining_guesses_by_player_id: dict[str, int] = {}
        self.game_end_window: ctk.CTkToplevel | None = None

        # ── Grid raiz: topbar (row 0) + conteudo (row 1) ──
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
        tb = ctk.CTkFrame(self, fg_color=COLORS["surface"],
                          corner_radius=0, height=54)
        tb.grid(row=0, column=0, columnspan=3, sticky="ew")
        tb.grid_propagate(False)
        tb.grid_columnconfigure(1, weight=1)

        lbl(tb, "Guessing Game", style="title").grid(
            row=0, column=0, padx=(20, 2), sticky="w")
        lbl(tb, "RPC", style="small", color=COLORS["accent"]).grid(
            row=0, column=0, padx=(172, 0), sticky="w")

        # Login group
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

        self.join_button = btn(login, "Entrar", self.join_game,
                               width=90, height=32)
        self.join_button.grid(row=0, column=1)

        # Status de conexao
        self.connection_dot = lbl(tb, "●", style="body",
                                  color=COLORS["text_muted"])
        self.connection_dot.grid(row=0, column=3, padx=(12, 4))

        self.connection_label = lbl(tb, "Desconectado", style="small",
                                    color=COLORS["text_muted"])
        self.connection_label.grid(row=0, column=4, padx=(0, 20))

    # ═══════════════════════════════════════════
    # PAINEL ESQUERDO — Jogadores
    # ═══════════════════════════════════════════
    def _build_left_panel(self) -> None:
        panel = card(self)
        panel.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=12)
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        lbl(panel, "Jogadores", style="heading",
            color=COLORS["text_secondary"]).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        hsep(panel, row=1, padx=(12, 12), pady=(0, 8))

        # CTkScrollableFrame aceita pack nos filhos diretos
        self.players_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.players_scroll.grid(row=2, column=0, sticky="nsew",
                                 padx=8, pady=(0, 12))

    # ═══════════════════════════════════════════
    # PAINEL CENTRAL
    # ═══════════════════════════════════════════
    def _build_center_panel(self) -> None:
        panel = card(self)
        panel.grid(row=1, column=1, sticky="nsew", padx=6, pady=12)
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Linha categoria
        cat_row = ctk.CTkFrame(panel, fg_color="transparent")
        cat_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        cat_row.grid_columnconfigure(1, weight=1)

        lbl(cat_row, "Categoria:", style="small",
            color=COLORS["text_muted"]).grid(row=0, column=0, padx=(0, 8))

        badge = ctk.CTkFrame(cat_row, fg_color=COLORS["accent_muted"],
                             corner_radius=6)
        badge.grid(row=0, column=1, sticky="w")
        # badge usa grid internamente
        self.category_label = lbl(badge, "Aguardando inicio",
                                  style="small", color=COLORS["accent"])
        self.category_label.grid(row=0, column=0, padx=10, pady=4)

        # Turno
        self.turn_label = lbl(panel, "Turno: aguardando",
                              style="small", color=COLORS["text_muted"])
        self.turn_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        hsep(panel, row=2, padx=(12, 12), pady=(0, 6))

        # Card da imagem
        img_card = ctk.CTkFrame(panel, fg_color=COLORS["surface_alt"],
                                corner_radius=12)
        img_card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        img_card.grid_rowconfigure(0, weight=1)
        img_card.grid_columnconfigure(0, weight=1)

        self.character_label = ctk.CTkLabel(img_card, text="",
                                            width=260, height=260)
        self.character_label.grid(row=0, column=0, padx=20, pady=20)
        self._load_placeholder_image()

        # Nome do personagem
        char_row = ctk.CTkFrame(panel, fg_color="transparent")
        char_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 4))
        char_row.grid_columnconfigure(1, weight=1)

        lbl(char_row, "Seu personagem:", style="small",
            color=COLORS["text_muted"]).grid(row=0, column=0, padx=(0, 8))
        self.char_name_label = lbl(char_row, "-", style="char_name",
                                   color=COLORS["text_primary"])
        self.char_name_label.grid(row=0, column=1, sticky="w")

        hsep(panel, row=5, padx=(12, 12), pady=(4, 6))

        # Rotulo de acao
        self.action_label = lbl(panel, "Acoes: entre na partida.",
                                style="small", color=COLORS["text_muted"])
        self.action_label.grid(row=6, column=0, sticky="w",
                               padx=16, pady=(0, 6))

        # Frame de acoes (botoes aparecem aqui dinamicamente)
        self.action_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self.action_frame.grid(row=7, column=0, sticky="ew",
                               padx=16, pady=(0, 14))
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.action_frame.grid_columnconfigure(1, weight=1)

        # Botoes criados uma vez; mostrados/ocultados via grid/grid_remove
        self.start_button      = btn(self.action_frame, "Iniciar Partida",
                                     self.start_game)
        self.make_guess_button = btn(self.action_frame, "Fazer Palpite",
                                     self.start_guess_choice)
        self.no_guess_button   = btn(self.action_frame, "Pular",
                                     self.pass_guess_opportunity, style="ghost")
        self.hint_button       = btn(self.action_frame, "Enviar Dica",
                                     self.send_public_hint)
        self.guess_button      = btn(self.action_frame, "Confirmar Palpite",
                                     self.submit_guess)
        self.pass_button       = btn(self.action_frame, "Passar",
                                     self.pass_guess_opportunity, style="ghost")
        self.exchange_button   = btn(self.action_frame, "Troca Privada",
                                     self.request_hint_exchange, style="ghost")
        self.spy_button        = btn(self.action_frame, "Espionar",
                                     self.spy_on_exchange, style="ghost")

        self.target_menu = ctk.CTkOptionMenu(
            self.action_frame, variable=self.target_var,
            values=["Selecione jogador"],
            fg_color=COLORS["surface_alt"], button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_dim"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text_primary"], font=FONTS["body"],
            corner_radius=8,
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
            color=COLORS["text_secondary"]).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 4))

        self.events_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.events_scroll.grid(row=1, column=0, sticky="nsew",
                                padx=6, pady=(0, 4))

        hsep(panel, row=2, padx=(10, 10), pady=(4, 4))

        lbl(panel, "Chat", style="heading",
            color=COLORS["text_secondary"]).grid(
            row=3, column=0, sticky="w", padx=14, pady=(8, 4))

        self.chat_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.chat_scroll.grid(row=4, column=0, sticky="nsew",
                              padx=6, pady=(0, 4))

        # Input do chat
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

        self.chat_button = btn(chat_input, "->", self.send_chat_message,
                               width=36, height=32)
        self.chat_button.grid(row=0, column=1)

    # ═══════════════════════════════════════════
    # LOGICA DE JOGO — identica ao original
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

        self._set_connected_state(True)
        self.connection_dot.configure(text_color=COLORS["success"])
        self.connection_label.configure(
            text=f"{player_name} · #{self.rpc_client.player_id[:8]}",
            text_color=COLORS["text_secondary"],
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
            self.after(0, self._append_event,
                       f"Stream de jogo encerrado: {error.details()}")

    def _listen_chat_events(self) -> None:
        try:
            for event in self.rpc_client.subscribe_to_chat_events():
                self.after(0, self._append_chat,
                           f"{event.player_name}: {event.text}")
        except grpc.RpcError as error:
            self.after(0, self._append_chat,
                       f"Stream de chat encerrado: {error.details()}")

    def start_game(self) -> None:
        max_guesses = simpledialog.askinteger(
            "Iniciar partida",
            "Numero de palpites por jogador:",
            parent=self,
            minvalue=1,
            maxvalue=99,
        )
        if max_guesses is None:
            return
        self._run_command(
            "StartGame",
            lambda: self.rpc_client.start_game(max_guesses),
        )

    def send_public_hint(self) -> None:
        hint = self._ask_text("Dica publica", "Digite uma dica curta:")
        if hint:
            self._run_command("SendPublicHint",
                              lambda: self.rpc_client.send_public_hint(hint))

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
            "SubmitGuess", lambda: self.rpc_client.submit_guess(owner_id, guess))
        if sent:
            self.responded_this_opportunity = True
            self.choosing_guess = False
            self._update_action_state()

    def pass_guess_opportunity(self) -> None:
        sent = self._run_command(
            "PassGuessOpportunity", lambda: self.rpc_client.pass_guess_opportunity())
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
                lambda: self.rpc_client.request_hint_exchange(
                    target_id, private_hint),
            )

    def spy_on_exchange(self) -> None:
        player_a_id = self._ask_text("Espionagem", "ID do primeiro jogador:")
        if not player_a_id:
            return
        player_b_id = self._ask_text("Espionagem", "ID do segundo jogador:")
        if player_b_id:
            self._run_command(
                "SpyOnExchange",
                lambda: self.rpc_client.spy_on_exchange(
                    player_a_id, player_b_id),
            )

    def send_chat_message(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        self.chat_entry.delete(0, "end")
        self._run_command("SendChatMessage",
                          lambda: self.rpc_client.send_chat_message(text),
                          show_success=False)

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

    def _handle_game_event(self, event) -> None:
        if event.players:
            self._set_players(list(event.players))

        if event.max_guesses_per_player > 0:
            self.max_guesses_per_player = event.max_guesses_per_player

        if event.remaining_guesses:
            self.remaining_guesses_by_player_id = {
                item.player_id: item.guesses_left
                for item in event.remaining_guesses
            }

        if event.type == game_pb2.GAME_STARTED:
            self.game_started = True

        if event.type == game_pb2.ROUND_STARTED:
            self.game_started = True
            self.category_name = event.category_name
            self.category_label.configure(text=event.category_name)

        if event.type == game_pb2.CHARACTER_ASSIGNED:
            self.game_started = True
            self.character_image_path = event.image_path
            self._load_character_image(event.image_path)
            if hasattr(event, "character_name") and event.character_name:
                self.char_name_label.configure(text=event.character_name)

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
            turn_color = COLORS["accent"] if is_my_turn else COLORS["text_muted"]
            self.turn_label.configure(
                text=f"Turno de {event.current_turn_player_name}{suffix}",
                text_color=turn_color,
            )

        elif event.type == game_pb2.GAME_ENDED:
            self.game_started = False
            self.current_turn = "Partida encerrada"
            self.current_turn_player_id = ""
            self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
            self.choosing_guess = False
            self.responded_this_opportunity = False
            self.turn_label.configure(
                text="Partida encerrada",
                text_color=COLORS["warning"],
            )

        self._update_action_state()
        if event.type == game_pb2.PUBLIC_HINT_SENT and event.public_hint:
            self._append_public_hint_event(event)
        else:
            self._append_event(event.message)

        if event.type == game_pb2.GAME_ENDED:
            self._show_game_end_window(event.message)

        if event.scores:
            self._append_event(self._format_scores(event.scores))

        if event.remaining_guesses and self.rpc_client is not None and self.rpc_client.player_id:
            left = self.remaining_guesses_by_player_id.get(self.rpc_client.player_id)
            if left is not None:
                self._append_event(f"Seus palpites restantes: {left}")

    # ═══════════════════════════════════════════
    # UI HELPERS
    # ═══════════════════════════════════════════
    def _append_event(self, text: str, text_color: str | None = None) -> None:
        if not text.strip():
            return
        # CTkScrollableFrame: filhos diretos podem usar pack
        row_frame = ctk.CTkFrame(self.events_scroll, fg_color="transparent")
        row_frame.pack(fill="x", pady=1)

        ctk.CTkLabel(row_frame, text=">", font=FONTS["body"],
                     text_color=COLORS["accent"], width=14).pack(
            side="left", padx=(0, 6))
        ctk.CTkLabel(row_frame, text=text, font=FONTS["small"],
                     text_color=text_color or COLORS["text_secondary"],
                     anchor="w", justify="left", wraplength=210).pack(
            side="left", fill="x", expand=True)

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
                     text_color=COLORS["accent"], width=14).pack(
            side="left", padx=(0, 6))
        ctk.CTkLabel(row_frame,
                     text=f"{actor_name} deu uma dica publica: ",
                     font=FONTS["small"],
                     text_color=COLORS["text_secondary"],
                     anchor="w", justify="left", wraplength=210).pack(
            side="left")
        ctk.CTkLabel(row_frame, text=hint, font=FONTS["small"],
                     text_color=COLORS["accent"],
                     anchor="w", justify="left", wraplength=210).pack(
            side="left", fill="x", expand=True)

        try:
            self.events_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _append_chat(self, text: str) -> None:
        if not text.strip():
            return
        ctk.CTkLabel(self.chat_scroll, text=text, font=FONTS["small"],
                     text_color=COLORS["text_secondary"],
                     anchor="w", justify="left", wraplength=210).pack(
            fill="x", padx=4, pady=1)

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
            is_me = (self.rpc_client is not None
                     and player.player_id == self.rpc_client.player_id)
            PlayerCard(self.players_scroll,
                       name=player.name,
                       short_id=player.player_id[:8],
                       is_me=is_me).pack(fill="x", pady=3, padx=2)

        self._refresh_target_menu()

    def _set_connected_state(self, connected: bool) -> None:
        login_state   = "disabled" if connected else "normal"
        command_state = "normal"   if connected else "disabled"

        self.name_entry.configure(state=login_state)
        self.join_button.configure(state=login_state)
        self.chat_entry.configure(state=command_state)
        self.chat_button.configure(state=command_state)

        if not connected:
            self.connection_dot.configure(text_color=COLORS["text_muted"])
            self.connection_label.configure(text="Desconectado",
                                            text_color=COLORS["text_muted"])
        self._update_action_state()

    def _refresh_target_menu(self) -> None:
        if self.rpc_client is None:
            values = ["Selecione jogador"]
        else:
            values = [
                p.name for p in self.rpc_client.players
                if p.player_id != self.rpc_client.player_id
            ] or ["Selecione jogador"]

        self.target_menu.configure(values=values)
        if self.target_var.get() not in values:
            self.target_var.set(values[0])

    def _selected_guess_owner_id(self) -> str:
        if self.turn_phase == game_pb2.POST_HINT_GUESSES:
            return self.current_turn_player_id
        return self.players_by_name.get(self.target_var.get(), "")

    def _update_action_state(self) -> None:
        connected = self.rpc_client is not None and bool(self.rpc_client.player_id)
        self._hide_action_widgets()

        if not connected:
            self.action_label.configure(text="Entre na partida para jogar.")
            return

        if not self.game_started:
            self.start_button.grid(row=0, column=0, columnspan=2,
                                   sticky="ew", pady=4)
            self.start_button.configure(state="normal")
            self.action_label.configure(
                text="Aguarde os jogadores e inicie a partida.")
            return

        self.start_button.grid_remove()

        is_my_turn = (self.rpc_client is not None
                      and self.current_turn_player_id == self.rpc_client.player_id)
        my_id = self.rpc_client.player_id if self.rpc_client is not None else ""
        guesses_left = self.remaining_guesses_by_player_id.get(my_id)
        can_still_guess = guesses_left is None or guesses_left > 0
        can_pre  = self.turn_phase == game_pb2.PRE_HINT_GUESS and is_my_turn
        can_hint = self.turn_phase == game_pb2.HINT and is_my_turn
        can_post = self.turn_phase == game_pb2.POST_HINT_GUESSES and not is_my_turn
        can_guess = (
            (can_pre or can_post)
            and not self.responded_this_opportunity
            and can_still_guess
        )

        if can_pre and not can_still_guess:
            self.action_label.configure(
                text="Seus palpites acabaram. Envie apenas sua dica.")
            self._show(self.no_guess_button, 0, 0, span=2)

        elif can_pre and not self.choosing_guess:
            self.action_label.configure(
                text="Voce pode fazer um palpite antes da dica.")
            self._show(self.make_guess_button, 0, 0)
            self._show(self.no_guess_button,   0, 1)

        elif can_pre and self.choosing_guess:
            self.action_label.configure(
                text="Escolha um jogador e envie um palpite.")
            self._show(self.target_menu,  0, 0, span=2)
            self._show(self.guess_entry,  1, 0, span=2)
            self._show(self.guess_button, 2, 0)
            self._show(self.pass_button,  2, 1)

        elif can_hint:
            self.action_label.configure(text="Agora envie sua dica publica.")
            self._show(self.hint_button, 0, 0, span=2)

        elif can_post and not can_still_guess and not self.responded_this_opportunity:
            self.action_label.configure(
                text=f"Seus palpites acabaram. Passe a vez para {self.current_turn}.")
            self._show(self.pass_button, 0, 0, span=2)

        elif can_post and can_guess and not self.choosing_guess:
            self.action_label.configure(
                text=f"Quer adivinhar o personagem de {self.current_turn}?")
            self._show(self.make_guess_button, 0, 0)
            self._show(self.no_guess_button,   0, 1)

        elif can_post and can_guess and self.choosing_guess:
            self.action_label.configure(
                text=f"Digite seu palpite para {self.current_turn}.")
            self._show(self.guess_entry,  0, 0, span=2)
            self._show(self.guess_button, 1, 0)
            self._show(self.pass_button,  1, 1)

        elif self.responded_this_opportunity:
            self.action_label.configure(
                text="Voce ja respondeu esta oportunidade.")
        else:
            self.action_label.configure(text="Aguarde os outros jogadores.")

    def _hide_action_widgets(self) -> None:
        for w in [
            self.start_button, self.make_guess_button, self.no_guess_button,
            self.target_menu, self.guess_entry, self.guess_button,
            self.pass_button, self.hint_button, self.exchange_button,
            self.spy_button,
        ]:
            try:
                w.configure(state="disabled")
            except Exception:
                pass
            w.grid_remove()

    @staticmethod
    def _show(widget, row: int, col: int, span: int = 1) -> None:
        px = (0, 4) if (col == 0 and span == 1) else (0, 0)
        widget.grid(row=row, column=col, columnspan=span,
                    sticky="ew", padx=px, pady=4)
        try:
            widget.configure(state="normal")
        except Exception:
            pass

    @staticmethod
    def _format_scores(scores) -> str:
        ordered = sorted(scores, key=lambda s: s.score, reverse=True)
        return "Placar: " + " | ".join(
            f"{s.player_name} {s.score}pts" for s in ordered
        )

    def _load_placeholder_image(self) -> None:
        img = placeholder_image(size=(260, 260))
        self.character_image = ctk.CTkImage(
            light_image=img, dark_image=img, size=(260, 260))
        self.character_label.configure(image=self.character_image, text="")

    def _load_character_image(self, image_path: str) -> None:
        absolute_path = os.path.join(PROJECT_ROOT, image_path)
        if not os.path.exists(absolute_path):
            self.character_label.configure(
                image=None,
                text=f"Imagem nao encontrada:\n{image_path}")
            return
        image = Image.open(absolute_path)
        self.character_image = ctk.CTkImage(
            light_image=image, dark_image=image, size=(260, 260))
        self.character_label.configure(image=self.character_image, text="")

    def _on_close(self) -> None:
        if self.rpc_client is not None:
            self.rpc_client.close()
        self.destroy()

    def _show_game_end_window(self, message: str) -> None:
        if self.game_end_window is not None and self.game_end_window.winfo_exists():
            self.game_end_window.destroy()

        self.game_end_window = ctk.CTkToplevel(self)
        self.game_end_window.title("Fim de jogo")
        self.game_end_window.geometry("520x220")
        self.game_end_window.resizable(False, False)
        self.game_end_window.configure(fg_color=COLORS["bg"])
        self.game_end_window.grab_set()

        body = card(self.game_end_window)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Fim de jogo", style="heading", color=COLORS["warning"]).pack(
            anchor="w", padx=14, pady=(14, 8)
        )
        lbl(body, message, style="body", color=COLORS["text_secondary"],
            wraplength=460, justify="left").pack(anchor="w", padx=14, pady=(0, 12))

        btn(
            body,
            "Iniciar nova partida",
            self._restart_from_game_end,
        ).pack(fill="x", padx=14, pady=(0, 14))

    def _restart_from_game_end(self) -> None:
        if self.game_end_window is not None and self.game_end_window.winfo_exists():
            self.game_end_window.destroy()
        self.start_game()


if __name__ == "__main__":
    app = GuessingGameApp()
    app.mainloop()
