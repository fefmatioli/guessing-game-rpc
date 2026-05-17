# Guessing Game RPC

Jogo multijogador de adivinhação desenvolvido em Python com gRPC. Cada jogador recebe uma imagem secreta de um personagem/objeto, envia dicas curtas aos demais e tenta adivinhar os objetos dos outros jogadores.

Toda a comunicação do jogo passa por RPC. O servidor mantém o estado autoritativo da partida e envia atualizações por streaming de eventos, sem polling.

## Requisitos

- Python 3.10+
- Dependências de `requirements.txt`

## Instalação

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Se `proto/game.proto` for alterado, regenere os stubs:

```bash
python -m grpc_tools.protoc -Iproto --python_out=generated --grpc_python_out=generated proto/game.proto
```

## Execução

Servidor:

```bash
python server/server.py
```

Cliente gráfico, uma janela por jogador:

```bash
python client/gui_client.py
```

Teste headless:

```bash
python test_headless.py
```

## Fluxo do jogo

1. Os jogadores entram informando seus nomes.
2. O primeiro jogador conectado vira dono da sala.
3. O dono configura e inicia a partida, escolhendo número de sessões e turnos por sessão.
4. O servidor sorteia uma categoria com personagens suficientes e entrega uma imagem secreta para cada jogador.
5. Em cada turno, o jogador da vez envia uma dica pública curta sobre seu próprio objeto.
6. Após a dica, os outros jogadores podem tentar adivinhar ou passar.
7. O dono do objeto arbitra cada palpite recebido, aceitando ou rejeitando.
8. Ao final dos turnos, os personagens são revelados e os pontos da sessão são contabilizados.
9. Os jogadores votam por maioria para continuar ou encerrar.
10. Se a maioria continuar dentro do limite de sessões, começa uma nova sessão com novos objetos.
11. Se o limite de sessões já foi atingido e a maioria continuar, uma nova partida é aprovada e apenas o dono da sala configura o próximo jogo.

## Pontuação

| Evento | Pontos |
|---|---:|
| Primeiro jogador a acertar um objeto | +15 |
| Segundo jogador a acertar o mesmo objeto | +10 |
| Terceiro jogador a acertar o mesmo objeto | +7 |
| Quarto em diante a acertar o mesmo objeto | +4 |
| Único jogador a acertar um objeto | +5 extra |
| Dono do objeto: exatamente 1 pessoa acertou | +12 |
| Dono do objeto: exatamente 2 pessoas acertaram | +8 |
| Dono do objeto: 3 ou mais pessoas acertaram | +4 |
| Dono do objeto: ninguém acertou | 0 |
| Dono do objeto: todos os outros acertaram | -5 |
| Espionagem bem-sucedida | +3 |
| Espionagem descoberta | -5 |

A aplicação contabiliza os pontos automaticamente. A arbitragem continua com o dono do objeto, mas o cliente mostra uma sugestão baseada nas respostas cadastradas em `assets/data/characters.json`.

Em caso de empate na pontuação final, o desempate considera, nesta ordem: maior número de primeiros acertos e maior número de acertos totais. Se ainda assim houver empate, o resultado é declarado como empate real.

## Ações especiais

- Troca privada de dicas: um jogador solicita a outro uma troca de dicas de uma palavra. A troca precisa ser aceita pelo outro jogador.
- Espionagem: um terceiro jogador pode tentar espionar uma troca pendente entre dois outros jogadores. Se for descoberto, perde pontos.
- Chat em tempo real: todos podem conversar em um chat separado das ações formais do jogo. Dicas, palpites, trocas e espionagem não são feitas pelo chat.

## Arquitetura

- `proto/game.proto`: contrato gRPC e mensagens Protocol Buffers.
- `generated/`: stubs Python gerados pelo Protocol Buffers.
- `server/game_state.py`: estado central e regras do jogo.
- `server/server.py`: implementação dos serviços gRPC.
- `client/grpc_client.py`: camada fina de chamadas RPC usada pela interface.
- `client/gui_client.py`: interface gráfica em CustomTkinter.
- `assets/data/characters.json`: catálogo de personagens e respostas aceitas.
- `assets/characters/`: imagens usadas no jogo.
- `test_headless.py`: simulação automatizada de partida com múltiplos clientes gRPC.

## Tecnologias

- gRPC + Protocol Buffers para RPC e server streaming.
- CustomTkinter para interface gráfica.
- Pillow para carregar e ajustar imagens.
- Threads no cliente para manter os streams de eventos e chat ativos.
