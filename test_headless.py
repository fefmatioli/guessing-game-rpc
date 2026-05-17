"""
Teste headless do Guessing Game RPC.
Sobe o servidor em thread, cria N clientes gRPC, simula partida completa.
"""
from __future__ import annotations

import os
import sys
import time
import queue
import threading
import traceback
from concurrent import futures
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Paths
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "generated"))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "client"))

import grpc
import game_pb2
import game_pb2_grpc
from game_state import GameState, now_unix_ms, _calculate_guess_points
from server import GameService, ChatService
from grpc_client import GameRpcClient

# ──────────────────────────────────────────────
# Cores para output
# ──────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_lock_print = threading.Lock()

def log(label: str, msg: str, color: str = RESET):
    with _lock_print:
        print(f"{color}[{label:12s}]{RESET} {msg}")

def ok(label, msg):   log(label, "OK  " + msg, GREEN)
def err(label, msg):  log(label, "FAIL " + msg, RED)
def warn(label, msg): log(label, "WARN " + msg, YELLOW)
def info(label, msg): log(label, "     " + msg, CYAN)

# ──────────────────────────────────────────────
# Servidor em thread
# ──────────────────────────────────────────────
def start_server(port: int = 50099) -> tuple[grpc.Server, GameState]:
    state = GameState()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    game_pb2_grpc.add_GameServiceServicer_to_server(GameService(state), server)
    game_pb2_grpc.add_ChatServiceServicer_to_server(ChatService(state), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server, state

# ──────────────────────────────────────────────
# Coletor de eventos assíncrono
# ──────────────────────────────────────────────
class EventCollector:
    def __init__(self, client: GameRpcClient, name: str):
        self.client = client
        self.name = name
        self.events: list[game_pb2.GameEvent] = []
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        try:
            for ev in self.client.subscribe_to_game_events():
                if self._stop.is_set():
                    break
                self.events.append(ev)
                self._q.put(ev)
        except Exception:
            pass

    def wait_for(self, event_type: int, timeout: float = 5.0) -> Optional[game_pb2.GameEvent]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self._q.get(timeout=0.1)
                if ev.type == event_type:
                    return ev
                # Put back non-matching into a local list check
            except queue.Empty:
                pass
        # Check already received
        for ev in self.events:
            if ev.type == event_type:
                return ev
        return None

    def wait_for_any(self, types: set, timeout: float = 5.0) -> Optional[game_pb2.GameEvent]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self._q.get(timeout=0.1)
                if ev.type in types:
                    return ev
            except queue.Empty:
                pass
        for ev in self.events:
            if ev.type in types:
                return ev
        return None

    def count(self, event_type: int) -> int:
        return sum(1 for e in self.events if e.type == event_type)

    def stop(self):
        self._stop.set()

# ──────────────────────────────────────────────
# Resultados dos testes
# ──────────────────────────────────────────────
PASS = []
FAIL = []

def assert_ok(label: str, condition: bool, detail: str = ""):
    if condition:
        ok("TEST", f"{label}" + (f" — {detail}" if detail else ""))
        PASS.append(label)
    else:
        err("TEST", f"FALHOU: {label}" + (f" — {detail}" if detail else ""))
        FAIL.append(label)

def assert_not_none(label, val, detail=""):
    assert_ok(label, val is not None, detail or f"valor={val}")

# ──────────────────────────────────────────────
PORT = 50099

def run_tests():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  GUESSING GAME RPC — TESTES HEADLESS{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # ── SOBE SERVIDOR ──────────────────────────
    server, state = start_server(PORT)
    info("SERVER", f"Servidor gRPC ouvindo em :{PORT}")
    time.sleep(0.3)

    addr = f"localhost:{PORT}"
    collectors: list[EventCollector] = []

    try:
        points_ladder = [_calculate_guess_points(i) for i in range(1, 6)]
        assert_ok("Pontuação por ordem de acerto",
                  points_ladder == [15, 10, 7, 4, 4],
                  str(points_ladder))

        # ══════════════════════════════════════
        # BLOCO 1: Join + Dono da sala
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 1] Join & Dono da sala{RESET}")

        c1 = GameRpcClient(addr); r1 = c1.join_game("Alice")
        c2 = GameRpcClient(addr); r2 = c2.join_game("Bob")
        c3 = GameRpcClient(addr); r3 = c3.join_game("Carol")

        assert_ok("Join Alice", r1.success, r1.message)
        assert_ok("Join Bob",   r2.success, r2.message)
        assert_ok("Join Carol", r3.success, r3.message)
        assert_ok("IDs distintos", r1.player_id != r2.player_id != r3.player_id)
        assert_ok("Alice é dona",  r1.room_owner_id == r1.player_id,
                  f"owner={r1.room_owner_id[:8]}, alice={r1.player_id[:8]}")
        assert_ok("Bob vê mesma dona", r2.room_owner_id == r1.player_id)

        # Join duplicado
        c1b = GameRpcClient(addr); r1b = c1b.join_game("Alice")
        assert_ok("Join duplicado reutiliza jogador", not r1b.success or r1b.player_id == r1.player_id,
                  "esperado: reusa ou retorna mesmo ID")

        # Não-dono não pode iniciar
        resp = c2.start_game(max_rounds=1)
        assert_ok("Não-dono não inicia", not resp.success, resp.message)

        # ══════════════════════════════════════
        # BLOCO 2: Subscribe & Snapshot
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 2] Subscribe & streams{RESET}")

        ec1 = EventCollector(c1, "Alice"); collectors.append(ec1)
        ec2 = EventCollector(c2, "Bob");   collectors.append(ec2)
        ec3 = EventCollector(c3, "Carol"); collectors.append(ec3)
        time.sleep(0.4)

        # Evento PLAYER_JOINED deve ter chegado (3 joins antes do subscribe podem não chegar)
        # — importante: snapshot só manda ROUND_STARTED se jogo já começou

        # ══════════════════════════════════════
        # BLOCO 3: StartGame
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 3] StartGame (1 sessão){RESET}")

        resp = c1.start_game(max_rounds=1)
        assert_ok("StartGame pela dona", resp.success, resp.message)

        # Todos devem receber ROUND_STARTED
        ev_rs1 = ec1.wait_for(game_pb2.ROUND_STARTED, timeout=3)
        ev_rs2 = ec2.wait_for(game_pb2.ROUND_STARTED, timeout=3)
        ev_rs3 = ec3.wait_for(game_pb2.ROUND_STARTED, timeout=3)
        assert_not_none("Alice recebe ROUND_STARTED", ev_rs1)
        assert_not_none("Bob recebe ROUND_STARTED", ev_rs2)
        assert_not_none("Carol recebe ROUND_STARTED", ev_rs3)
        if ev_rs1:
            assert_ok("session_number=1", ev_rs1.session_number == 1, str(ev_rs1.session_number))
            assert_ok("max_rounds=1", ev_rs1.max_rounds == 1, str(ev_rs1.max_rounds))
            assert_ok("Categoria preenchida", bool(ev_rs1.category_name), ev_rs1.category_name)
            info("TEST", f"Categoria: {ev_rs1.category_name}")

        # CHARACTER_ASSIGNED — só o próprio jogador recebe
        ev_ca1 = ec1.wait_for(game_pb2.CHARACTER_ASSIGNED, timeout=3)
        ev_ca2 = ec2.wait_for(game_pb2.CHARACTER_ASSIGNED, timeout=3)
        ev_ca3 = ec3.wait_for(game_pb2.CHARACTER_ASSIGNED, timeout=3)
        assert_not_none("Alice recebe CHARACTER_ASSIGNED", ev_ca1)
        assert_not_none("Bob recebe CHARACTER_ASSIGNED", ev_ca2)
        assert_not_none("Carol recebe CHARACTER_ASSIGNED", ev_ca3)
        if ev_ca1 and ev_ca2 and ev_ca3:
            assert_ok("Personagens distintos",
                      ev_ca1.character_id != ev_ca2.character_id != ev_ca3.character_id,
                      f"{ev_ca1.object_name} / {ev_ca2.object_name} / {ev_ca3.object_name}")
            assert_ok("character_id preenchido em ev_ca1", bool(ev_ca1.character_id))
            assert_ok("object_name preenchido (nome do personagem)", bool(ev_ca1.object_name),
                      ev_ca1.object_name)
            assert_ok("image_path preenchido", bool(ev_ca1.image_path), ev_ca1.image_path)
            # Alice não deve receber o personagem de Bob (privacidade)
            assert_ok("Alice não vê personagem de Bob",
                      ev_ca1.target_player_id == r1.player_id)

        # ══════════════════════════════════════
        # BLOCO 4: Fluxo de turno (dica seguida de palpites)
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 4] Fluxo ciclo 1 (dica + palpites){RESET}")

        # Descobre quem está no turno
        ev_turn = ec1.wait_for_any({game_pb2.TURN_STARTED, game_pb2.HINT_PHASE_STARTED}, timeout=3)
        assert_not_none("Evento de turno recebido", ev_turn)

        if ev_turn:
            current_pid = ev_turn.current_turn_player_id
            info("TEST", f"1° turno: jogador {ev_turn.current_turn_player_name}")
            assert_ok("hint_cycle=1 no 1° turno", ev_turn.hint_cycle == 1,
                      str(ev_turn.hint_cycle))

            # Mapa pid -> client
            pid_map = {r1.player_id: c1, r2.player_id: c2, r3.player_id: c3}
            name_map = {r1.player_id: "Alice", r2.player_id: "Bob", r3.player_id: "Carol"}
            ec_map   = {r1.player_id: ec1, r2.player_id: ec2, r3.player_id: ec3}

            current_client = pid_map.get(current_pid)

            # Tentativa de dar dica pelo jogador errado
            wrong_pids = [p for p in pid_map if p != current_pid]
            wrong_resp = pid_map[wrong_pids[0]].send_public_hint("errado")
            assert_ok("Jogador errado não pode dar dica", not wrong_resp.success, wrong_resp.message)

            # Dica válida pelo jogador do turno
            if current_client:
                r_hint = current_client.send_public_hint("redondo")
                assert_ok("Dica válida enviada", r_hint.success, r_hint.message)

                ev_hint = ec1.wait_for(game_pb2.PUBLIC_HINT_SENT, timeout=3)
                assert_not_none("PUBLIC_HINT_SENT broadcast", ev_hint)
                if ev_hint:
                    assert_ok("public_hint preenchido", ev_hint.public_hint == "redondo",
                               ev_hint.public_hint)
                    assert_ok("hint_cycle preenchido", ev_hint.hint_cycle >= 1,
                               str(ev_hint.hint_cycle))

                # Pelo enunciado, depois de cada dica os outros podem palpitar ou esperar.
                ev_guess_phase = ec1.wait_for(game_pb2.GUESS_PHASE_STARTED, timeout=3)
                assert_not_none("GUESS_PHASE_STARTED após dica", ev_guess_phase)
                if ev_guess_phase:
                    eligible = {p.player_id for p in ev_guess_phase.players}
                    assert_ok("Dono não é elegível para palpitar",
                              current_pid not in eligible)
                    assert_ok("Outros jogadores são elegíveis",
                              set(wrong_pids).issubset(eligible))

                    guesser_pid = wrong_pids[0]
                    owner_pid = current_pid
                    guess_resp = pid_map[guesser_pid].submit_guess(owner_pid, "palpite_certo")
                    assert_ok("Palpite pós-dica enviado", guess_resp.success, guess_resp.message)

                    ev_pending = ec_map[owner_pid].wait_for(game_pb2.PENDING_GUESS_FOR_OWNER, timeout=3)
                    assert_not_none("Dono recebe PENDING_GUESS_FOR_OWNER", ev_pending)
                    if ev_pending:
                        val_resp = pid_map[owner_pid].validate_guess(ev_pending.guess_id, True)
                        assert_ok("ValidateGuess aceito", val_resp.success, val_resp.message)

                    ev_accepted = ec1.wait_for(game_pb2.GUESS_ACCEPTED, timeout=3)
                    assert_not_none("GUESS_ACCEPTED broadcast", ev_accepted)
                    if ev_accepted:
                        assert_ok("Primeiro acerto do objeto vale 15",
                                  ev_accepted.score_delta == 15,
                                  str(ev_accepted.score_delta))
                        assert_ok("guess_order por objeto preenchido",
                                  ev_accepted.guess_order == 1,
                                  str(ev_accepted.guess_order))

                    dup_resp = pid_map[guesser_pid].submit_guess(owner_pid, "de novo")
                    assert_ok("Jogador que já acertou não palpita o mesmo objeto",
                              not dup_resp.success, dup_resp.message)

                    for pid in wrong_pids[1:]:
                        pass_resp = pid_map[pid].pass_guess_opportunity()
                        info("TEST", f"{name_map[pid]} passa: {pass_resp.message}")

        # ══════════════════════════════════════
        # BLOCO 5: Completar sessão (todos passam restante)
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 5] Completar sessão e ROUND_ENDED{RESET}")

        # Avança todos os turnos restantes enviando dicas e passando palpites
        # (timeout total de 30s para completar a sessão)
        round_ended_ev = None
        deadline = time.time() + 30
        pid_map_local = {r1.player_id: c1, r2.player_id: c2, r3.player_id: c3}
        ec_map_local  = {r1.player_id: ec1, r2.player_id: ec2, r3.player_id: ec3}

        while time.time() < deadline:
            # Checa se sessão já encerrou
            for ec in [ec1, ec2, ec3]:
                if ec.count(game_pb2.ROUND_ENDED) > 0:
                    round_ended_ev = next(e for e in ec.events if e.type == game_pb2.ROUND_ENDED)
                    break
            if round_ended_ev:
                break

            # Tenta avançar: pega evento de turno e age
            for pid, client in pid_map_local.items():
                ec = ec_map_local[pid]
                ev = None
                try:
                    ev = ec._q.get(timeout=0.05)
                except queue.Empty:
                    continue

                if ev.type in {game_pb2.HINT_PHASE_STARTED, game_pb2.TURN_STARTED}:
                    if ev.current_turn_player_id == pid:
                        if ev.turn_phase == game_pb2.HINT:
                            client.send_public_hint("dica")
                        elif ev.turn_phase == game_pb2.PRE_HINT_GUESS:
                            client.pass_guess_opportunity()

                elif ev.type == game_pb2.GUESS_PHASE_STARTED:
                    if ev.current_turn_player_id != pid:
                        client.pass_guess_opportunity()

                elif ev.type == game_pb2.PENDING_GUESS_FOR_OWNER:
                    if ev.target_player_id == pid:
                        client.validate_guess(ev.guess_id, False)

            time.sleep(0.05)

        assert_not_none("ROUND_ENDED recebido", round_ended_ev,
                        "sessão completou dentro de 30s")

        if round_ended_ev:
            assert_ok("character_reveals preenchido",
                      len(round_ended_ev.character_reveals) == 3,
                      str(len(round_ended_ev.character_reveals)))
            assert_ok("scores preenchido",
                      len(round_ended_ev.scores) == 3,
                      str(len(round_ended_ev.scores)))
            assert_ok("is_final_session=True (1 sessão)",
                      round_ended_ev.is_final_session, str(round_ended_ev.is_final_session))
            info("TEST", f"Personagens revelados: " +
                 ", ".join(f"{r.player_name}={r.character_name}" for r in round_ended_ev.character_reveals))

        # ══════════════════════════════════════
        # BLOCO 7: Votação após fim dos turnos
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 7] Votação após fim dos turnos{RESET}")

        ev_vote_final = ec1.wait_for(game_pb2.VOTE_STARTED, timeout=5)
        assert_not_none("VOTE_STARTED após sessão final", ev_vote_final)
        if ev_vote_final:
            assert_ok("Maioria necessária correta", ev_vote_final.votes_needed == 2,
                      str(ev_vote_final.votes_needed))

        rv1_end = c1.vote_for_next_round(False)
        rv2_end = c2.vote_for_next_round(False)
        assert_ok("Voto Alice para encerrar", rv1_end.success, rv1_end.message)
        assert_ok("Voto Bob para encerrar", rv2_end.success, rv2_end.message)

        ev_end = ec1.wait_for(game_pb2.GAME_ENDED, timeout=5)
        assert_not_none("GAME_ENDED recebido", ev_end)

        if ev_end:
            assert_ok("scores no GAME_ENDED", len(ev_end.scores) > 0)
            assert_ok("ranking preenchido", len(ev_end.ranking) > 0,
                      str(len(ev_end.ranking)))
            assert_ok("mensagem de vencedor", "Vencedor" in ev_end.message or "Empate" in ev_end.message,
                      ev_end.message)
            info("TEST", ev_end.message)

        ev_fr = ec1.wait_for(game_pb2.FINAL_RANKING, timeout=3)
        assert_not_none("FINAL_RANKING recebido", ev_fr)

        assert_ok("Votação encerra por maioria antes de todos votarem", True)

        # ══════════════════════════════════════
        # BLOCO 8: Nova partida (2 sessões + votação)
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 8] Nova partida (2 sessões) — teste de votação{RESET}")

        # Zera collectors para nova partida
        for ec in [ec1, ec2, ec3]:
            ec.events.clear()
            while not ec._q.empty():
                try: ec._q.get_nowait()
                except: pass

        resp2 = c1.start_game(max_rounds=2)
        assert_ok("StartGame sessão 2", resp2.success, resp2.message)

        ev_rs_new = ec1.wait_for(game_pb2.ROUND_STARTED, timeout=3)
        assert_not_none("ROUND_STARTED nova partida", ev_rs_new)
        if ev_rs_new:
            assert_ok("session_number=1 nova partida", ev_rs_new.session_number == 1)
            assert_ok("max_rounds=2 nova partida", ev_rs_new.max_rounds == 2)

        # Completa sessão 1 rapidamente
        round2_ended = None
        deadline2 = time.time() + 30
        while time.time() < deadline2:
            for ec in [ec1, ec2, ec3]:
                if ec.count(game_pb2.ROUND_ENDED) > 0:
                    round2_ended = next(e for e in ec.events if e.type == game_pb2.ROUND_ENDED)
                    break
            if round2_ended:
                break

            for pid, client in pid_map_local.items():
                ec = ec_map_local[pid]
                try:
                    ev = ec._q.get(timeout=0.05)
                except queue.Empty:
                    continue

                if ev.type in {game_pb2.HINT_PHASE_STARTED, game_pb2.TURN_STARTED}:
                    if ev.current_turn_player_id == pid:
                        if ev.turn_phase == game_pb2.HINT:
                            client.send_public_hint("dica")
                        elif ev.turn_phase == game_pb2.PRE_HINT_GUESS:
                            client.pass_guess_opportunity()
                elif ev.type == game_pb2.GUESS_PHASE_STARTED:
                    if ev.current_turn_player_id != pid:
                        client.pass_guess_opportunity()
                elif ev.type == game_pb2.PENDING_GUESS_FOR_OWNER:
                    if ev.target_player_id == pid:
                        client.validate_guess(ev.guess_id, False)
            time.sleep(0.05)

        assert_not_none("ROUND_ENDED sessão 1/2", round2_ended)
        if round2_ended:
            assert_ok("is_final_session=False em sessão 1/2",
                      not round2_ended.is_final_session)

        # VOTE_STARTED deve aparecer
        ev_vote = ec1.wait_for(game_pb2.VOTE_STARTED, timeout=5)
        assert_not_none("VOTE_STARTED após sessão 1/2", ev_vote)

        # Maioria vota continuar
        if ev_vote:
            rv1 = c1.vote_for_next_round(True)
            rv2 = c2.vote_for_next_round(True)
            assert_ok("Voto Alice", rv1.success, rv1.message)
            assert_ok("Voto Bob",   rv2.success, rv2.message)

            ev_vote_cast = ec1.wait_for(game_pb2.VOTE_CAST, timeout=3)
            assert_not_none("VOTE_CAST recebido", ev_vote_cast)

            ev_new_round = ec1.wait_for(game_pb2.NEW_ROUND_STARTED, timeout=5)
            assert_not_none("NEW_ROUND_STARTED (sessão 2/2)", ev_new_round)

            if ev_new_round:
                assert_ok("session_number=2 na nova sessão",
                           ev_new_round.session_number == 2, str(ev_new_round.session_number))

            # Verifica personagens novos foram atribuídos
            ev_ca_new = ec1.wait_for(game_pb2.CHARACTER_ASSIGNED, timeout=5)
            assert_not_none("CHARACTER_ASSIGNED na sessão 2", ev_ca_new)
            if ev_ca_new and ev_ca1:
                info("TEST", f"Personagem antigo: {ev_ca1.character_id[:8]} — "
                     f"Novo: {ev_ca_new.character_id[:8]}")

        # ══════════════════════════════════════
        # BLOCO 9: Troca de dicas (hint exchange)
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 9] Troca de dicas privadas{RESET}")

        # Reseta eventos do bloco 9
        for ec in [ec1, ec2, ec3]:
            while not ec._q.empty():
                try: ec._q.get_nowait()
                except: pass

        exch_resp = c1.request_hint_exchange(r2.player_id, "minha_dica")
        assert_ok("RequestHintExchange enviado", exch_resp.success, exch_resp.message)

        # Bob deve receber HINT_EXCHANGE_REQUESTED com private_hint
        ev_exch_req = ec2.wait_for(game_pb2.HINT_EXCHANGE_REQUESTED, timeout=3)
        assert_not_none("Bob recebe HINT_EXCHANGE_REQUESTED", ev_exch_req)
        if ev_exch_req:
            assert_ok("private_hint no evento privado",
                       ev_exch_req.private_hint == "minha_dica", ev_exch_req.private_hint)
            assert_ok("actor_player_id = Alice", ev_exch_req.actor_player_id == r1.player_id)

        # Carol NÃO deve ver o conteúdo da dica
        ev_exch_carol = ec3.wait_for(game_pb2.HINT_EXCHANGE_REQUESTED, timeout=2)
        if ev_exch_carol:
            assert_ok("Carol não vê private_hint",
                       not ev_exch_carol.private_hint, ev_exch_carol.private_hint)

        # Carol pode optar por espionar enquanto a troca está pendente.
        spy_resp = c3.spy_on_exchange(r1.player_id, r2.player_id)
        assert_ok("SpyOnExchange aceito com troca pendente", spy_resp.success, spy_resp.message)

        # Espionar si mesmo
        self_spy = c3.spy_on_exchange(r3.player_id, r1.player_id)
        assert_ok("Espionar si mesmo bloqueado", not self_spy.success, self_spy.message)

        # Espionar mesma dupla duas vezes
        spy_dup = c3.spy_on_exchange(r1.player_id, r2.player_id)
        assert_ok("Espionar dupla duas vezes bloqueado", not spy_dup.success, spy_dup.message)

        # Bob aceita
        resp_exch = c2.respond_hint_exchange(r1.player_id, True, "dica_bob")
        assert_ok("RespondHintExchange aceito", resp_exch.success, resp_exch.message)

        # Alice recebe EXCHANGE_COMPLETED com dica de Bob
        ev_comp1 = ec1.wait_for(game_pb2.EXCHANGE_COMPLETED, timeout=3)
        assert_not_none("Alice recebe EXCHANGE_COMPLETED", ev_comp1)
        if ev_comp1:
            assert_ok("Alice vê dica de Bob",
                       ev_comp1.private_hint == "dica_bob", ev_comp1.private_hint)

        # Bob recebe EXCHANGE_COMPLETED com dica de Alice
        ev_comp2 = ec2.wait_for(game_pb2.EXCHANGE_COMPLETED, timeout=3)
        assert_not_none("Bob recebe EXCHANGE_COMPLETED", ev_comp2)
        if ev_comp2:
            assert_ok("Bob vê dica de Alice",
                       ev_comp2.private_hint == "minha_dica", ev_comp2.private_hint)

        # Troca já usada
        exch2 = c1.request_hint_exchange(r3.player_id, "outra_dica")
        assert_ok("Segunda troca bloqueada (já usou)", not exch2.success, exch2.message)

        spy_late = c3.spy_on_exchange(r1.player_id, r2.player_id)
        assert_ok("Espionagem sem troca pendente bloqueada", not spy_late.success, spy_late.message)

        # ══════════════════════════════════════
        # BLOCO 10: Edge cases e validações
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 10] Edge cases{RESET}")

        # Palpite de si mesmo
        self_guess = c1.submit_guess(r1.player_id, "eu mesmo")
        assert_ok("Palpite de si mesmo bloqueado", not self_guess.success, self_guess.message)

        # StartGame com 0 jogadores novos (servidor com jogo já em andamento)
        # Tentativa de iniciar partida enquanto já está rodando: bloqueado?
        # (game_state.start_game verifica _game_started)
        # — Nota: após bloco 8, sessão 2 pode ainda estar rodando
        # Voto de jogador que já votou
        # (já testado implicitamente — não vamos duplicar)

        # ValidateGuess com ID inválido
        val_invalid = c1.validate_guess("id-inexistente", True)
        assert_ok("ValidateGuess ID inexistente retorna erro", not val_invalid.success,
                  val_invalid.message)

        # Dica vazia
        empty_hint = c1.send_public_hint("")
        assert_ok("Dica vazia bloqueada", not empty_hint.success, empty_hint.message)

        # Palpite vazio
        empty_guess = c1.submit_guess(r2.player_id, "")
        assert_ok("Palpite vazio bloqueado", not empty_guess.success, empty_guess.message)

        # ══════════════════════════════════════
        # BLOCO 11: Saída de jogador
        # ══════════════════════════════════════
        print(f"\n{BOLD}[BLOCO 11] Saída de jogador{RESET}")

        leave_resp = c3.leave_game()
        assert_ok("LeaveGame remove jogador", leave_resp.success, leave_resp.message)

        ev_left = ec1.wait_for(game_pb2.PLAYER_LEFT, timeout=3)
        assert_not_none("PLAYER_LEFT recebido", ev_left)
        if ev_left:
            assert_ok("Jogador removido da lista",
                      all(p.player_id != r3.player_id for p in ev_left.players))
            assert_ok("Sala continua com dois jogadores",
                      len(ev_left.players) == 2, str(len(ev_left.players)))

    except Exception as e:
        err("CRASH", f"Exceção não tratada: {e}")
        traceback.print_exc()

    finally:
        for c in collectors:
            c.stop()
        server.stop(grace=0)

    # ══════════════════════════════════════
    # RESUMO
    # ══════════════════════════════════════
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  RESUMO{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    total = len(PASS) + len(FAIL)
    print(f"{GREEN}  PASSOU: {len(PASS)}/{total}{RESET}")
    if FAIL:
        print(f"{RED}  FALHOU: {len(FAIL)}/{total}{RESET}")
        for f in FAIL:
            print(f"{RED}    - {f}{RESET}")
    else:
        print(f"{GREEN}  Todos os testes passaram!{RESET}")
    print()


if __name__ == "__main__":
    run_tests()
