# Guessing Game RPC

Aplicacao multijogador de adivinhacao usando Python, gRPC e CustomTkinter.

O jogo usa arquitetura cliente-servidor, estado centralizado em memoria e
atualizacao por eventos via server streaming. Nao ha polling.

## O Que Ja Funciona

- `GameService` e `ChatService` separados no `.proto`;
- entrada de jogadores com `JoinGame`;
- chat em tempo real por server streaming;
- inicio da partida com `StartGame`;
- sorteio de uma categoria geek para a rodada;
- sorteio de um personagem diferente para cada jogador;
- evento publico `ROUND_STARTED` com a categoria;
- evento privado `CHARACTER_ASSIGNED` com a imagem do personagem do jogador;
- primeira rodada apenas com dicas publicas;
- a partir da segunda rodada, palpite opcional antes da dica;
- palpites dos demais apos a dica, uma resposta por oportunidade;
- validacao automatica de palpites pelo servidor usando `accepted_answers`;
- pontuacao automatica quando o palpite esta correto;
- cliente grafico que mostra categoria, imagem, eventos e chat.

## Categorias

O catalogo atual fica em `assets/data/characters.json` e possui:

- Lord of the Rings
- Star Wars
- DC
- RPG
- Games
- Anime

O servidor escolhe uma categoria que tenha personagens suficientes para todos os
jogadores conectados. Se houver mais jogadores que personagens em qualquer
categoria, a partida nao inicia.

## Estrutura

```text
guessing-game-rpc/
|-- assets/
|   |-- characters/
|   |   |-- lotr/
|   |   |-- starwars/
|   |   |-- dc/
|   |   |-- rpg/
|   |   |-- games/
|   |   `-- anime/
|   `-- data/
|       `-- characters.json
|-- proto/
|   `-- game.proto
|-- generated/
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

## Instalar Dependencias

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

## Gerar Arquivos gRPC

Sempre que `proto/game.proto` mudar:

```bash
python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/game.proto
```

## Executar

Servidor:

```bash
python server/server.py
```

Cliente grafico:

```bash
python client/gui_client.py
```

Cliente terminal:

```bash
python client/client.py
```

Abra varios clientes para simular multiplos jogadores.

## Imagens

As imagens sao carregadas localmente pelo cliente a partir do caminho enviado
pelo servidor no evento `CHARACTER_ASSIGNED`.

Exemplo:

```json
{
  "id": "batman",
  "name": "Batman",
  "image": "assets/characters/dc/batman.png",
  "accepted_answers": ["batman", "homem morcego", "bruce wayne"]
}
```

Coloque os arquivos PNG exatamente nos caminhos indicados no JSON, por exemplo:

```text
assets/characters/dc/batman.png
assets/characters/starwars/yoda.png
assets/characters/anime/goku.png
```

Se a imagem ainda nao existir, a GUI mostra uma mensagem com o caminho esperado.
O nome correto do personagem nao aparece na area principal do jogador; a tela
mostra apenas a categoria e a imagem recebida.

## Adicionar Personagens

Edite `assets/data/characters.json`:

1. Escolha a categoria.
2. Adicione um objeto com `id`, `name`, `image` e `accepted_answers`.
3. Coloque o PNG no caminho informado em `image`.
4. Use nomes de arquivo em minusculo, sem espacos, preferencialmente com `_`.

Exemplo:

```json
{
  "id": "novo_personagem",
  "name": "Novo Personagem",
  "image": "assets/characters/games/novo_personagem.png",
  "accepted_answers": ["novo personagem"]
}
```

`accepted_answers` e usado pelo servidor para validar palpites automaticamente.

## Fluxo De Turno

1. O servidor sorteia uma categoria e um personagem diferente para cada jogador.
2. Todos sabem a categoria, mas cada jogador ve apenas a propria imagem.
3. Na primeira rodada, cada jogador apenas envia uma dica publica.
4. A partir da segunda rodada, o jogador da vez escolhe se quer fazer um unico
   palpite antes da dica.
5. Depois, o jogador da vez envia uma dica publica do proprio personagem.
6. Os demais jogadores podem tentar adivinhar o personagem dele ou passar.
7. Cada palpite e validado pelo servidor usando as respostas aceitas do
   personagem.
8. Se estiver correto, o servidor adiciona 10 pontos ao jogador que acertou.

## Sem Polling

Os clientes ficam inscritos em `SubscribeToGameEvents` e
`SubscribeToChatEvents`. O servidor publica eventos nas filas dos streams, e os
clientes recebem as atualizacoes automaticamente.
