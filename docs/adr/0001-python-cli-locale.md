# 0001. Python, en ligne de commande, local d'abord

- Statut : acceptée
- Date : 2026-11-16

## Contexte

learn-it doit tourner sur n'importe quel projet, y compris un projet privé en cours de développement, sans infrastructure à déployer. Le travail combine des appels à git, de l'analyse de fichiers et un LLM qui utilise des outils.

## Décision

- Python 3.11+, distribué comme une commande (`uv tool install`).
- Typer pour la CLI, Rich pour l'affichage, Pydantic pour le modèle de données.
- Le SDK officiel Anthropic pour l'agent, le SDK MCP officiel pour `learn-it serve`.
- Tout ce que l'outil produit reste dans `.learn-it/`, à la racine du projet analysé.

## Alternatives envisagées

- **TypeScript / Node** : SDK tout aussi mûrs, et naturel pour une extension VS Code. Écarté pour la v0, Python restant plus simple pour analyser du code et prototyper des pipelines LLM.
- **Go** : un binaire unique, facile à distribuer, mais un écosystème LLM moins fourni.
- **Application web hébergée** : obligerait à stocker le code des utilisateurs côté serveur, à l'opposé du « local d'abord ».

## Conséquences

- Itération rapide. Pydantic valide, sérialise et fournit le schéma de l'outil `record_decision`.
- Il faut Python et uv sur la machine, ce que `uv tool install` rend simple.
- Une interface web reste possible plus tard, au-dessus de `features.py`.
