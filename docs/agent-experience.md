# Usage, options et conversation

Les commandes IA (`ask`, `overview`, `decisions`, `why`, `review`, `chat`) acceptent
`--model`, `--effort` et `--budget`. Les options explicites priment sur les variables
d'environnement. Le modèle par défaut reste `claude-opus-5-5`, effort `high`.

```bash
learn-it ask "Où sont stockées les sessions ?" --effort medium --budget 40000
learn-it ask "Pourquoi Redis ?" --model claude-sonnet-5-5 --no-stream
learn-it chat -p ./mon-projet --effort medium
```

## Mesures et coût

À la fin de chaque boucle IA, stderr reçoit les totaux d'entrée, sortie, écritures
et lectures de cache, la part des entrées servie par le cache, le nombre de requêtes
et d'appels d'outils et la durée mesurée. Les compteurs viennent des réponses API,
y compris les opérations de compaction quand elles sont présentes. Aucun succès
de cache n'est supposé : zéro lecture mesurée reste zéro.

Le coût est une estimation en USD aux tarifs publics standard vérifiés le
16 novembre 2026 pour les modèles listés dans `agent/usage.py`. Les tokens de
cache sont facturés avec leur tarif propre, y compris les écritures d'une heure.
Un modèle inconnu, une géographie ou un niveau de service spécial, une interruption
ou des données d'usage manquantes donnent « coût indisponible ». Ce montant ne
remplace pas une facture : taxes, remises et conditions particulières sont exclus.
Les prix restent un instantané ; il faut les revérifier avant de les mettre à jour.
Source : [tarifs Claude API](https://platform.claude.com/docs/en/about-claude/pricing).

## Budget de tâche

`--budget` et `LEARN_IT_BUDGET` désignent un **nombre de tokens**, avec un minimum
de 20 000 imposé par l'API. Le réglage est envoyé dans `output_config.task_budget`
avec le bêta `task-budgets-2026-03-13` ; le même budget est gardé entre les requêtes
d'un tour sans décrémenter manuellement les tokens déjà présents dans l'historique.

Ce budget API est **indicatif** : Claude peut le dépasser. Il ne garantit ni un
plafond de facture ni une limite exacte sur tous les tokens d'une session de chat.
Chaque question de chat démarre un nouveau tour. Les limites locales restent
16 000 tokens de sortie par réponse et `LEARN_IT_MAX_ITERATIONS` requêtes ordinaires
par question ; la compaction peut ajouter une requête de synthèse. Un modèle ne
prenant pas en charge ce bêta renvoie une erreur API explicite.
Source : [budgets de tâche](https://platform.claude.com/docs/en/build-with-claude/task-budgets).

## Conversation et streaming

`ask` affiche le Markdown au fil des fragments reçus ; `--no-stream` conserve
l'affichage Markdown complet. Les appels d'outils restent visibles sur stderr.

`chat` garde un même thread SDK, le profil initial du projet, les réponses et les
résultats d'outils pour les questions suivantes. Si le serveur ne peut pas maintenir
le thread, le SDK renvoie l'historique complet au lieu de perdre le contexte.
L'agent peut réutiliser les faits déjà lus ; il garde ses outils pour vérifier
les changements éventuels du projet.

- `/save` écrit la conversation lisible complète dans `.learn-it/chat-<identifiant>.md`.
- `/exit`, `/quit`, Ctrl-D ou Ctrl-C à l'invite terminent la conversation.

Après un tour complet dont le contexte mesuré atteint 100 000 tokens, le runner
demande une compaction au serveur (`compact-2026-09-04`). Le résumé remplace
l'ancien contexte envoyé au modèle ; l'export `/save` conserve les questions et
réponses originales. `LEARN_IT_COMPACT_THRESHOLD` règle ce seuil (0 désactive la
compaction automatique). Cette opération peut consommer des tokens supplémentaires
et dépend de la prise en charge du modèle et de la plateforme.
Sources : [tool runner SDK](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner),
[compaction](https://platform.claude.com/docs/en/build-with-claude/compaction).

Les tests simulent des réponses HTTP/SSE à travers le vrai SDK : ils vérifient la
conservation des résultats d'outils entre questions, les fragments de streaming,
la compaction, l'export et les compteurs. Ils ne démontrent pas les performances
ni les taux de cache sur l'API réelle ; ces mesures restent dans le ticket #10.
