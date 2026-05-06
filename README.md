# Guessing Game RPC

Aplicacao multijogador de adivinhacao usando Python e gRPC.

Esta base implementa:

- `GameService` e `ChatService` separados no arquivo `.proto`;
- entrada de jogadores com `JoinGame`;
- lista de jogadores em memoria no servidor;
- evento `PLAYER_JOINED` enviado por server streaming;
- inicio de partida com `StartGame`;
- sorteio de objetos secretos por tema;
- eventos privados para informar o objeto de cada jogador;
- turnos com fases: palpite opcional antes da dica, dica publica e palpites dos demais;
- passagem de oportunidade com `PassGuessOpportunity`;
- chat em tempo real por server streaming;
- cliente de terminal com threads para escutar eventos sem travar o input;
- cliente grafico com CustomTkinter;
- base pronta para turnos, objetos, dicas, palpites, trocas privadas, espionagem e pontuacao.
- base pronta para palpites, trocas privadas, espionagem e pontuacao.

## Estrutura

```text
guessing-game-rpc/
|-- proto/
|   `-- game.proto
|-- generated/
|   |-- game_pb2.py
|   `-- game_pb2_grpc.py
|-- server/
|   |-- server.py
|   `-- game_state.py
|-- client/
|   |-- client.py
|   |-- grpc_client.py
|   `-- gui_client.py
|-- requirements.txt
`-- README.md
```

## Instalar dependencias

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

No Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Gerar os arquivos gRPC

Sempre que `proto/game.proto` mudar, rode:

```bash
python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/game.proto
```

## Executar o servidor

```bash
python server/server.py
```

## Executar clientes

Cliente terminal:

```bash
python client/client.py
```

Cliente grafico:

```bash
python client/gui_client.py
```

Abra varios terminais para simular multiplos jogadores.

## Cliente grafico

O cliente grafico usa CustomTkinter e possui:

- painel de estado do jogador;
- painel de eventos do jogo;
- painel de chat;
- campo para enviar mensagem;
- botoes para iniciar jogo, enviar dica publica, fazer palpite, solicitar troca privada e tentar espionar.
- exibicao do objeto secreto recebido por evento privado;
- exibicao do turno atual.
- exibicao apenas das acoes disponiveis na fase atual do turno.

A logica gRPC fica separada em `client/grpc_client.py`. A interface fica em
`client/gui_client.py`.

As threads dos streams nao alteram widgets diretamente. Elas recebem eventos do
gRPC e usam `after()` para agendar a atualizacao na thread principal do Tkinter.

## Observacao sobre polling

O projeto nao usa polling. Os clientes ficam inscritos nos streams do gRPC, e o
servidor publica eventos em filas bloqueantes (`queue.Queue`). Cada stream fica
parado em `queue.get()` ate existir um novo evento para enviar.

## RPCs planejados

O `.proto` declara:

- `JoinGame`
- `StartGame`
- `SendPublicHint`
- `SubmitGuess`
- `ValidateGuess`
- `PassGuessOpportunity`
- `RequestHintExchange`
- `RespondHintExchange`
- `SpyOnExchange`
- `SubscribeToGameEvents`
- `SendChatMessage`
- `SubscribeToChatEvents`

Nesta etapa, entrada de jogadores, eventos de entrada, chat em tempo real,
inicio da partida, distribuicao de objetos, fases de turno, palpites e passagem
de oportunidade estao implementados.

Os comandos `ValidateGuess`, `RequestHintExchange`, `RespondHintExchange` e
`SpyOnExchange` ainda retornam uma resposta informando que serao implementados
na proxima etapa.

## Fluxo de turno atual

1. O jogador da vez pode tentar adivinhar o objeto de outro jogador ou passar.
2. Depois disso, ele deve enviar uma dica publica sobre o proprio objeto.
3. Os outros jogadores podem tentar adivinhar o objeto dele ou passar.
4. Quando todos responderem essa oportunidade, o servidor avanca para o proximo
   jogador na ordem.
