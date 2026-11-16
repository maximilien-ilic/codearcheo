# Réponses, décisions et suivi

## Vérifier les sources

Les réponses de `ask`, `overview`, `why`, `review` et les décisions reconstituées
portent un bilan de citations. Les références fichier:ligne (avec ou sans backticks)
et `commit <sha>` sont contrôlées. Les références introuvables, ignorées, sensibles
ou hors du projet sont signalées sur stderr et dans les rapports enregistrés.
Une réponse sans source est également signalée. En streaming, la vérification et
le bilan arrivent à la fin : le texte reçu avant ce bilan reste provisoire.

Ce contrôle vérifie l'existence des références, pas que chaque phrase découle de
la source. Il ne valide pas encore les URL des PR. La correction automatique de
citations avec mesure du gain reste à expérimenter avec l'évaluation réelle (#10).

## Exporter des ADR

```bash
learn-it decisions -p ./projet --export docs/adr
learn-it decisions -p ./projet --export docs/adr --force
```

Les fichiers MADR portent une mention de reconstruction, le statut proposé, la
source de la justification et les preuves. La numérotation reprend après les ADR
existants. Un titre déjà exporté exige `--force` ; un titre qui n'est qu'un suffixe
d'un autre ne lui correspond pas. Les destinations restent dans le projet et les
liens symboliques sont refusés. Le lot est validé avant écriture, mais les écritures
de plusieurs fichiers ne forment pas une transaction en cas de panne disque.

Les ADR déjà présents figurent dans le profil. Les titres reconnus ancrent les
décisions comme documentées ; citer un ancien ADR ne suffit pas à documenter un
choix différent. Les prompts
demandent de vérifier si le code suit encore ces documents.

## Recommandations et tickets

```bash
learn-it review -p ./projet
learn-it review -p ./projet --issues
```

Le rapport est écrit dans `.learn-it/review.md` et les recommandations dans
`review.json`, triées par impact décroissant puis effort croissant. Elles portent
le verdict, les raisons, la proposition, les compromis, les étapes et les preuves.
`--issues` affiche d'abord le rapport puis exige une confirmation interactive.
Seuls les verdicts `improve` et `replace` sont proposés comme tickets. La publication
utilise `gh` et l'origine GitHub du projet ; une empreinte dans le corps évite de
recréer un ticket déjà publié, même fermé. Au-delà de la limite de recherche de
1 000 tickets, la publication s'arrête pour éviter une déduplication incomplète.

## Comparer deux états

```bash
learn-it scan ./projet
learn-it diff HEAD~1 -p ./projet
learn-it diff v0.1.0 -p ./projet --json
```

Les profils et décisions d'un arbre Git propre sont conservés par SHA complet dans
`.learn-it/history/`. Le premier résultat complet pour ce SHA reste immuable. Un
arbre sale, un HEAD modifié ou un changement pendant l'analyse empêche l'archivage
des décisions comme faits de ce SHA. Les rapports courants restent disponibles.
La vérification de stabilité se fait en début et fin d'analyse : elle n'isole pas
les lectures d'un autre processus qui modifierait puis restaurerait les mêmes fichiers.

`diff` compare les technos présentes et les décisions analysées aux deux SHA.
Sans analyse de décisions pour les deux côtés, il le dit et ne transforme pas
une analyse manquante en suppression. Sans REF, il utilise le dernier snapshot
d'un autre SHA, ou le SHA actuel pour comparer le travail non commité. Si un ancien
profil manque ou est corrompu, un clone local temporaire sert à le reconstruire,
avec configuration Git globale/système et hooks neutralisés ; le checkout de
travail reste en place. Les liens historiques hors du clone sont refusés.

Un exemple de commentaire déterministe de PR, sans appel IA, se trouve dans
[`examples/technology-diff.yml`](examples/technology-diff.yml). Le programme y est
installé depuis la base de confiance, jamais depuis le code de la PR. Les PR de
fork ne reçoivent pas de commentaire avec leur jeton limité en lecture.

## Structure du code

Installer `learn-it[code]` active tree-sitter pour Python, JavaScript/TypeScript,
Go et Rust. Le profil contient les modules centraux, points d'entrée et zones
combinant dépendances et fréquence de modification. `overview` utilise le diagramme
des imports réellement résolus, et `learn-it scan ./projet --graph-json` exporte
le graphe complet. Les limites de résolution et de volume sont détaillées dans
[`code-structure.md`](code-structure.md).
