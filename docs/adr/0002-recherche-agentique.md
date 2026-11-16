# 0002. Recherche agentique plutôt que RAG vectoriel

- Statut : acceptée
- Date : 2026-11-16

## Contexte

Pour répondre sur un projet, il faut retrouver les bons passages de code et d'historique. L'approche classique, le RAG, découpe le code, calcule des embeddings et interroge une base vectorielle. Trois limites pèsent ici :

- les questions sur du code portent sur des identifiants précis, que la similarité sémantique sert mal ;
- un projet en cours change à chaque commit, et même entre deux commits : un index vectoriel est vite périmé ;
- le *pourquoi* vit surtout dans l'historique git, qu'un index de fichiers ne capture pas.

## Décision

Pas d'index vectoriel en v0. Claude pilote lui-même des outils en lecture seule sur l'arbre de travail réel : `list_files`, `search_code` (`git grep`), `read_file`, `git_log`, `git_show`, `git_blame`. Il part de la carte que donne le profil déterministe ([ADR 0003](0003-les-faits-avant-le-llm.md)). Les mêmes outils sont exposés en MCP.

## Alternatives envisagées

- **RAG vectoriel** (embeddings et base vectorielle) : utile pour des questions floues sur de très gros dépôts, mais l'index doit être tenu à jour et la précision baisse sur les identifiants.
- **Tout mettre dans le contexte** : impossible au-delà des petits projets, et coûteux.
- **Hybride** : à reconsidérer si de très gros monorepos l'exigent.

## Conséquences

- Toujours à jour, aucune infrastructure, des citations exactes (`fichier:ligne`, commit).
- Plus d'allers-retours avec l'API, donc plus de latence et de tokens. Le cache de prompt (préfixe système stable, cache automatique de la conversation) et un profil qui oriente la recherche compensent en partie.
- Sur un très gros dépôt, il faudra un index de symboles (roadmap : tree-sitter).
