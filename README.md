# learn-it

**Interroge n'importe quel projet. Comprends chaque décision technique. Améliore-les.**

learn-it analyse un projet (celui sur lequel tu travailles, ou n'importe quel dépôt GitHub) pour répondre à tes questions, reconstituer les décisions techniques qui l'ont façonné, puis dire lesquelles mériteraient d'être revues.

```bash
learn-it scan https://github.com/owner/repo     # la carte du projet, sans IA
learn-it ask "Comment fonctionne l'authentification ?"
learn-it decisions                              # les décisions techniques, au format ADR
learn-it review                                 # garder, améliorer ou remplacer, et par où commencer
```

> **Statut : v0.** `scan` fonctionne et est testé, et la CI tourne sur chaque PR. Les commandes IA sont testées sans appel réel à l'API ; `evals/` mesure leurs vraies réponses sur des projets de référence (voir [Évaluation](#évaluation)). Voir aussi la [roadmap](#roadmap).

## Le problème

Le code dit **quoi**. Presque jamais **pourquoi**.

Pourquoi PostgreSQL plutôt que MongoDB ? Pourquoi ce monorepo, pourquoi ce service à part ? La réponse est éparpillée dans l'historique git, les messages de commit, des docs à moitié à jour et la tête de gens partis depuis. Comprendre un projet en profondeur prend des semaines. Le modifier sans comprendre ses choix, c'est risquer de casser ce qui tenait pour une bonne raison.

learn-it rassemble ces indices et les fait parler.

## Ce que ça fait

| Commande | Question à laquelle elle répond | IA |
|---|---|:---:|
| `scan [CIBLE]` | De quoi est fait ce projet ? Langages, stack et date d'adoption de chaque techno, activité, fichiers les plus modifiés, docs, travail non commité. | non |
| `overview` | Comment est-il organisé ? Architecture (avec diagramme), flux principaux, carte du code, ordre de lecture. | oui |
| `ask "…"` | N'importe quelle question, avec une réponse sourcée. | oui |
| `decisions` | Quelles décisions techniques ont été prises, quand, pourquoi, avec quelles conséquences ? | oui |
| `why <cible>` | Pourquoi ce fichier, cette dépendance ou ce choix existe-t-il ? | oui |
| `review` | Ces décisions sont-elles toujours les bonnes ? Que changer, à quel coût, par où commencer ? | oui |
| `chat` | Enchaîner les questions avec historique, streaming et sauvegarde. | oui |
| `diff [REF]` | Quelles technos et décisions ont changé depuis une révision Git ? | non |
| `serve` | Les mêmes outils, pour ton agent (Claude Code, Cursor…) via MCP. | — |

La cible est un dossier local (par défaut le dossier courant) ou une URL GitHub : en argument pour `scan`, avec `-p/--project` pour les autres commandes. Un dépôt GitHub est cloné une fois, historique complet compris, dans `~/.cache/learn-it/`.

## Démarrage rapide

Il faut Python 3.11 ou plus, git, [uv](https://docs.astral.sh/uv/), et une clé API Anthropic pour les commandes IA.

```bash
git clone https://github.com/maximilien-ilic/learn-it && cd learn-it
uv tool install --editable .          # installe la commande learn-it ('.[mcp]' pour serve)
export ANTHROPIC_API_KEY=sk-ant-...   # ou : ant auth login

cd ~/code/mon-projet
learn-it scan                         # gratuit, quelques secondes
learn-it ask "Par où passe une commande, de l'API jusqu'à la base ?"
learn-it decisions
learn-it review
```

Les résultats sont enregistrés dans `.learn-it/` à la racine du projet analysé (`profile.json`, `overview.md`, `decisions.md` et `.json`, `review.md`). Ce dossier s'exclut lui-même de git. Le profil est recalculé à chaque commande, donc il suit le travail non commité ; un scan prend moins d'une seconde sur des dépôts de plusieurs milliers de commits.

### Depuis ton agent, via MCP

```bash
claude mcp add learn-it -- learn-it serve -p /chemin/vers/mon-projet
```

Ton agent dispose alors du profil du projet, des décisions reconstituées et des outils de recherche dans le code et l'historique.

## Comment ça marche

```mermaid
flowchart LR
    T["dossier local<br/>ou URL GitHub"] --> S[sources]
    S --> A["analyzers<br/>fichiers · stack · historique git"]
    A --> P[("profil<br/>.learn-it/profile.json")]
    P --> G["agent Claude<br/>+ outils en lecture seule"]
    S --> G
    G --> F["ask · overview · decisions · why · review"]
    P --> M["serveur MCP"]
```

1. **Les faits d'abord.** `scan` construit un profil du projet sans IA. La stack vient des manifestes (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, Dockerfile, compose, CI…), la date d'adoption de chaque techno vient de `git log -S`, et l'historique donne l'activité, les zones chaudes et le travail en cours.
2. **Puis l'enquête.** L'agent part de ce profil et explore le code comme le ferait un dev : il cherche (`git grep`), lit les passages utiles, remonte l'historique (`git log`, `git show`, `git blame`) jusqu'au commit qui a introduit un choix.
3. **Des réponses vérifiables.** Chaque affirmation cite sa source (`src/db.py:12-40`, `commit a1b2c3d`), et ce qui est documenté reste séparé de ce qui est déduit.

Principes :

- **Recherche agentique plutôt que RAG vectoriel.** Pas d'index à reconstruire : l'agent voit toujours l'état actuel du code, y compris le travail non commité d'un projet en cours ([ADR 0002](docs/adr/0002-recherche-agentique.md)).
- **Outils d'enquête en lecture seule.** L'analyse lit le code et l'historique ; elle exclut les fichiers ignorés par git (`.env`…), les fichiers sensibles connus (`*.pem`, `id_rsa`…) et les internes Git. Les rapports vont dans `.learn-it/`. L'export ADR est explicite ; la publication de recommandations en tickets exige une confirmation.
- Les liens symboliques (fichiers et dossiers) sont exclus de l'analyse. Les sorties dans `.learn-it/` et les chemins du cache GitHub refusent également les liens symboliques.
- **Local d'abord.** L'analyse tourne sur ta machine ; seuls le profil et les extraits lus par l'agent partent vers l'API Claude.

## Structure du code

```
src/learn_it/
├── cli.py            commandes (Typer)
├── config.py         réglages lus dans l'environnement
├── domain.py         modèle de données : ProjectProfile, Technology, Decision…
├── sources.py        dossier local ou URL GitHub → projet sur disque
├── git.py            appels à git, sans shell
├── analyzers/        faits déterministes, sans IA
│   ├── inventory.py    fichiers, langages, docs
│   ├── stack.py        stack technique depuis les manifestes
│   └── history.py      activité, zones chaudes, dates d'adoption
├── agent/            la partie IA
│   ├── tools.py        outils en lecture seule (partagés avec MCP)
│   ├── prompts.py      consignes de chaque tâche
│   └── runner.py       boucle d'outils Claude
├── features.py       ask · overview · decisions · why · review
├── evidence.py       vérification des citations : fichier:ligne et commits
├── store.py          persistance dans .learn-it/
├── render.py         affichage terminal et rapports Markdown
└── mcp_server.py     learn-it serve

evals/                évaluation des réponses IA
├── cases.toml        projets de référence, questions et preuves attendues
├── shop.py           projet synthétique à l'historique figé (aussi utilisé par les tests)
├── scoring.py        barème : citations valides, faits, sources, déductions signalées
└── run.py            exécution avec la vraie API (jamais en CI)
```

Les dépendances descendent : `analyzers` ignore tout de l'IA, `agent` ignore tout de la CLI. Pour ajouter une fonctionnalité : un prompt dans `agent/prompts.py`, une fonction dans `features.py`, une commande dans `cli.py`.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | clé API (ou un profil `ant auth login`) |
| `LEARN_IT_MODEL` | `claude-opus-5-5` | modèle Claude |
| `LEARN_IT_EFFORT` | `high` | effort de raisonnement, de `low` à `max` ; vide pour les modèles qui ne le gèrent pas |
| `LEARN_IT_LANG` | `French` | langue des rapports (`ask` répond dans la langue de la question) |
| `LEARN_IT_MAX_ITERATIONS` | `40` | nombre maximal d'allers-retours de l'agent |
| `LEARN_IT_CACHE_DIR` | `~/.cache/learn-it` | où sont clonés les dépôts GitHub |

## Roadmap

Déjà fait : la CLI et ses sept commandes, le scan déterministe, l'agent Claude et son serveur MCP, la CI et l'évaluation des réponses.

La suite tient en cinq jalons, de v0.2 (des réponses fiables) à v0.6 (expérience et diffusion), avec un ticket GitHub par étape. Le détail, et ce qui a été fait récemment, sont dans [docs/roadmap.md](docs/roadmap.md).

## Développement

Les [commandes de suivi des décisions](docs/decision-workflow.md) décrivent la
vérification des citations, l'export ADR, les recommandations en JSON, les tickets
sur confirmation et `learn-it diff`. Voir aussi les
[sources GitHub et ADR](docs/project-sources.md), le
[graphe des imports](docs/code-structure.md) et le
[chat, streaming et bilan d'usage](docs/agent-experience.md).

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

La CI GitHub (`.github/workflows/ci.yml`) lance ces contrôles sous Python 3.11 et 3.14, sur chaque PR et chaque push sur `master`.

### Évaluation

`pytest` ne couvre que la partie déterministe. Pour mesurer les vraies réponses de Claude, avec une clé API :

```bash
uv run python -m evals.run           # tous les projets de référence (consomme des tokens)
uv run python -m evals.run shop      # seulement ceux nommés
```

Chaque cas de `evals/cases.toml` vérifie que les citations `fichier:ligne` et les commits cités existent, que les faits et les sources attendus sont présents, que ce que rien ne documente est signalé comme déduit, et qu'aucun secret ne fuit. Le texte exact n'est jamais comparé.

Les décisions techniques de learn-it sont elles-mêmes documentées dans [`docs/adr/`](docs/adr/), au format ADR que l'outil vise à produire.
