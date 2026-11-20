# Feuille de route

Mise à jour le 19 novembre 2026. Chaque étape a son ticket GitHub, et les [jalons][milestones] regroupent ces tickets en montrant leur avancement.

## Ce qui a été fait récemment

En deux jours, learn-it est passé d'une idée à une v0 testée et relue en continu.

- **15 novembre : le squelette.** La CLI Python et ses sept commandes (`scan`, `ask`, `overview`, `decisions`, `why`, `review`, `serve`) sont en place. Le scan déterministe relève la stack, les dates d'adoption, les zones chaudes et le travail non commité. L'agent Claude dispose d'outils en lecture seule, et le serveur MCP les expose. Le README et trois ADR complètent l'ensemble.
- **16 novembre : une revue indépendante.** Une automatisation Codex relit chaque nouveau commit de `master` toutes les cinq minutes. Elle ouvre des PR correctives et tient son journal dans [#4] ([#7]).
- **Trois failles corrigées.** Des liens symboliques permettaient de lire ou d'écrire hors du projet ([#1]), et des noms GitHub invalides atteignaient les chemins et les arguments de git ([#2]) : la PR [#6] a corrigé les deux. Des noms de fichiers échappés par git contournaient aussi le filtre des secrets dans la recherche : corrigé dans la PR [#8].
- **Un profil toujours à jour ([#3]).** Chaque commande rescanne le projet, avec ou sans git. Le scan prend moins d'une seconde, même sur fastapi (8 125 commits).
- **Une CI et une évaluation ([#5]).** Le lint et les tests tournent sous Python 3.11 et 3.14 sur chaque PR. Les citations `fichier:ligne` et les commits cités sont vérifiés automatiquement, et des cas de référence notent les vraies réponses de Claude sans comparer leur texte.

Les trois derniers points ont été fusionnés par la PR [#9], avec 82 tests et une CI verte.

- **Nuit du 16 au 17 novembre : la roadmap presque entière.** La PR [#29] a livré les étapes #11 à #23 : citations contrôlées, cas de référence étendus, coût et conversation, sources GitHub et ADR, nouveaux écosystèmes, export et recommandations, historique, graphe des imports. La PR [#31] a ajouté la correction des citations et les limites de requêtes, et les revues Codex ont corrigé deux défauts au passage ([#28], [#30]). Le projet compte maintenant 288 tests, tous sans appel IA réel.
- **17 novembre : la stack lue au bon endroit.** Sur pallets/flask, la stack était datée à partir d'un exemple (`examples/celery/`) plutôt que du `pyproject.toml` racine, et Flask figurait parmi ses propres dépendances. Corrigé ; trois limites trouvées en testant l'outil sur de vrais dépôts sont devenues les tickets [#32], [#33] et [#34].

- **17 novembre, après-midi : les décisions du propriétaire et une première mesure réelle.** Licence MIT (#24, la publication sur PyPI attendra la fin du projet), revue côté serveur sur l'abonnement Claude (#25, prête dès que le secret existe), et un moteur `claude-code` qui fait tourner learn-it sur l'abonnement. La première évaluation réelle est passée de 6 à 11 cas réussis sur 11 hors dépôt Go, après deux corrections : des chemins complets dans les citations et le barème ([docs/evaluation.md](evaluation.md)).

- **18 novembre : Go mesuré et premières protections de #34.** La mesure complète atteint 12/14, Go compris. Les deux échecs concernent des chemins abrégés : une complétion locale les résout en rejeu hors ligne. Une confirmation donne 4/6, avec un échec de contenu sur Express et une revue Go bloquée par le quota. L'export ADR refuse désormais une décision sans preuve vérifiable, sauf option explicite, et signale chaque citation invalide. Le cache de l'analyse syntaxique évite aussi de reparcourir les fichiers déjà refusés ; l'analyse Go à chaud descend à 8,4 s ([mesures](scan-performance.md)).

- **19 et 20 novembre : variabilité, tokens, vitesse et revue serveur.** Six évaluations complètes donnent de 13 à 14 cas réussis sur 14. L'effort `medium` devient le réglage par défaut : la mesure 10 donne un coût moyen des réponses inférieur de 32 % à `high` en équivalent API. Le profil et les résultats d'outils passent en JSON compact. La mesure 11 relève une baisse de 14 % des tokens lus dans le cache après plusieurs changements du prompt et du rendu. Sur golang/go, le scan à chaud passe de 7,8 à 6,5 s, `find_symbol` de 3,5 à 0,45 s, et le démarrage de `learn-it serve` de 9,5 à 1 s ([mesures de la PR #98](https://github.com/maximilien-ilic/learn-it/pull/98)). Cinq régressions introduites par ces optimisations ont été trouvées par la revue Codex et corrigées (#104). La revue Claude côté serveur tourne depuis le 20 novembre, à la fin de la CI de chaque push (#25). Ses deux premières exécutions ont déjà trouvé un défaut (#107).

- **20 novembre, soir : la version 0.2.0.** Version, CHANGELOG daté, archives vérifiées (#131), tag et release GitHub. Un analyseur à pile remplace la regex de détection PHP et suit les interpolations (#132). Un guide de contribution explique comment faire évoluer le projet (#134). La mesure 12 donne 13/14 sur `35070ba`, un commit antérieur au tag.

## Où on en est

La version 0.2.0 est publiée sur GitHub le 20 novembre, et sa publication sur PyPI reste à finaliser après l'annulation du premier job de publication ([#24]). Les tickets de suivi sont clos : [#10] (évaluations sur l'abonnement, 95 réponses réussies sur 98 depuis la mesure 10), [#25] (revue serveur active, environ 0,10 $ par revue en équivalent API) et [#34] (non planifié : les erreurs mesurées ne sont pas corrigeables par le modèle). Les jalons ci-dessous restent des pistes pour faire évoluer le projet.

## La suite

Cinq jalons, dans l'ordre où ils apportent le plus :

1. mesurer ce que valent les réponses ;
2. aller chercher les vraies raisons des choix ;
3. rendre les décisions exploitables ;
4. approfondir la lecture du code ;
5. soigner l'expérience et la diffusion.

### v0.2 — Des réponses fiables

Avant d'ajouter des fonctionnalités, savoir ce que valent les réponses et ne plus laisser passer une citation inventée.

| Étape | Ticket | État |
|---|---|---|
| Mesurer les vraies réponses une première fois et régler les prompts | [#10] | clos ; variabilité et effort mesurés sur l'abonnement Claude |
| Vérifier les citations de chaque réponse avant de l'afficher | [#11] | fait |
| Étoffer les cas de référence : trois langages, une injection de prompt, un gros dépôt | [#12] | fait |
| Afficher coût et durée, régler modèle et effort par commande | [#13] | fait |
| Corriger aussi les preuves des décisions et recommandations | [#34] | complétion locale et garde ADR en place ; extension après un gain mesuré sur les réponses texte |

### v0.3 — Retrouver le pourquoi

La raison d'un choix se trouve souvent dans la PR qui l'a introduit ou dans un ADR, pas dans le code.

| Étape | Ticket | État |
|---|---|---|
| Lire les pull requests et issues GitHub liées aux commits | [#14] | fait |
| Reconnaître davantage d'écosystèmes : Java, Ruby, PHP, .NET, infrastructure | [#15] | fait |
| Partir des ADR déjà présents dans le projet analysé | [#16] | fait |
| Dater une dépendance à travers les migrations de manifeste | [#32] | fait |
| Distinguer la stack du projet de celle de ses exemples et tests | [#33] | fait |

### v0.4 — Faire vivre les décisions

Des décisions et des recommandations qu'une équipe peut versionner, trier et suivre.

| Étape | Ticket | État |
|---|---|---|
| Exporter les décisions en fichiers ADR dans le projet | [#17] | fait |
| Recommandations structurées et plan d'action exportable en tickets | [#18] | fait |
| Suivre l'évolution des décisions dans le temps (`learn-it diff`) | [#19] | fait |

### v0.5 — Comprendre la structure

Lire le code comme un graphe, sans ralentir le scan.

| Étape | Ticket | État |
|---|---|---|
| Garder le scan sous deux secondes sur un très gros dépôt | [#20] | fait |
| Symboles et graphe des dépendances avec tree-sitter | [#21] | fait |
| Carte d'architecture tirée du graphe réel | [#22] | fait |

### v0.6 — Expérience et diffusion

Un outil agréable au quotidien, installable par d'autres, et relu même machine éteinte.

| Étape | Ticket | État |
|---|---|---|
| Mode conversation `learn-it chat`, réponses en streaming | [#23] | fait |
| Licence, versions et publication sur PyPI | [#24] | licence, release GitHub et contrôles du paquet faits. Publication PyPI à finaliser |
| Lancer la revue automatique côté serveur, sans Orca | [#25] | prête, secret à créer |

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
[#28]: https://github.com/maximilien-ilic/learn-it/pull/28
[#30]: https://github.com/maximilien-ilic/learn-it/pull/30
[#31]: https://github.com/maximilien-ilic/learn-it/pull/31
[#32]: https://github.com/maximilien-ilic/learn-it/issues/32
[#33]: https://github.com/maximilien-ilic/learn-it/issues/33
[#34]: https://github.com/maximilien-ilic/learn-it/issues/34
