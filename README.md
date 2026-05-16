# Guessing Game — RPC

Jogo de adivinhação multijogador em Python com gRPC. Cada jogador recebe um personagem secreto de uma categoria temática e deve ajudar os outros a adivinhar o seu personagem enviando dicas públicas, enquanto tenta descobrir o personagem dos demais.

---

## Requisitos

- Python 3.10+
- Dependências listadas em `requirements.txt`

---

## Instalação

```bash
# Crie e ative o ambiente virtual
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Instale as dependências
pip install -r requirements.txt
```

Caso altere `proto/game.proto`, regenere os stubs:

```bash
python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/game.proto
```

---

## Executar

**Servidor** (uma instância):

```bash
python server/server.py
```

**Cliente gráfico** (uma janela por jogador — abra quantas precisar):

```bash
python client/gui_client.py
```

---

## Fluxo do jogo

1. Todos os jogadores entram digitando seu nome e clicando em **Entrar**.
2. O dono da sala clica em **Iniciar Partida** e define o número de sessões e turnos por sessão.
3. O servidor sorteia uma **categoria temática** e distribui um **personagem secreto** diferente para cada jogador.
4. Cada sessão roda em ciclos: em cada ciclo, todos os jogadores dão uma dica pública sobre seu personagem, um por vez.
5. Após cada dica, os demais jogadores podem enviar um **palpite** ou **passar**.
6. O **dono do personagem** recebe o palpite e decide se aceita ou rejeita.
7. Ao final de cada sessão os personagens são revelados e os pontos são somados.
8. Se não for a última sessão, os jogadores votam se querem continuar.

### Pontuação

| Evento | Pontos |
|---|---|
| 1.º a acertar (globalmente na sessão) | +15 |
| 2.º a acertar | +10 |
| 3.º a acertar | +7 |
| 4.º ou mais | +4 |
| Único a acertar (bônus solo) | +5 extra |
| Dono: exatamente 1 pessoa acertou | +12 |
| Dono: exatamente 2 acertaram | +8 |
| Dono: 3 ou mais acertaram | +4 |
| Dono: ninguém acertou | 0 |
| Dono: todos acertaram (penalidade) | −5 |
| Espionagem bem-sucedida | +3 |
| Espionagem descoberta | −5 |

### Ações especiais

- **Troca de dica privada** — um jogador solicita a outro uma troca secreta de uma palavra. Só pode ser usada uma vez por sessão por jogador.
- **Espionar troca** — qualquer jogador pode tentar interceptar uma troca privada entre dois outros. Há 30 % de chance de ser descoberto.

---

## Categorias

O catálogo fica em `assets/data/characters.json` e inclui:

| Categoria | Personagens |
|---|---|
| Lord of the Rings | Gandalf, Frodo, Aragorn, Legolas, Gimli, Sauron, Gollum, Saruman |
| Star Wars | Darth Vader, Luke, Leia, Yoda, Obi-Wan, Han Solo, Chewbacca, Palpatine |
| DC | Batman, Superman, Joker, Harley Quinn, Wonder Woman, Aquaman, Flash, Lanterna Verde |
| Games | Mario, Sonic, Link, Kratos, Lara Croft, Master Chief, Pac-Man, Steve |
| Anime | Goku, Naruto, Luffy, Gojo, Levi, Tanjiro, Edward Elric |

O servidor escolhe automaticamente uma categoria que tenha personagens suficientes para todos os jogadores conectados.

---

## Estrutura do projeto

```
guessing-game-rpc/
├── proto/
│   └── game.proto          # definição dos serviços e mensagens gRPC
├── generated/              # stubs gerados automaticamente
├── server/
│   ├── server.py           # servicers gRPC (GameService, ChatService)
│   └── game_state.py       # lógica e estado centralizado do jogo
├── client/
│   ├── gui_client.py       # interface gráfica (CustomTkinter)
│   └── grpc_client.py      # camada de comunicação gRPC
├── assets/
│   ├── characters/         # imagens dos personagens (por categoria)
│   └── data/
│       └── characters.json # catálogo de personagens e respostas aceitas
└── requirements.txt
```

---

## Tecnologias

- **gRPC + Protocol Buffers** — comunicação cliente-servidor com server streaming
- **Python** — linguagem principal
- **CustomTkinter** — interface gráfica moderna
- **Pillow** — carregamento e redimensionamento de imagens
- **Threading** — streams de eventos em threads dedicadas
