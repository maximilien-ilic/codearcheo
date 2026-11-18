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
Chaque question de chat démarre un nouveau tour. Un modèle ne prenant pas en charge
ce bêta renvoie une erreur API explicite.
Source : [budgets de tâche](https://platform.claude.com/docs/en/build-with-claude/task-budgets).

Les lectures du cache au deuxième retour API sont distinguées d'une absence de
lecture mesurée et d'un usage indisponible. Ce diagnostic décrit les compteurs
reçus ; il ne promet pas un succès du cache. Sa validation sur l'API réelle reste
dans #10.

Une requête de génération soumise à la limite locale ne suit pas automatiquement
les redirections HTTP : elles pourraient envoyer plusieurs POST dans une seule
tentative du SDK. Un serveur renvoyant une redirection doit utiliser son URL finale
pour ces appels bornés.

## Limites locales appliquées avant l'envoi

`--max-requests N` (ou `LEARN_IT_MAX_REQUESTS`) limite le nombre de tentatives HTTP
de génération pour la session. La valeur doit être positive ; sans option, aucune
limite supplémentaire n'est ajoutée. La même instance de limite est réutilisée
pour une réponse et sa réparation, et pour toutes les questions d'un `chat`.

Le garde-fou utilise le middleware public du SDK avant chaque tentative vers
`/v1/messages`. Il compte aussi les retries automatiques, les rejouements du thread
et les demandes de compaction. Quand il n'y a plus de place, la tentative suivante
est refusée avant l'envoi. Ce nombre n'est pas celui des opérations internes que
le fournisseur peut effectuer derrière une requête HTTP.

`--max-output-tokens N` (ou `LEARN_IT_MAX_OUTPUT_TOKENS`) fixe le `max_tokens` de
**chaque requête**, avec 16 000 par défaut. Le réglage vaut aussi pour une synthèse
de compaction. Il ne plafonne ni les tokens d'entrée ni le total de la session.
Les valeurs explicites de ces deux options priment sur les variables d'environnement.

```bash
learn-it ask "Pourquoi Redis ?" --max-requests 5 --max-output-tokens 4000
learn-it chat --max-requests 20 --max-output-tokens 4000
```

`LEARN_IT_MAX_ITERATIONS` reste une limite de réponses ordinaires par boucle,
distincte du nombre de tentatives HTTP. Elle ne remplace pas `--max-requests` :
une réponse peut être précédée de retries et suivie d'une compaction.

Avec le moteur Claude Code, ce réglage est transmis à
[`claude -p --max-turns`](https://code.claude.com/docs/en/cli-reference).
Le comptage inclut les tours d'outils et la réponse finale. Si Claude atteint la
limite avant de conclure, la commande signale l'arrêt et conserve les compteurs
d'usage retournés, sans enregistrer une synthèse inachevée. Cette limite ne fixe
ni le nombre de tentatives HTTP internes ni un montant facturé.

Si la limite refuse seulement une compaction facultative après une réponse
complète, cette réponse est conservée avec une note. Une nouvelle question ne
réinitialise pas le compteur du chat ; `/save` et `/exit` restent disponibles.
Une tentative ayant échoué sans usage retourné demeure comptée et rend le coût
incomplet, même si un retry fournit ensuite une réponse normale.

Ces contrôles bornent les requêtes émises et leur paramètre de sortie, **pas la
facture totale**. Les entrées, opérations internes du fournisseur et essais dont
l'usage n'a pas été retourné empêchent de promettre un montant précis. Aucun
appel payant n'est utilisé dans les tests : un transport HTTP/SSE local simule le
serveur, y compris les retries et la récupération du thread.
Sources : [middleware SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/middleware),
[tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner),
[compaction](https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand).

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
