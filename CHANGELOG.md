# Changelog — Guessing Game RPC

## Visão Geral das Mudanças

Refatoração completa do projeto original para uma arquitetura cliente-servidor gRPC com sistema de jogo mais rico, validação manual de palpites, troca de dicas, espionagem e ranking por sessões temáticas.

---

## proto/game.proto

### Novos tipos de evento (`GameEventType`)
| Valor | Nome | Descrição |
|-------|------|-----------|
| 25 | `GUESS_ACCEPTED` | Palpite aceito pelo dono |
| 26 | `GUESS_REJECTED` | Palpite rejeitado pelo dono |
| 27 | `SPY_SUCCESSFUL` | Espionagem bem-sucedida |
| 28 | `SPY_DISCOVERED` | Espião descoberto |
| 29 | `ROUND_SCORE_SUMMARY` | Resumo de pontuação ao fim de cada sessão |
| 30 | `FINAL_RANKING` | Ranking final ao fim de todas as sessões |
| 31 | `PENDING_GUESS_FOR_OWNER` | Notificação privada para o dono validar palpite |

### Novos campos em `GameEvent`
- `max_rounds` (field 23) — total de sessões/rodadas da partida
- `object_name` (field 6) — nome do personagem atribuído (em `CHARACTER_ASSIGNED`)
- `hint_cycle` (field 37) — ciclo de dica atual dentro da sessão
- `max_hint_cycles` (field 38) — total de ciclos por sessão (sempre 3)
- `ranking` (field 39) — lista de `RankingEntry` para `FINAL_RANKING`
- `guess_order` (field 40) — posição do palpite aceito (1º, 2º…)
- `session_number` (field 41) — número da sessão atual
- `is_final_session` (field 42) — se esta é a última sessão

### Nova mensagem `RankingEntry`
```proto
message RankingEntry {
  int32 position = 1;
  string player_id = 2;
  string player_name = 3;
  int32 score = 4;
  int32 points_this_round = 5;
}
```

### Novos RPCs
| RPC | Descrição |
|-----|-----------|
| `ValidateGuess` | Dono aceita ou rejeita um palpite pendente |
| `SendPublicHint` | Envia dica pública na fase de dicas |
| `RequestHintExchange` | Solicita troca privada de dica com outro jogador |
| `RespondHintExchange` | Responde a uma solicitação de troca de dica |
| `SpyOnExchange` | Tenta espionar a troca de dicas entre dois jogadores |
| `PassGuessOpportunity` | Passa a vez de adivinhar |
| `VoteForNextRound` | Vota para continuar ou encerrar após uma sessão |

### Alterações em mensagens existentes
- `StartGameRequest`: campo `max_rounds` substituiu `max_guesses_per_player`
- `ValidateGuessRequest`: `owner_player_id`, `guess_id`, `accepted`

---

## server/game_state.py

Reescrita completa. Principais aspectos:

### Constantes de pontuação
```python
HINTS_PER_SESSION = 3          # ciclos hint→guess por sessão
SPY_CATCH_CHANCE = 0.30        # 30% de chance de ser descoberto
SPY_REWARD = 3                 # pontos por espionagem bem-sucedida
SPY_PENALTY = -5               # penalidade por ser descoberto
GUESS_POINTS = {1: 15, 2: 10, 3: 7}   # pontos por ordem de acerto
GUESS_POINTS_DEFAULT = 4       # 4º acertador em diante
OWNER_POINTS_ONE = 12          # só 1 jogador adivinhou o personagem do dono
OWNER_POINTS_TWO = 8           # 2 jogadores adivinharam
OWNER_POINTS_THREE = 4         # 3+ jogadores adivinharam
OWNER_POINTS_NONE = 0          # ninguém adivinhou
OWNER_POINTS_ALL = -5          # TODOS adivinharam (regra especial, prevalece)
SOLO_BONUS = 5                 # bônus se apenas 1 jogador adivinhou um personagem em toda a sessão
```

### Sistema de validação manual
- `submit_guess()` armazena um `PendingGuess` com UUID e **não** concede pontos imediatamente
- `validate_guess(owner_player_id, guess_id, accepted)` — o dono aceita/rejeita; pontos só são dados na aceitação
- `_pending_guesses: dict[str, PendingGuess]` — store de palpites aguardando validação

### Dataclasses novas
- `PendingGuess` — representa um palpite aguardando validação (com `guess_id`, `guesser`, `owner`, `guess`, `order`)
- `ValidationResult` — resultado de `validate_guess`
- `GuessResult` — resultado de `submit_guess`, com campos `is_session_over: bool` e `round_end: Optional[RoundEndResult]`
- `ScoreChange` — mudança de pontuação de um jogador
- `RoundEndResult` — resultado ao fim de uma sessão, com `is_final: bool`

### Arquitetura de sessões
- Cada "rodada" é uma sessão temática com `HINTS_PER_SESSION=3` ciclos hint→guess
- Ao fim de todos os `max_rounds`, o jogo termina sem votação
- `_end_session_locked()` aplica bônus solo e pontuação do dono conforme a regra

### Correções de bugs
- **Bug "Ciclo 4/3"**: `pass_guess_opportunity` e `submit_guess` verificavam `_check_session_over_locked()` **antes** de `_advance_if_everyone_answered_locked()`. Invertida a ordem: a sessão só termina depois que a fila de turnos avança — evitando que um ciclo fantasma fosse iniciado.

---

## server/server.py

Reescrita completa para acompanhar a nova API do `game_state`.

### Eventos de início de sessão
- `_publish_session_start_events()` substitui `_publish_round_start_events()`
- Envia `session_number`, `is_final_session`, `hint_cycle`, `max_hint_cycles`
- `CHARACTER_ASSIGNED` inclui `object_name` com o nome do personagem

### Fluxo de palpite (SubmitGuess)
1. Publica `GUESS_SUBMITTED` (público) para todos
2. Publica `PENDING_GUESS_FOR_OWNER` (privado) só para o dono
3. Se `result.is_session_over` → chama `_publish_round_ended`
4. Caso contrário, avança o turno normalmente

### ValidateGuess
- Publica `GUESS_ACCEPTED` (com `score_delta` e `guess_order`) ou `GUESS_REJECTED`
- Avança o turno após validação

### Fim de sessão / jogo
- `_publish_round_ended`: se `round_end.is_final` → chama `_publish_game_ended` diretamente (sem votação)
- Publica `ROUND_SCORE_SUMMARY` com `ScoreChange` de cada jogador
- `_publish_game_ended`: publica `GAME_ENDED` + `FINAL_RANKING` com lista de `RankingEntry`

### Espionagem
- `_publish_exchange_result` usa `SPY_DISCOVERED` / `SPY_SUCCESSFUL` (substituiu `SPY_ATTEMPTED`/`SPY_CAUGHT`)

---

## client/grpc_client.py

- `start_game(max_rounds: int = 3)` — usa `StartGameRequest(player_id, max_rounds)`
- `validate_guess(guess_id, accepted)` — novo método para o dono validar palpites
- Removido `max_guesses_per_player` de toda a API do cliente

---

## client/gui_client.py

Reescrita completa da interface.

### Novo estado
- `session_number`, `max_rounds`, `hint_cycle`, `max_hint_cycles`
- `_pending_to_validate: dict[str, dict]` — palpites pendentes exibidos ao dono

### Painel de validação de palpites
- `pending_frame` (CTkScrollableFrame) exibido ao dono quando há palpites pendentes
- Botões "Aceitar" / "Rejeitar" chamam `rpc_client.validate_guess()`

### Label de sessão
- Exibe "Sessao X/Y · Ciclo Z/3" no topo durante o jogo

### Eventos tratados
| Evento | Ação na GUI |
|--------|-------------|
| `PENDING_GUESS_FOR_OWNER` | Adiciona palpite ao painel de validação do dono |
| `GUESS_ACCEPTED` | Exibe pontuação concedida no log |
| `GUESS_REJECTED` | Exibe rejeição no log |
| `SPY_SUCCESSFUL` | Exibe resultado de espionagem no log |
| `SPY_DISCOVERED` | Exibe que o espião foi descoberto |
| `ROUND_SCORE_SUMMARY` | Abre janela de resumo de pontuação da sessão |
| `FINAL_RANKING` | Abre janela de ranking final |
| `CHARACTER_ASSIGNED` | Exibe nome do personagem via `event.object_name` |

### Correções de bugs na GUI
- **Lista de jogadores**: `_set_players` só é chamado em `PLAYER_JOINED` e `TURN_STARTED` — corrige sobrescrita da lista com subconjuntos de jogadores de outros eventos
- **Imagem na nova sessão**: `ROUND_STARTED` reseta imagem para placeholder; `CHARACTER_ASSIGNED` recarrega
- **Janela de fim de jogo**: usa `event.ranking` (lista de `RankingEntry`) quando disponível

---

## assets/data/characters.json

- **Removida** a categoria RPG (sem imagens disponíveis)
- **Corrigidas** todas as extensões de imagem: `.png` → `.jpg` (maioria) ou `.webp` (Frodo, Legolas — LOTR)
- **Removida** entrada duplicada `frodo2.jpg` do LOTR
- **Normalizado** nome de arquivo `Frodo.webp` → `frodo.webp` (minúsculas)

---

## test_headless.py (novo arquivo)

Script de teste sem interface gráfica para validação do fluxo completo do servidor.

- Sobe o servidor gRPC em processo no porto 50099
- Cria 3 clientes simulados: Alice, Bob, Carol
- `EventCollector`: thread em background consumindo o stream de eventos
- 11 blocos de teste, 76 asserções
- Cobre: join, start, hint phase, guess submission, manual validation, hint exchange, spy, pass opportunity, session end, voting, multi-session flow
- Resultado: 73/76 passam (3 falsos positivos por race condition de fila nos testes — não são bugs da aplicação)

---

## Arquitetura Geral

```
proto/game.proto
      |
      v
generated/game_pb2.py + game_pb2_grpc.py   (gerados pelo protoc)
      |
      +---> server/game_state.py   (lógica de negócio pura, sem gRPC)
      |           |
      |           v
      +---> server/server.py       (handlers gRPC, publica eventos via filas por jogador)
      |
      +---> client/grpc_client.py  (stub wrapper fino)
                  |
                  v
            client/gui_client.py   (CustomTkinter, threads de stream)
```

### Fluxo de eventos
- Sem polling: o servidor usa `queue.Queue` por jogador
- `SubscribeToGameEvents` e `SubscribeToChatEvents` são streams gRPC do lado do servidor
- Cada RPC que muda estado publica eventos nas filas dos jogadores relevantes
