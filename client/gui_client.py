from __future__ import annotations

import os
import threading

import customtkinter as ctk
import grpc
from PIL import Image, ImageDraw, ImageOps

from grpc_client import GameRpcClient, game_pb2

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLORS = {
    "bg":           "#0c0e14",
    "surface":      "#13172a",
    "surface_alt":  "#191e33",
    "border":       "#252c46",
    "accent":       "#6b8ef0",
    "accent_dim":   "#4a6de0",
    "accent_muted": "#141c42",
    "text":         "#dde4f5",
    "text_sub":     "#8a93b8",
    "text_dim":     "#454e6e",
    "green":        "#5cb87c",
    "amber":        "#e5b54a",
    "red":          "#d96464",
    "gold":         "#e5b54a",
}

FONTS: dict = {}
BTN: dict = {}


def _init_theme() -> None:
    global FONTS, BTN
    FONTS = {
        "title":  ctk.CTkFont(family="Segoe UI", size=19, weight="bold"),
        "head":   ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        "body":   ctk.CTkFont(family="Segoe UI", size=13),
        "small":  ctk.CTkFont(family="Segoe UI", size=11),
        "mono":   ctk.CTkFont(family="Consolas",  size=12),
        "char":   ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
    }
    BTN = {
        "primary": dict(corner_radius=8, height=36, fg_color=COLORS["accent"],
                        hover_color=COLORS["accent_dim"], text_color=COLORS["text"], font=FONTS["body"]),
        "ghost":   dict(corner_radius=8, height=36, fg_color=COLORS["surface_alt"],
                        hover_color=COLORS["border"], text_color=COLORS["text_sub"], font=FONTS["body"],
                        border_width=1, border_color=COLORS["border"]),
        "success": dict(corner_radius=8, height=36, fg_color=COLORS["green"],
                        hover_color="#4aa068", text_color="#0c1a12", font=FONTS["body"]),
        "danger":  dict(corner_radius=8, height=36, fg_color=COLORS["red"],
                        hover_color="#b84444", text_color=COLORS["text"], font=FONTS["body"]),
        "amber":   dict(corner_radius=8, height=36, fg_color="#7a5c10",
                        hover_color="#956e12", text_color=COLORS["amber"], font=FONTS["body"],
                        border_width=1, border_color=COLORS["amber"]),
    }


def lbl(parent, text, style="body", color=None, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=FONTS.get(style, FONTS["body"]),
                        text_color=color or COLORS["text"], **kw)


def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10, **kw)


def btn(parent, text, command, style="primary", **kw) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, command=command, **{**BTN[style], **kw})


def modal(parent, title: str, geometry: str) -> ctk.CTkToplevel:
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.geometry(geometry)
    win.resizable(False, False)
    win.configure(fg_color=COLORS["bg"])
    win.transient(parent)
    win._modal_geometry = geometry
    return win


def show_modal(parent, win: ctk.CTkToplevel) -> None:
    win.update_idletasks()
    parent.update_idletasks()

    width = win.winfo_width()
    height = win.winfo_height()
    if width <= 1 or height <= 1:
        base_geometry = getattr(win, "_modal_geometry", "380x270").split("+", 1)[0]
        width_s, height_s = base_geometry.lower().split("x", 1)
        width = int(width_s)
        height = int(height_s)

    x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 2, 0)

    win.geometry(f"{width}x{height}+{x}+{y}")
    win.lift()
    win.focus_set()
    win.after(120, lambda: win.winfo_exists() and win.grab_set())


def sep(parent, row: int, col: int = 0, span: int = 4,
        padx=(12, 12), pady=(4, 4)) -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"])
    f.grid(row=row, column=col, columnspan=span, sticky="ew", padx=padx, pady=pady)
    return f


def _entry(parent, placeholder: str, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent, placeholder_text=placeholder,
        fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
        text_color=COLORS["text"], placeholder_text_color=COLORS["text_dim"],
        font=FONTS["body"], height=36, corner_radius=8, **kw,
    )


def _placeholder_img(size=(280, 280)) -> Image.Image:
    img = Image.new("RGBA", size, (25, 30, 51, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=14,
                            outline=(37, 44, 70, 255), width=2)
    cx, cy = size[0] // 2, size[1] // 2
    r = 28
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(69, 78, 110, 255), width=2)
    draw.line([cx, cy-r+8, cx, cy+r-8], fill=(69, 78, 110, 255), width=2)
    draw.line([cx-r+8, cy, cx+r-8, cy], fill=(69, 78, 110, 255), width=2)
    return img


def _fit_image_inside(img: Image.Image, size=(280, 280)) -> Image.Image:
    fitted = ImageOps.contain(img, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (25, 30, 51, 255))
    x = (size[0] - fitted.width) // 2
    y = (size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


class PlayerCard(ctk.CTkFrame):
    def __init__(self, parent, name: str, is_me: bool, is_owner: bool):
        bg = COLORS["accent_muted"] if is_me else COLORS["surface_alt"]
        super().__init__(parent, fg_color=bg, corner_radius=7)
        dot = COLORS["accent"] if is_me else COLORS["text_dim"]
        ctk.CTkLabel(self, text="●", font=FONTS["small"], text_color=dot,
                     width=16).pack(side="left", padx=(10, 6), pady=7)
        label = f"{name}  (eu)" if is_me else name
        color = COLORS["gold"] if is_owner else COLORS["text"]
        ctk.CTkLabel(self, text=label, font=FONTS["body"],
                     text_color=color).pack(side="left", pady=7)
        if is_owner:
            ctk.CTkLabel(self, text="dono", font=FONTS["small"],
                         text_color=COLORS["text_dim"]).pack(side="right", padx=(4, 10), pady=7)


class GuessingGameApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        _init_theme()

        self.title("Guessing Game · RPC")
        self.geometry("1200x720")
        self.minsize(980, 600)
        self.configure(fg_color=COLORS["bg"])
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Estado
        self.rpc_client: GameRpcClient | None = None
        self._streams_started = False
        self._leaving = False

        self.category_name = ""
        self.char_image: ctk.CTkImage | None = None
        self.current_turn_name = ""
        self.current_turn_id = ""
        self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
        self.players_by_name: dict[str, str] = {}
        self.can_guess_current_turn = False

        self.game_started = False
        self.voting_phase = False
        self.already_voted = False
        self.votes_continue = 0
        self.votes_end = 0
        self.votes_needed = 0
        self.responded = False
        self.room_owner_id = ""

        self.session_number = 0
        self.max_rounds = 1
        self.hint_cycle = 1
        self.max_hint_cycles = 3

        self._pending: dict[str, dict] = {}        # guess_id -> {guesser_name, guess_text}
        self._exchange_req_id = ""
        self._exchange_req_name = ""
        self._exchange_req_hint = ""
        self._exchange_win: ctk.CTkToplevel | None = None
        self._end_win: ctk.CTkToplevel | None = None

        # Layout raiz
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=220)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=260)

        self._build_topbar()
        self._build_left()
        self._build_center()
        self._build_right()
        self._set_connected(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # topbar
    def _build_topbar(self) -> None:
        tb = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=52)
        tb.grid(row=0, column=0, columnspan=3, sticky="ew")
        tb.grid_propagate(False)
        tb.grid_columnconfigure(1, weight=1)

        title_frame = ctk.CTkFrame(tb, fg_color="transparent")
        title_frame.grid(row=0, column=0, padx=(20, 0), pady=0, sticky="w")
        lbl(title_frame, "Guessing Game", style="title").pack(side="left")
        lbl(title_frame, "  RPC", style="small",
            color=COLORS["accent"]).pack(side="left", pady=(6, 0))

        login = ctk.CTkFrame(tb, fg_color="transparent")
        login.grid(row=0, column=2, padx=16, sticky="e")

        self.name_entry = ctk.CTkEntry(
            login, placeholder_text="Seu nome...", width=180, height=32,
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text"], placeholder_text_color=COLORS["text_dim"],
            font=FONTS["body"], corner_radius=8,
        )
        self.name_entry.grid(row=0, column=0, padx=(0, 8))
        self.name_entry.bind("<Return>", lambda _: self.join_game())

        self.join_btn = btn(login, "Entrar", self.join_game, width=88, height=32)
        self.join_btn.grid(row=0, column=1, padx=(0, 8))
        self.leave_btn = btn(login, "Sair", self.leave_game, style="ghost", width=72, height=32)
        self.leave_btn.grid(row=0, column=2)

        status = ctk.CTkFrame(tb, fg_color="transparent")
        status.grid(row=0, column=3, padx=(12, 20), sticky="e")
        self.conn_dot = lbl(status, "●", style="body", color=COLORS["text_dim"])
        self.conn_dot.pack(side="left", padx=(0, 4))
        self.conn_lbl = lbl(status, "Desconectado", style="small", color=COLORS["text_dim"])
        self.conn_lbl.pack(side="left")

    # painel esquerdo — Jogadores + Placar
    def _build_left(self) -> None:
        p = card(self)
        p.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=12)
        p.grid_rowconfigure(2, weight=2)
        p.grid_rowconfigure(5, weight=1)
        p.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(p, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)
        lbl(header, "Jogadores", style="head", color=COLORS["text_sub"]).grid(
            row=0, column=0, sticky="w")
        self.owner_lbl = lbl(header, "Dono: —", style="small", color=COLORS["text_dim"])
        self.owner_lbl.grid(row=0, column=1, sticky="e")
        sep(p, 1, padx=(10, 10), pady=(0, 6))

        self.players_frame = ctk.CTkScrollableFrame(
            p, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.players_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 6))

        sep(p, 3, padx=(10, 10), pady=(0, 4))
        lbl(p, "Placar", style="head", color=COLORS["text_sub"]).grid(
            row=4, column=0, sticky="w", padx=14, pady=(4, 4))

        self.scores_frame = ctk.CTkScrollableFrame(
            p, fg_color="transparent", height=100,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.scores_frame.grid(row=5, column=0, sticky="nsew", padx=8, pady=(0, 12))

    # painel central
    def _build_center(self) -> None:
        p = card(self)
        p.grid(row=1, column=1, sticky="nsew", padx=6, pady=12)
        p.grid_rowconfigure(3, weight=1)
        p.grid_columnconfigure(0, weight=1)

        # Linha de status
        status_row = ctk.CTkFrame(p, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        status_row.grid_columnconfigure(1, weight=1)

        badge_frame = ctk.CTkFrame(status_row, fg_color=COLORS["accent_muted"], corner_radius=6)
        badge_frame.grid(row=0, column=0, sticky="w")
        self.category_lbl = lbl(badge_frame, "Aguardando", style="small", color=COLORS["accent"])
        self.category_lbl.grid(padx=10, pady=4)

        self.session_lbl = lbl(status_row, "", style="small", color=COLORS["text_dim"])
        self.session_lbl.grid(row=0, column=1, padx=(12, 0), sticky="w")

        # Turno
        self.turn_lbl = lbl(p, "Aguardando inicio...", style="small", color=COLORS["text_dim"])
        self.turn_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        sep(p, 2, padx=(12, 12), pady=(0, 0))

        # Imagem
        img_card = ctk.CTkFrame(p, fg_color=COLORS["surface_alt"], corner_radius=12)
        img_card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(8, 6))
        img_card.grid_rowconfigure(0, weight=1)
        img_card.grid_columnconfigure(0, weight=1)

        self.char_img_lbl = ctk.CTkLabel(img_card, text="", width=280, height=280)
        self.char_img_lbl.grid(row=0, column=0, padx=24, pady=24)
        self._load_placeholder()

        # Nome do personagem
        char_row = ctk.CTkFrame(p, fg_color="transparent")
        char_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 4))
        char_row.grid_columnconfigure(1, weight=1)
        lbl(char_row, "Seu personagem:", style="small",
            color=COLORS["text_dim"]).grid(row=0, column=0, padx=(0, 8))
        self.char_name_lbl = lbl(char_row, "—", style="char", color=COLORS["text"])
        self.char_name_lbl.grid(row=0, column=1, sticky="w")

        sep(p, 5, padx=(12, 12), pady=(4, 6))

        # Ações primárias
        self.action_lbl = lbl(p, "Entre na partida para jogar.",
                               style="small", color=COLORS["text_dim"])
        self.action_lbl.grid(row=6, column=0, sticky="w", padx=16, pady=(0, 4))

        self.primary_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.primary_frame.grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 2))
        self.primary_frame.grid_columnconfigure(0, weight=1)
        self.primary_frame.grid_columnconfigure(1, weight=1)

        # Ações secundárias (exchange + spy)
        self.secondary_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.secondary_frame.grid(row=8, column=0, sticky="ew", padx=16, pady=(0, 4))
        self.secondary_frame.grid_columnconfigure(0, weight=1)
        self.secondary_frame.grid_columnconfigure(1, weight=1)

        # Painel de validação (só o dono vê)
        self.pending_frame = ctk.CTkScrollableFrame(
            p, fg_color=COLORS["surface_alt"], corner_radius=8, height=110,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
            label_text="Palpites aguardando validação",
            label_font=FONTS["small"],
            label_text_color=COLORS["amber"],
            label_fg_color=COLORS["surface_alt"],
        )
        self.pending_frame.grid(row=9, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.pending_frame.grid_columnconfigure(0, weight=1)
        self.pending_frame.grid_remove()

        # Widgets de ação
        self.start_btn     = btn(self.primary_frame, "Iniciar Partida", self.start_game)
        self.hint_btn      = btn(self.primary_frame, "Enviar Dica", self.send_hint)
        self.guess_entry   = _entry(self.primary_frame, "Seu palpite...")
        self.guess_btn     = btn(self.primary_frame, "Confirmar", self.submit_guess)
        self.pass_btn      = btn(self.primary_frame, "Passar", self.pass_opportunity, style="ghost")
        self.vote_yes_btn  = btn(self.primary_frame, "Continuar Jogando", self.vote_continue, style="success")
        self.vote_no_btn   = btn(self.primary_frame, "Encerrar Jogo",    self.vote_end,     style="danger")

        self.exchange_btn  = btn(self.secondary_frame, "Troca Privada",   self.open_exchange_dialog, style="ghost")
        self.spy_btn       = btn(self.secondary_frame, "Espionar Troca",  self.open_spy_dialog,      style="amber")

        self.guess_entry.bind("<Return>", lambda _: self.submit_guess())

    # painel direito — Eventos + Chat
    def _build_right(self) -> None:
        p = card(self)
        p.grid(row=1, column=2, sticky="nsew", padx=(6, 12), pady=12)
        p.grid_rowconfigure(1, weight=2)
        p.grid_rowconfigure(4, weight=1)
        p.grid_columnconfigure(0, weight=1)

        lbl(p, "Eventos", style="head", color=COLORS["text_sub"]).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 4))

        self.events_frame = ctk.CTkScrollableFrame(
            p, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.events_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 4))

        sep(p, 2, padx=(10, 10), pady=(4, 4))

        lbl(p, "Chat", style="head", color=COLORS["text_sub"]).grid(
            row=3, column=0, sticky="w", padx=14, pady=(6, 4))

        self.chat_frame = ctk.CTkScrollableFrame(
            p, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.chat_frame.grid(row=4, column=0, sticky="nsew", padx=6, pady=(0, 4))

        chat_input = ctk.CTkFrame(p, fg_color="transparent")
        chat_input.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 12))
        chat_input.grid_columnconfigure(0, weight=1)

        self.chat_entry = ctk.CTkEntry(
            chat_input, placeholder_text="Mensagem...",
            fg_color=COLORS["surface_alt"], border_color=COLORS["border"],
            text_color=COLORS["text"], placeholder_text_color=COLORS["text_dim"],
            font=FONTS["body"], height=32, corner_radius=8,
        )
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.chat_entry.bind("<Return>", lambda _: self.send_chat())

        btn(chat_input, "→", self.send_chat, width=36, height=32).grid(row=0, column=1)

    # conexão
    def join_game(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            self._log("Informe um nome antes de entrar.")
            return
        try:
            self.rpc_client = GameRpcClient()
            resp = self.rpc_client.join_game(name)
        except grpc.RpcError as e:
            self._log(f"Falha ao conectar: {e.details()}")
            return
        if not resp.success:
            self._log(f"Erro ao entrar: {resp.message}")
            return

        self.room_owner_id = resp.room_owner_id
        self._set_connected(True)
        self.conn_dot.configure(text_color=COLORS["green"])
        self.conn_lbl.configure(
            text=f"{name} · #{self.rpc_client.player_id[:8]}",
            text_color=COLORS["text_sub"],
        )
        self._refresh_players()
        self._update_actions()
        self._log(resp.message)
        if self.rpc_client.player_id == self.room_owner_id:
            self._log("Você é o dono da sala. Inicie quando todos estiverem prontos.")
        self._start_streams()

    def _start_streams(self) -> None:
        if self._streams_started or self.rpc_client is None:
            return
        self._streams_started = True
        threading.Thread(target=self._game_stream, daemon=True).start()
        threading.Thread(target=self._chat_stream, daemon=True).start()

    def _game_stream(self) -> None:
        try:
            for ev in self.rpc_client.subscribe_to_game_events():
                self.after(0, self._on_game_event, ev)
        except grpc.RpcError as e:
            if not self._leaving:
                self.after(0, self._log, f"Stream encerrado: {e.details()}")

    def _chat_stream(self) -> None:
        try:
            for ev in self.rpc_client.subscribe_to_chat_events():
                self.after(0, self._append_chat, f"{ev.player_name}: {ev.text}")
        except grpc.RpcError as e:
            if not self._leaving:
                self.after(0, self._append_chat, f"Chat encerrado: {e.details()}")

    # ações
    def start_game(self) -> None:
        win = modal(self, "Iniciar Partida", "380x270")

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Configurar partida", style="head").pack(anchor="w", padx=14, pady=(14, 10))

        row_r = ctk.CTkFrame(body, fg_color="transparent")
        row_r.pack(fill="x", padx=14, pady=(0, 8))
        row_r.grid_columnconfigure(1, weight=1)
        lbl(row_r, "Sessões:", style="small", color=COLORS["text_sub"]).grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        rounds_entry = ctk.CTkEntry(row_r, width=80, fg_color=COLORS["surface_alt"],
                                    border_color=COLORS["border"], text_color=COLORS["text"],
                                    font=FONTS["body"], height=34, corner_radius=8)
        rounds_entry.insert(0, "3")
        rounds_entry.grid(row=0, column=1, sticky="ew")

        row_t = ctk.CTkFrame(body, fg_color="transparent")
        row_t.pack(fill="x", padx=14, pady=(0, 4))
        row_t.grid_columnconfigure(1, weight=1)
        lbl(row_t, "Turnos/sessão:", style="small", color=COLORS["text_sub"]).grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        turns_entry = ctk.CTkEntry(row_t, width=80, fg_color=COLORS["surface_alt"],
                                   border_color=COLORS["border"], text_color=COLORS["text"],
                                   font=FONTS["body"], height=34, corner_radius=8)
        turns_entry.insert(0, "3")
        turns_entry.grid(row=0, column=1, sticky="ew")

        lbl(body, "Cada sessão usa uma categoria. Em cada turno todos dão uma dica.",
            style="small", color=COLORS["text_dim"], wraplength=320).pack(
            anchor="w", padx=14, pady=(0, 12))

        def confirm():
            try:
                r = int(rounds_entry.get().strip())
                t = int(turns_entry.get().strip())
                if r < 1 or t < 1:
                    raise ValueError
            except ValueError:
                return
            win.destroy()
            self._cmd("StartGame", lambda: self.rpc_client.start_game(r, t))

        turns_entry.bind("<Return>", lambda _: confirm())
        btn(body, "Iniciar Partida", confirm).pack(fill="x", padx=14, pady=(0, 14))
        show_modal(self, win)

    def send_hint(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Dica Pública")
        win.geometry("380x180")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        lbl(body, "Sua dica pública (uma palavra):", style="head").pack(
            anchor="w", padx=14, pady=(14, 8))

        entry = _entry(body, "Uma palavra sobre seu personagem...")
        entry.pack(fill="x", padx=14, pady=(0, 12))

        def confirm():
            hint = entry.get().strip()
            if not hint:
                return
            win.destroy()
            self._cmd("SendPublicHint", lambda: self.rpc_client.send_public_hint(hint))

        entry.bind("<Return>", lambda _: confirm())
        btn(body, "Enviar Dica", confirm).pack(fill="x", padx=14, pady=(0, 14))

    def submit_guess(self) -> None:
        guess = self.guess_entry.get().strip()
        if not guess:
            self._log("Digite um palpite antes de confirmar.")
            return
        owner_id = self.current_turn_id
        if not owner_id:
            return
        self.guess_entry.delete(0, "end")
        ok = self._cmd("SubmitGuess", lambda: self.rpc_client.submit_guess(owner_id, guess))
        if ok:
            self.responded = True
            self._update_actions()

    def pass_opportunity(self) -> None:
        ok = self._cmd("PassGuessOpportunity", lambda: self.rpc_client.pass_guess_opportunity())
        if ok:
            self.responded = True
            self._update_actions()

    def vote_continue(self) -> None:
        ok = self._cmd("VoteForNextRound", lambda: self.rpc_client.vote_for_next_round(True))
        if ok:
            self.already_voted = True
            self._update_actions()

    def vote_end(self) -> None:
        ok = self._cmd("VoteForNextRound", lambda: self.rpc_client.vote_for_next_round(False))
        if ok:
            self.already_voted = True
            self._update_actions()

    def leave_game(self) -> None:
        if self.rpc_client is None:
            self._reset_to_lobby()
            return
        self._leaving = True
        try:
            try:
                self.rpc_client.leave_game()
            except Exception:
                pass
            self.rpc_client.close()
        finally:
            self.rpc_client = None
            self._streams_started = False
            self._reset_to_lobby()
            self._set_connected(False)
            self._leaving = False

    def open_exchange_dialog(self) -> None:
        if self.rpc_client is None:
            return
        others = [p for p in self.rpc_client.players
                  if p.player_id != self.rpc_client.player_id]
        if not others:
            self._log("Não há outros jogadores para trocar dicas.")
            return
        self._show_exchange_dialog(others)

    def _show_exchange_dialog(self, others) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Troca de Dica Privada")
        win.geometry("420x260")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Solicitar troca de dica privada", style="head").pack(
            anchor="w", padx=14, pady=(14, 4))
        lbl(body, "Escolha com quem trocar e envie sua dica (uma palavra).",
            style="small", color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(0, 10))

        names = [p.name for p in others]
        target_var = ctk.StringVar(value=names[0])
        ctk.CTkOptionMenu(
            body, variable=target_var, values=names,
            fg_color=COLORS["surface_alt"], button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_dim"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"], font=FONTS["body"], corner_radius=8,
        ).pack(fill="x", padx=14, pady=(0, 8))

        hint_entry = _entry(body, "Sua dica privada (uma palavra)...")
        hint_entry.pack(fill="x", padx=14, pady=(0, 12))

        def confirm():
            target_id = next(
                (p.player_id for p in others if p.name == target_var.get()), "")
            hint = hint_entry.get().strip()
            if not target_id or not hint:
                return
            win.destroy()
            self._cmd("RequestHintExchange",
                      lambda: self.rpc_client.request_hint_exchange(target_id, hint))

        hint_entry.bind("<Return>", lambda _: confirm())
        btn(body, "Enviar Pedido", confirm).pack(fill="x", padx=14, pady=(0, 6))
        btn(body, "Cancelar", win.destroy, style="ghost").pack(fill="x", padx=14, pady=(0, 14))

    def open_spy_dialog(self) -> None:
        if self.rpc_client is None:
            return
        others = [p for p in self.rpc_client.players
                  if p.player_id != self.rpc_client.player_id]
        if len(others) < 2:
            self._log("São necessários pelo menos 2 outros jogadores para espionar.")
            return
        self._show_spy_dialog(others)

    def _show_spy_dialog(self, others) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Espionar Troca de Dicas")
        win.geometry("420x250")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Espionar troca de dicas", style="head").pack(
            anchor="w", padx=14, pady=(14, 4))
        lbl(body, "Escolha a dupla com uma solicitação de troca pendente.",
            style="small", color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(0, 10))

        names = [p.name for p in others]
        var_a = ctk.StringVar(value=names[0])
        var_b = ctk.StringVar(value=names[1] if len(names) > 1 else names[0])

        for var in (var_a, var_b):
            ctk.CTkOptionMenu(
                body, variable=var, values=names,
                fg_color=COLORS["surface_alt"], button_color=COLORS["accent"],
                button_hover_color=COLORS["accent_dim"],
                dropdown_fg_color=COLORS["surface"],
                dropdown_hover_color=COLORS["surface_alt"],
                text_color=COLORS["text"], font=FONTS["body"], corner_radius=8,
            ).pack(fill="x", padx=14, pady=(0, 6))

        def confirm():
            id_a = next((p.player_id for p in others if p.name == var_a.get()), "")
            id_b = next((p.player_id for p in others if p.name == var_b.get()), "")
            if not id_a or not id_b or id_a == id_b:
                self._log("Escolha dois jogadores diferentes.")
                return
            win.destroy()
            self._cmd("SpyOnExchange", lambda: self.rpc_client.spy_on_exchange(id_a, id_b))

        btn(body, "Espionar", confirm).pack(fill="x", padx=14, pady=(0, 6))
        btn(body, "Cancelar", win.destroy, style="ghost").pack(fill="x", padx=14, pady=(0, 14))

    def send_chat(self) -> None:
        text = self.chat_entry.get().strip()
        if not text:
            return
        self.chat_entry.delete(0, "end")
        self._cmd("SendChatMessage",
                  lambda: self.rpc_client.send_chat_message(text), silent=True)

    def _accept(self, guess_id: str) -> None:
        self._cmd("ValidateGuess", lambda: self.rpc_client.validate_guess(guess_id, True))

    def _reject(self, guess_id: str) -> None:
        self._cmd("ValidateGuess", lambda: self.rpc_client.validate_guess(guess_id, False))

    def _cmd(self, label: str, fn, silent: bool = False):
        if self.rpc_client is None:
            self._log("Entre na partida primeiro.")
            return False
        try:
            resp = fn()
        except grpc.RpcError as e:
            self._log(f"{label}: {e.details()}")
            return False
        if not resp.success:
            self._log(f"{resp.message}")
        elif not silent:
            self._log(resp.message)
        return resp.success

    # tratamento de eventos
    def _on_game_event(self, ev) -> None:
        if self._leaving:
            return
        t = ev.type

        if t in {game_pb2.PLAYER_JOINED, game_pb2.PLAYER_LEFT, game_pb2.TURN_STARTED} and ev.players:
            self._set_players(list(ev.players))

        if ev.room_owner_id:
            self.room_owner_id = ev.room_owner_id
            if self.rpc_client:
                self.rpc_client.room_owner_id = ev.room_owner_id
            self._update_owner_label()

        if ev.max_rounds > 0:
            self.max_rounds = ev.max_rounds
        if ev.session_number > 0:
            self.session_number = ev.session_number
        if ev.hint_cycle > 0:
            self.hint_cycle = ev.hint_cycle
            if ev.max_hint_cycles > 0:
                self.max_hint_cycles = ev.max_hint_cycles
        self._update_session_lbl()

        if t in {game_pb2.GAME_STARTED, game_pb2.NEW_ROUND_STARTED}:
            self.game_started = True
            self.voting_phase = False
            self.already_voted = False
            self.can_guess_current_turn = False
            self._pending.clear()
            self._refresh_pending()

        if t == game_pb2.ROUND_STARTED:
            self.game_started = True
            self.voting_phase = False
            self.already_voted = False
            self.can_guess_current_turn = False
            self.category_lbl.configure(text=ev.category_name or "—")
            self._load_placeholder()
            self.char_name_lbl.configure(text="—")
            self._pending.clear()
            self._refresh_pending()

        if t == game_pb2.CHARACTER_ASSIGNED:
            self.game_started = True
            if ev.image_path:
                self._load_image(ev.image_path)
            if ev.object_name:
                self.char_name_lbl.configure(text=ev.object_name)

        elif t in {game_pb2.TURN_STARTED, game_pb2.HINT_PHASE_STARTED,
                   game_pb2.GUESS_PHASE_STARTED}:
            eligible_ids = {p.player_id for p in ev.players}
            self.can_guess_current_turn = (
                t == game_pb2.GUESS_PHASE_STARTED
                and self.rpc_client is not None
                and self.rpc_client.player_id in eligible_ids
            )
            self.responded = (
                t == game_pb2.GUESS_PHASE_STARTED
                and not self.can_guess_current_turn
            )
            self.game_started = True
            self.current_turn_name = ev.current_turn_player_name
            self.current_turn_id = ev.current_turn_player_id
            self.turn_phase = ev.turn_phase
            is_mine = self.rpc_client and ev.current_turn_player_id == self.rpc_client.player_id
            suffix = " — sua vez" if is_mine else ""
            self.turn_lbl.configure(
                text=f"Turno de {ev.current_turn_player_name}{suffix}",
                text_color=COLORS["accent"] if is_mine else COLORS["text_dim"],
            )

        elif t == game_pb2.ROUND_ENDED:
            self.game_started = False
            self.can_guess_current_turn = False
            self.turn_lbl.configure(text="Sessão encerrada", text_color=COLORS["amber"])
            self._show_round_end(ev)

        elif t == game_pb2.VOTE_STARTED:
            self.voting_phase = True
            self.already_voted = False
            self.game_started = False
            self.can_guess_current_turn = False
            self.votes_continue = ev.votes_continue
            self.votes_end = ev.votes_end
            self.votes_needed = ev.votes_needed
            self.turn_lbl.configure(text="Votação em andamento", text_color=COLORS["amber"])

        elif t == game_pb2.VOTE_CAST:
            self.votes_continue = ev.votes_continue
            self.votes_end = ev.votes_end
            self.votes_needed = ev.votes_needed

        elif t == game_pb2.GAME_ENDED:
            self.game_started = False
            self.voting_phase = False
            self.votes_continue = 0
            self.votes_end = 0
            self.votes_needed = 0
            self.current_turn_id = ""
            self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
            self.responded = False
            self.can_guess_current_turn = False
            self.turn_lbl.configure(text="Partida encerrada", text_color=COLORS["text_dim"])
            self._show_game_end(ev)

        elif t == game_pb2.NEW_GAME_APPROVED:
            self.game_started = False
            self.voting_phase = False
            self.already_voted = False
            self.votes_continue = 0
            self.votes_end = 0
            self.votes_needed = 0
            self.current_turn_id = ""
            self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
            self.responded = False
            self.can_guess_current_turn = False
            self.turn_lbl.configure(text="Nova partida aprovada", text_color=COLORS["green"])

        elif t == game_pb2.PLAYER_LEFT:
            self._set_players(ev.players)
            if ev.room_owner_id:
                self.room_owner_id = ev.room_owner_id
                self._update_owner_label()

        elif t == game_pb2.PENDING_GUESS_FOR_OWNER:
            if self.rpc_client and ev.target_player_id == self.rpc_client.player_id:
                self._pending[ev.guess_id] = {
                    "guesser": ev.guesser_player_name,
                    "guess":   ev.guess_text,
                    "suggested": ev.accepted,
                }
                self._refresh_pending()

        elif t in {game_pb2.GUESS_ACCEPTED, game_pb2.GUESS_REJECTED}:
            self._pending.pop(ev.guess_id, None)
            self._refresh_pending()

        elif t == game_pb2.HINT_EXCHANGE_REQUESTED:
            if self.rpc_client and ev.target_player_id == self.rpc_client.player_id \
                    and ev.private_hint:
                self._exchange_req_id   = ev.actor_player_id
                self._exchange_req_name = self._name_by_id(ev.actor_player_id)
                self._exchange_req_hint = ev.private_hint
                self.after(100, self._show_exchange_response_window)

        self._update_actions()

        # Log de eventos
        color = None
        if t == game_pb2.PUBLIC_HINT_SENT and ev.public_hint:
            self._log_hint(ev.current_turn_player_name, ev.public_hint)
            if ev.scores:
                self._refresh_scores(ev.scores)
            return
        if t in {game_pb2.FINAL_RANKING, game_pb2.SCORE_UPDATED}:
            if ev.scores:
                self._refresh_scores(ev.scores)
            return
        if t == game_pb2.SPY_DISCOVERED:
            color = COLORS["red"]
        elif t == game_pb2.SPY_SUCCESSFUL:
            color = COLORS["green"]
        elif t in {game_pb2.EXCHANGE_COMPLETED, game_pb2.HINT_EXCHANGE_OCCURRED}:
            color = COLORS["amber"]
        elif t == game_pb2.GUESS_ACCEPTED:
            color = COLORS["green"]
        elif t == game_pb2.GUESS_REJECTED:
            color = COLORS["red"]
        elif t == game_pb2.PENDING_GUESS_FOR_OWNER:
            color = COLORS["amber"]

        if ev.message.strip():
            self._log(ev.message, color)

        if ev.scores:
            self._refresh_scores(ev.scores)

    # estado dos botões
    def _update_actions(self) -> None:
        self._hide_all()

        connected = self.rpc_client is not None and bool(self.rpc_client.player_id)
        if not connected:
            self.action_lbl.configure(text="Entre na partida para jogar.")
            return

        if self.voting_phase:
            vote_text = (
                f"Continuar {self.votes_continue}/{self.votes_needed} · "
                f"Encerrar {self.votes_end}/{self.votes_needed}"
            ) if self.votes_needed else "Votação em andamento"
            if self.already_voted:
                self.action_lbl.configure(text=f"{vote_text}. Aguardando decisão...")
            else:
                self.action_lbl.configure(text=f"Fim de sessão! {vote_text}")
                self._show(self.vote_yes_btn, self.primary_frame, 0, 0)
                self._show(self.vote_no_btn,  self.primary_frame, 0, 1)
            return

        if not self.game_started:
            is_owner = self.rpc_client.player_id == self.room_owner_id
            if is_owner:
                self.action_lbl.configure(text="Você é o dono. Inicie quando quiser.")
                self._show(self.start_btn, self.primary_frame, 0, 0, span=2)
            else:
                self.action_lbl.configure(text="Aguarde o dono iniciar a partida.")
            return

        is_mine = self.rpc_client.player_id == self.current_turn_id
        is_hint  = self.turn_phase == game_pb2.HINT
        is_post  = self.turn_phase == game_pb2.POST_HINT_GUESSES
        n_players = len(self.rpc_client.players) if self.rpc_client else 0

        if is_hint and is_mine:
            self.action_lbl.configure(text="Sua vez: envie uma dica pública sobre seu personagem.")
            self._show(self.hint_btn, self.primary_frame, 0, 0, span=2)
            self._show(self.exchange_btn, self.secondary_frame, 0, 0, span=2)

        elif is_post and not is_mine and self.can_guess_current_turn and not self.responded:
            self.action_lbl.configure(
                text=f"Tente adivinhar o personagem de {self.current_turn_name}:")
            self._show(self.guess_entry, self.primary_frame, 0, 0, span=2)
            self._show(self.guess_btn,   self.primary_frame, 1, 0)
            self._show(self.pass_btn,    self.primary_frame, 1, 1)
            if n_players >= 3:
                self._show(self.exchange_btn, self.secondary_frame, 0, 0)
                self._show(self.spy_btn,      self.secondary_frame, 0, 1)
            else:
                self._show(self.exchange_btn, self.secondary_frame, 0, 0, span=2)

        elif is_post and is_mine:
            self.action_lbl.configure(
                text="Aguardando palpites... Você pode usar a troca de dicas.")
            self._show(self.exchange_btn, self.secondary_frame, 0, 0, span=2)

        else:
            wait_msg = "Respondido. Aguardando os outros." if self.responded else "Aguarde o turno."
            if is_post and not is_mine and not self.can_guess_current_turn:
                wait_msg = "Você já acertou ou respondeu esta oportunidade. Aguarde o próximo turno."
            self.action_lbl.configure(text=wait_msg)
            if n_players >= 3:
                self._show(self.exchange_btn, self.secondary_frame, 0, 0)
                self._show(self.spy_btn,      self.secondary_frame, 0, 1)
            else:
                self._show(self.exchange_btn, self.secondary_frame, 0, 0, span=2)

    def _hide_all(self) -> None:
        for w in [self.start_btn, self.hint_btn, self.guess_entry,
                  self.guess_btn, self.pass_btn, self.vote_yes_btn, self.vote_no_btn,
                  self.exchange_btn, self.spy_btn]:
            w.grid_remove()
            try:
                w.configure(state="disabled")
            except Exception:
                pass

    @staticmethod
    def _show(w, frame, row: int, col: int, span: int = 1) -> None:
        px = (0, 4) if col == 0 and span == 1 else (0, 0)
        w.grid(in_=frame, row=row, column=col, columnspan=span,
               sticky="ew", padx=px, pady=3)
        try:
            w.configure(state="normal")
        except Exception:
            pass

    # painel de validação
    def _refresh_pending(self) -> None:
        for w in self.pending_frame.winfo_children():
            w.destroy()
        if not self._pending:
            self.pending_frame.grid_remove()
            return

        self.pending_frame.grid(row=9, column=0, sticky="ew", padx=16, pady=(0, 14))

        for gid, info in list(self._pending.items()):
            row_f = ctk.CTkFrame(self.pending_frame, fg_color=COLORS["surface"], corner_radius=6)
            row_f.pack(fill="x", pady=3, padx=2)
            row_f.grid_columnconfigure(0, weight=1)

            lbl(row_f,
                f"{info['guesser']}: \"{info['guess']}\"",
                style="small", color=COLORS["text"]).grid(
                row=0, column=0, sticky="w", padx=8, pady=(6, 2))
            suggestion = "Sugestão: bate com a lista de respostas." \
                if info.get("suggested") else "Sugestão: não bate com a lista cadastrada."
            lbl(row_f, suggestion, style="small", color=COLORS["text_dim"]).grid(
                row=1, column=0, sticky="w", padx=8, pady=(0, 4))

            btns_f = ctk.CTkFrame(row_f, fg_color="transparent")
            btns_f.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
            btns_f.grid_columnconfigure(0, weight=1)
            btns_f.grid_columnconfigure(1, weight=1)

            g = gid
            btn(btns_f, "Aceitar", lambda x=g: self._accept(x),
                style="success", height=28).grid(row=0, column=0, sticky="ew", padx=(0, 3))
            btn(btns_f, "Rejeitar", lambda x=g: self._reject(x),
                style="danger", height=28).grid(row=0, column=1, sticky="ew", padx=(3, 0))

    # janelas popup
    def _show_exchange_response_window(self) -> None:
        if self._exchange_win and self._exchange_win.winfo_exists():
            self._exchange_win.destroy()

        win = ctk.CTkToplevel(self)
        self._exchange_win = win
        win.title("Pedido de Troca de Dica")
        win.geometry("460x240")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Solicitação de troca privada", style="head",
            color=COLORS["amber"]).pack(anchor="w", padx=14, pady=(14, 4))
        lbl(body, f"{self._exchange_req_name} quer trocar dicas com você.",
            style="body", color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(0, 2))
        lbl(body, f"Dica deles:  \"{self._exchange_req_hint}\"",
            style="body", color=COLORS["accent"]).pack(anchor="w", padx=14, pady=(0, 10))

        hint_entry = _entry(body, "Sua dica de resposta (uma palavra)...")
        hint_entry.pack(fill="x", padx=14, pady=(0, 10))

        btns_f = ctk.CTkFrame(body, fg_color="transparent")
        btns_f.pack(fill="x", padx=14, pady=(0, 14))
        btns_f.grid_columnconfigure(0, weight=1)
        btns_f.grid_columnconfigure(1, weight=1)

        def accept():
            h = hint_entry.get().strip()
            if not h:
                return
            req_id = self._exchange_req_id
            win.destroy()
            self._cmd("RespondHintExchange",
                      lambda: self.rpc_client.respond_hint_exchange(req_id, True, h))

        def reject():
            req_id = self._exchange_req_id
            win.destroy()
            self._cmd("RespondHintExchange",
                      lambda: self.rpc_client.respond_hint_exchange(req_id, False))

        hint_entry.bind("<Return>", lambda _: accept())
        btn(btns_f, "Aceitar e Trocar", accept,
            style="success").grid(row=0, column=0, sticky="ew", padx=(0, 4))
        btn(btns_f, "Recusar", reject,
            style="danger").grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _show_round_end(self, ev) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Sessão Encerrada")
        win.geometry("520x480")
        win.resizable(True, True)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        title = "Limite de sessões atingido" if ev.is_final_session else "Sessão encerrada!"
        tc = COLORS["gold"] if ev.is_final_session else COLORS["amber"]
        lbl(body, title, style="head", color=tc).pack(anchor="w", padx=14, pady=(14, 10))

        if ev.character_reveals:
            lbl(body, "Personagens revelados:", style="small",
                color=COLORS["text_sub"]).pack(anchor="w", padx=14)
            for r in ev.character_reveals:
                lbl(body, f"  {r.player_name}  →  {r.character_name}",
                    style="body", color=COLORS["text"]).pack(anchor="w", padx=22)

        if ev.score_deltas:
            lbl(body, "Pontos nesta sessão:", style="small",
                color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(10, 0))
            for d in sorted(ev.score_deltas, key=lambda x: x.score, reverse=True):
                if d.score != 0:
                    sign = "+" if d.score > 0 else ""
                    c = COLORS["green"] if d.score > 0 else COLORS["red"]
                    lbl(body, f"  {d.player_name}: {sign}{d.score} pts",
                        style="body", color=c).pack(anchor="w", padx=22)

        if ev.scores:
            lbl(body, "Placar acumulado:", style="small",
                color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(10, 0))
            for i, s in enumerate(sorted(ev.scores, key=lambda x: x.score, reverse=True)):
                pos = ["1.", "2.", "3."][i] if i < 3 else f"{i+1}."
                c = COLORS["gold"] if i == 0 else COLORS["text"]
                lbl(body, f"  {pos} {s.player_name}: {s.score} pts",
                    style="body", color=c).pack(anchor="w", padx=22)

        nota = "Votação iniciada — decida se abre nova partida ou encerra." if ev.is_final_session \
            else "Votação iniciada — decida se continua ou encerra."
        lbl(body, nota, style="small",
            color=COLORS["text_dim"]).pack(anchor="w", padx=14, pady=(12, 4))
        btn(body, "Fechar", win.destroy, style="ghost").pack(
            fill="x", padx=14, pady=(0, 14))

    def _show_game_end(self, ev) -> None:
        if self._end_win and self._end_win.winfo_exists():
            self._end_win.destroy()

        win = ctk.CTkToplevel(self)
        self._end_win = win
        win.title("Fim de Jogo")
        win.geometry("500x400")
        win.resizable(True, True)
        win.configure(fg_color=COLORS["bg"])
        win.grab_set()

        body = card(win)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        lbl(body, "Fim de Jogo", style="head",
            color=COLORS["gold"]).pack(anchor="w", padx=14, pady=(14, 6))
        lbl(body, ev.message, style="body", color=COLORS["text_sub"],
            wraplength=440, justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        entries = ev.ranking or sorted(
            ev.scores, key=lambda s: s.score, reverse=True)

        if entries:
            lbl(body, "Ranking Final:", style="small",
                color=COLORS["text_sub"]).pack(anchor="w", padx=14, pady=(0, 4))
            for i, e in enumerate(entries):
                pos   = getattr(e, "position", i + 1)
                name  = getattr(e, "player_name", getattr(e, "player_name", "?"))
                score = getattr(e, "score", 0)
                pos_s = ["1.", "2.", "3."][pos-1] if pos <= 3 else f"{pos}."
                c = COLORS["gold"] if pos == 1 else COLORS["text"]
                lbl(body, f"  {pos_s} {name}: {score} pts",
                    style="body", color=c).pack(anchor="w", padx=22)

        btn(body, "Fechar", win.destroy, style="ghost").pack(
            fill="x", padx=14, pady=(14, 14))

    # helpers de ui
    def _update_session_lbl(self) -> None:
        if self.session_number > 0:
            self.session_lbl.configure(
                text=f"Sessão {self.session_number}/{self.max_rounds}  ·  "
                     f"Ciclo {self.hint_cycle}/{self.max_hint_cycles}")

    def _log(self, text: str, color: str | None = None) -> None:
        if not text.strip():
            return
        row = ctk.CTkFrame(self.events_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="›", font=FONTS["body"],
                     text_color=COLORS["accent"], width=12).pack(side="left", padx=(2, 6))
        ctk.CTkLabel(row, text=text, font=FONTS["small"],
                     text_color=color or COLORS["text_sub"],
                     anchor="w", justify="left", wraplength=215).pack(
            side="left", fill="x", expand=True)
        try:
            self.events_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _log_hint(self, player: str, hint: str) -> None:
        row = ctk.CTkFrame(self.events_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text="›", font=FONTS["body"],
                     text_color=COLORS["accent"], width=12).pack(side="left", padx=(2, 6))
        ctk.CTkLabel(row, text=f"{player}: ",
                     font=FONTS["small"], text_color=COLORS["text_sub"],
                     anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=hint,
                     font=FONTS["small"], text_color=COLORS["accent"],
                     anchor="w").pack(side="left", fill="x", expand=True)
        try:
            self.events_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _append_chat(self, text: str) -> None:
        if not text.strip():
            return
        ctk.CTkLabel(self.chat_frame, text=text, font=FONTS["small"],
                     text_color=COLORS["text_sub"],
                     anchor="w", justify="left", wraplength=220).pack(
            fill="x", padx=6, pady=1)
        try:
            self.chat_frame._parent_canvas.yview_moveto(1.0)
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
        for w in self.players_frame.winfo_children():
            w.destroy()
        for p in players:
            PlayerCard(
                self.players_frame,
                name=p.name,
                is_me=(p.player_id == self.rpc_client.player_id),
                is_owner=(p.player_id == self.room_owner_id),
            ).pack(fill="x", pady=3, padx=4)
        self._update_owner_label()

    def _update_owner_label(self) -> None:
        owner_name = "—"
        players = self.rpc_client.players if self.rpc_client else []
        for p in players:
            if p.player_id == self.room_owner_id:
                owner_name = p.name
                break
        if hasattr(self, "owner_lbl"):
            self.owner_lbl.configure(text=f"Dono: {owner_name}")

    def _refresh_scores(self, scores) -> None:
        for w in self.scores_frame.winfo_children():
            w.destroy()
        for i, s in enumerate(sorted(scores, key=lambda x: x.score, reverse=True)):
            pos = ["1.", "2.", "3."][i] if i < 3 else f"{i+1}."
            c = COLORS["gold"] if i == 0 else COLORS["text_sub"]
            ctk.CTkLabel(self.scores_frame,
                         text=f"{pos} {s.player_name}: {s.score}",
                         font=FONTS["small"], text_color=c,
                         anchor="w").pack(fill="x", padx=6, pady=1)

    def _set_connected(self, connected: bool) -> None:
        self.name_entry.configure(state="disabled" if connected else "normal")
        self.join_btn.configure(state="disabled" if connected else "normal")
        self.leave_btn.configure(state="normal" if connected else "disabled")
        self.chat_entry.configure(state="normal" if connected else "disabled")
        if not connected:
            self.conn_dot.configure(text_color=COLORS["text_dim"])
            self.conn_lbl.configure(text="Desconectado", text_color=COLORS["text_dim"])
        self._update_actions()

    def _reset_to_lobby(self) -> None:
        self.category_name = ""
        self.current_turn_name = ""
        self.current_turn_id = ""
        self.turn_phase = game_pb2.TURN_PHASE_UNKNOWN
        self.players_by_name = {}
        self.game_started = False
        self.voting_phase = False
        self.already_voted = False
        self.votes_continue = 0
        self.votes_end = 0
        self.votes_needed = 0
        self.responded = False
        self.room_owner_id = ""
        self.can_guess_current_turn = False
        self.session_number = 0
        self.max_rounds = 1
        self.hint_cycle = 1
        self.max_hint_cycles = 3
        self._pending.clear()
        for frame in (self.players_frame, self.scores_frame, self.pending_frame):
            for w in frame.winfo_children():
                w.destroy()
        self.pending_frame.grid_remove()
        self.category_lbl.configure(text="Aguardando")
        self.session_lbl.configure(text="")
        self.turn_lbl.configure(text="Aguardando início...", text_color=COLORS["text_dim"])
        self.char_name_lbl.configure(text="—")
        self._load_placeholder()
        self.action_lbl.configure(text="Entre na partida para jogar.")
        self.guess_entry.delete(0, "end")
        self._update_owner_label()

    def _load_placeholder(self) -> None:
        img = _placeholder_img((280, 280))
        self.char_image = ctk.CTkImage(light_image=img, dark_image=img, size=(280, 280))
        self.char_img_lbl.configure(image=self.char_image, text="")

    def _load_image(self, path: str) -> None:
        full = os.path.join(PROJECT_ROOT, path)
        if not os.path.exists(full):
            self.char_img_lbl.configure(image=None,
                                        text=f"Imagem não encontrada:\n{path}")
            return
        try:
            img = Image.open(full).convert("RGBA")
            img = _fit_image_inside(img, (280, 280))
            self.char_image = ctk.CTkImage(light_image=img, dark_image=img, size=(280, 280))
            self.char_img_lbl.configure(image=self.char_image, text="")
        except Exception as e:
            self.char_img_lbl.configure(image=None, text=f"Erro ao carregar imagem:\n{e}")

    def _name_by_id(self, pid: str) -> str:
        if self.rpc_client:
            for p in self.rpc_client.players:
                if p.player_id == pid:
                    return p.name
        return pid[:8]

    def _on_close(self) -> None:
        if self.rpc_client:
            self.leave_game()
        self.destroy()


if __name__ == "__main__":
    app = GuessingGameApp()
    app.mainloop()
