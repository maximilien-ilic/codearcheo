# Feuille de route

Mise à jour le 16 novembre 2026. Chaque étape a son ticket GitHub, et les [jalons][milestones] regroupent ces tickets en montrant leur avancement.

## Ce qui a été fait récemment

En deux jours, learn-it est passé d'une idée à une v0 testée et relue en continu.

- **15 novembre : le squelette.** La CLI Python et ses sept commandes (`scan`, `ask`, `overview`, `decisions`, `why`, `review`, `serve`) sont en place. Le scan déterministe relève la stack, les dates d'adoption, les zones chaudes et le travail non commité. L'agent Claude dispose d'outils en lecture seule, et le serveur MCP les expose. Le README et trois ADR complètent l'ensemble.
- **16 novembre : une revue indépendante.** Une automatisation Codex relit chaque nouveau commit de `master` toutes les cinq minutes. Elle ouvre des PR correctives et tient son journal dans [#4] ([#7]).
- **Trois failles corrigées.** Des liens symboliques permettaient de lire ou d'écrire hors du projet ([#1]), et des noms GitHub invalides atteignaient les chemins et les arguments de git ([#2]) : la PR [#6] a corrigé les deux. Des noms de fichiers échappés par git contournaient aussi le filtre des secrets dans la recherche : corrigé dans la PR [#8].
- **Un profil toujours à jour ([#3]).** Chaque commande rescanne le projet, avec ou sans git. Le scan prend moins d'une seconde, même sur fastapi (8 125 commits).
- **Une CI et une évaluation ([#5]).** Le lint et les tests tournent sous Python 3.11 et 3.14 sur chaque PR. Les citations `fichier:ligne` et les commits cités sont vérifiés automatiquement, et des cas de référence notent les vraies réponses de Claude sans comparer leur texte.

Les trois derniers points ont été fusionnés par la PR [#9], avec 82 tests et une CI verte.

La PR [#29] propose maintenant les fonctionnalités des tickets #11 à #23 : citations
contrôlées, cas de référence étendus, usage et conversation, sources GitHub et ADR,
nouveaux écosystèmes, export et recommandations, historique et graphe des imports.
Le code est testé sans appel IA réel. Les expérimentations API de #10, la licence et
la diffusion de #24 et la revue serveur de #25 restent reportées à la demande du
propriétaire. Les tâches restantes de #11 et #13 sont détaillées dans leurs tickets.

## La suite

Cinq jalons, dans l'ordre où ils apportent le plus :

1. mesurer ce que valent les réponses ;
2. aller chercher les vraies raisons des choix ;
3. rendre les décisions exploitables ;
4. approfondir la lecture du code ;
5. soigner l'expérience et la diffusion.

### v0.2 — Des réponses fiables

Avant d'ajouter des fonctionnalités, savoir ce que valent les réponses et ne plus laisser passer une citation inventée.

| Étape | Ticket |
|---|---|
| Mesurer les vraies réponses une première fois et régler les prompts (demande une clé API) | [#10] |
| Vérifier les citations de chaque réponse avant de l'afficher | [#11] |
| Étoffer les cas de référence : trois langages, une injection de prompt, un gros dépôt | [#12] |
| Afficher coût et durée, régler modèle et effort par commande | [#13] |

### v0.3 — Retrouver le pourquoi

La raison d'un choix se trouve souvent dans la PR qui l'a introduit ou dans un ADR, pas dans le code.

| Étape | Ticket |
|---|---|
| Lire les pull requests et issues GitHub liées aux commits | [#14] |
| Reconnaître davantage d'écosystèmes : Java, Ruby, PHP, .NET, infrastructure | [#15] |
| Partir des ADR déjà présents dans le projet analysé | [#16] |

### v0.4 — Faire vivre les décisions

Des décisions et des recommandations qu'une équipe peut versionner, trier et suivre.

| Étape | Ticket |
|---|---|
| Exporter les décisions en fichiers ADR dans le projet | [#17] |
| Recommandations structurées et plan d'action exportable en tickets | [#18] |
| Suivre l'évolution des décisions dans le temps (`learn-it diff`) | [#19] |

### v0.5 — Comprendre la structure

Lire le code comme un graphe, sans ralentir le scan.

| Étape | Ticket |
|---|---|
| Garder le scan sous deux secondes sur un très gros dépôt | [#20] |
| Symboles et graphe des dépendances avec tree-sitter | [#21] |
| Carte d'architecture tirée du graphe réel | [#22] |

### v0.6 — Expérience et diffusion

Un outil agréable au quotidien, installable par d'autres, et relu même machine éteinte.

| Étape | Ticket |
|---|---|
| Mode conversation `learn-it chat`, réponses en streaming | [#23] |
| Licence, versions et publication sur PyPI | [#24] |
| Lancer la revue automatique côté serveur, sans Orca | [#25] |

## Comment on avance

- Chaque demande donne une branche et une PR, et la CI doit être verte avant la fusion.
- La revue Codex relit chaque commit qui arrive sur `master`, et ouvre une PR corrective si besoin ([#4]).
- Une étape est finie quand son ticket est fermé par une PR fusionnée. Les tâches détaillées vivent dans les tickets ; ce document donne l'ordre et la raison.
- Les tickets [#24] et [#25] portent l'étiquette `question` : chacun contient une décision qui revient au propriétaire du projet (la licence, les identifiants d'une revue côté serveur).

[milestones]: https://github.com/maximilien-ilic/learn-it/milestones
[#1]: https://github.com/maximilien-ilic/learn-it/issues/1
[#2]: https://github.com/maximilien-ilic/learn-it/issues/2
[#3]: https://github.com/maximilien-ilic/learn-it/issues/3
[#4]: https://github.com/maximilien-ilic/learn-it/issues/4
[#5]: https://github.com/maximilien-ilic/learn-it/issues/5
[#6]: https://github.com/maximilien-ilic/learn-it/pull/6
[#7]: https://github.com/maximilien-ilic/learn-it/pull/7
[#8]: https://github.com/maximilien-ilic/learn-it/pull/8
[#9]: https://github.com/maximilien-ilic/learn-it/pull/9
[#10]: https://github.com/maximilien-ilic/learn-it/issues/10
[#11]: https://github.com/maximilien-ilic/learn-it/issues/11
[#12]: https://github.com/maximilien-ilic/learn-it/issues/12
[#13]: https://github.com/maximilien-ilic/learn-it/issues/13
[#14]: https://github.com/maximilien-ilic/learn-it/issues/14
[#15]: https://github.com/maximilien-ilic/learn-it/issues/15
[#16]: https://github.com/maximilien-ilic/learn-it/issues/16
[#17]: https://github.com/maximilien-ilic/learn-it/issues/17
[#18]: https://github.com/maximilien-ilic/learn-it/issues/18
[#19]: https://github.com/maximilien-ilic/learn-it/issues/19
[#20]: https://github.com/maximilien-ilic/learn-it/issues/20
[#21]: https://github.com/maximilien-ilic/learn-it/issues/21
[#22]: https://github.com/maximilien-ilic/learn-it/issues/22
[#23]: https://github.com/maximilien-ilic/learn-it/issues/23
[#24]: https://github.com/maximilien-ilic/learn-it/issues/24
[#25]: https://github.com/maximilien-ilic/learn-it/issues/25
[#29]: https://github.com/maximilien-ilic/learn-it/pull/29
