# Faire évoluer learn-it

Ce guide résume comment le projet se développe : où ajouter du code, comment le vérifier
et comment il arrive sur `master`. La documentation et les tickets sont en français ; le
code, les commentaires et les messages de commit sont en anglais.

## Mettre en place

```bash
git clone https://github.com/maximilien-ilic/learn-it && cd learn-it
uv sync --all-extras
uv run ruff check .
uv run pytest
```

Pour essayer la CLI depuis ce clone : `uv tool install --editable '.[mcp,code]'`. Les
commandes IA passent par l'abonnement Claude avec `LEARN_IT_BACKEND=claude-code` (Claude
Code doit être connecté), ou par une clé `ANTHROPIC_API_KEY`.

## Où ajouter du code

Les dépendances descendent : `analyzers` ignore tout de l'IA, `agent` ignore tout de la CLI.

| Pour… | Modifier |
|---|---|
| une nouvelle question posée à Claude | un prompt dans `agent/prompts.py`, une fonction dans `features.py`, une commande dans `cli.py` |
| reconnaître une techno | `analyzers/stack.py` : un manifeste dans `MANIFESTS`, un fichier dans `FILE_SIGNALS`, ou un signal dans le code avec une preuve fichier:ligne |
| un nouvel outil de l'agent | une méthode de `agent/tools.py` avec docstring et `Args:` : elle sert aussi au serveur MCP (`learn-it serve`) |
| une règle de vérification des citations | `evidence.py` |

Trois règles tiennent le projet ([ADR](docs/adr/)) :

- **Les faits avant le modèle.** Tout ce qui peut être établi sans IA l'est dans `analyzers/`,
  et chaque techno porte un fichier source comme preuve.
- **Chaque affirmation est sourcée.** Une réponse cite `chemin:lignes` ou `commit <sha>`, et
  `evidence.py` vérifie que ces références existent. Une citation ne se devine jamais : un
  nom de fichier ambigu reste signalé plutôt que complété au hasard.
- **Recherche agentique, pas d'index.** L'agent lit l'état courant du code avec des outils
  en lecture seule, qui excluent les fichiers ignorés, sensibles et les liens symboliques.

## Vérifier un changement

- **Tests déterministes.** `uv run pytest` ne fait aucun appel au modèle : les agents sont
  simulés, ainsi que le faux exécutable `claude`. Un défaut corrigé reçoit un test de
  non-régression qui échoue avant le correctif.
- **Qualité des réponses.** Un changement de prompt, d'outil ou de vérification se mesure
  sur les projets de référence, avant et après :

  ```bash
  uv run --all-extras python -m evals.run --backend claude-code            # 14 cas, ≈ 13 min
  uv run --all-extras python -m evals.run --backend claude-code --case ID  # un seul cas
  ```

  Les rapports vont dans `~/.cache/learn-it/evals/`. Consigner le résultat dans
  [`docs/evaluation.md`](docs/evaluation.md). Ne jamais modifier un cas d'évaluation pour
  le faire passer. Un score varie d'une passe à l'autre : comparer au moins deux passes.
- **Coût.** Chaque commande affiche ses tokens et son coût en équivalent API. Une
  optimisation se mesure en tokens comptés par le modèle, pas en caractères.

## Livrer

1. Partir de `origin/master`, sur une branche `claude/<sujet>` ou `codex/<sujet>`, de
   préférence dans un worktree séparé, car plusieurs agents partagent le checkout principal.
2. Ouvrir une PR vers `master`, avec une description en français et la ligne
   `Fixes #N` quand elle résout un ticket. Ne jamais pousser directement sur `master`.
3. La CI lance ruff et pytest sous Python 3.11 et 3.14. Après la fusion, deux revues
   relisent chaque commit : la revue Codex locale ([docs/codex-review.md](docs/codex-review.md))
   et la revue Claude côté serveur ([docs/claude-review.md](docs/claude-review.md)). Leurs
   constats deviennent des tickets ou des PR correctives.
4. Noter le changement dans la section `Unreleased` du [CHANGELOG](CHANGELOG.md), et tenir
   à jour « Où en est le projet » dans le README.

Les commits restent au nom du propriétaire, sans ligne `Co-Authored-By` ni mention d'un
assistant IA.

## Publier une version

Voir [docs/releasing.md](docs/releasing.md) : passage de version, notes datées dans le
CHANGELOG, tag `vX.Y.Z` et release GitHub. La publication sur PyPI passe par Trusted
Publishing et attend l'approbation du propriétaire dans l'environnement `pypi`.
