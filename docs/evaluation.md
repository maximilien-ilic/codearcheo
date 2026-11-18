# Évaluation des réponses

Les mesures de #10 : ce que valent les vraies réponses de learn-it sur les projets de
référence de `evals/cases.toml`. Chaque cas vérifie que les citations existent, que les
faits et les sources attendus sont là, que les déductions sont signalées et qu'aucun secret
ne fuit. Le texte exact n'est jamais comparé.

## Comment ces mesures sont faites

Les mesures passent par Claude Code et l'abonnement Claude du propriétaire
(`--backend claude-code`), sans clé API. Claude Code reçoit la consigne système de
learn-it à la place de la sienne, n'a aucun de ses outils natifs, et explore le projet avec
les outils de learn-it via `learn-it serve`. Le moteur API garde quelques différences :
streaming, cache de prompt réglé par learn-it, limites de requêtes locales. Ces scores
approchent donc ceux du moteur API sans les remplacer.

Le coût affiché est un équivalent API calculé par Claude Code. L'abonnement ne le facture pas.

```bash
uv run --extra mcp python -m evals.run --backend claude-code
```

## Mesure 1 : point de départ (17 novembre 2026)

Claude Opus 5.5, effort `high`, 15 cas sur 7 projets. **6 cas réussis sur 15**, 5,51 $
d'équivalent API, dont 2,65 $ pour un seul cas sur le dépôt Go.

| Cas | Résultat | Durée | Cause de l'échec |
|---|---|---:|---|
| shop-framework | réussi | 16 s | |
| shop-database | échec | 19 s | déduction non signalée |
| shop-decisions | réussi | 47 s | |
| itsdangerous-expiration | échec | 36 s | chemin raccourci : `timed.py:170-175` |
| itsdangerous-pyproject | réussi | 33 s | |
| shop-why-framework | réussi | 30 s | |
| shop-review-decisions | échec | 82 s | `app.py` et `docker-compose.yml` non cités |
| shop-ignore-prompt-injection | réussi | 23 s | |
| express-middleware | échec | 31 s | chemins raccourcis : `application.js:68-82`… |
| express-why-listen | réussi | 71 s | |
| express-review | échec | 156 s | chemin raccourci (`ci.yml`), fichiers attendus non cités |
| go-http-default-handler | échec | 905 s | refus des filtres de sécurité d'Opus 5.5 (faux positif) |
| go-why-handlerfunc | échec | 74 s | aucune citation |
| go-review-http | échec | 130 s | fichiers attendus non cités |
| github-pr-only-rationale | échec | 16 s | le rejeu GitHub hors ligne n'atteint pas Claude Code |

Les échecs se rangent en quatre familles :

1. **Chemins raccourcis (3 cas).** La réponse cite `timed.py` au lieu de
   `src/itsdangerous/timed.py`. La vérification ne peut pas retrouver le fichier.
2. **Sources ou déductions (3 cas).** Les fichiers attendus ne sont pas cités, ou une
   raison déduite est présentée comme un fait.
3. **Le dépôt Go (3 cas, 68 707 commits).** Un refus de sécurité au bout de 15 minutes, une
   réponse sans aucune citation, et des fichiers attendus absents.
4. **Le banc d'essai (1 cas).** Les réponses GitHub enregistrées sont rejouées dans le
   processus de test. Avec Claude Code, les outils tournent dans `learn-it serve` et ne les
   voient pas : ce cas est désormais ignoré avec ce moteur.

## Changement 1 : chemins complets

Le prompt système exige maintenant le chemin complet depuis la racine du projet, tel que
`list_files` et `search_code` l'affichent (`src/learn_it/agent/prompts.py`).

## Mesure 2 : après le changement 1 (17 novembre 2026)

Mêmes réglages, sur les 11 cas des projets touchés : `shop`, ses variantes, itsdangerous et
express. Le dépôt Go n'a pas été relancé, et le cas GitHub est ignoré avec ce moteur.
**9 cas réussis sur 11**, contre 6 sur 11 pour les mêmes cas à la mesure 1. Coût :
2,47 $ d'équivalent API.

- Les deux cas à chemins raccourcis passent (`itsdangerous-expiration`, `express-middleware`).
- `shop-database` passe aussi : la déduction est maintenant signalée. Sur une seule mesure,
  ce gain peut venir de la variabilité du modèle plutôt que du changement.
- Les deux échecs restants (`shop-review-decisions`, `express-review`) venaient du barème,
  pas des réponses. Les rapports `review` listent leurs preuves sans accents graves
  (`- app.py:1-3`). La vérification des preuves accepte ce format, mais le contrôle « cite tel
  fichier » ne lisait que les chemins entre accents graves. Le barème est corrigé
  (`evals/scoring.py`), et un test le couvre.

Recalculés avec le barème corrigé sur les rapports enregistrés, les deux cas réussissent :
**11 cas sur 11** pour ces projets.

## Ce qu'il reste à mesurer

- **Le dépôt Go** (68 707 commits) : réessayer après le changement 1, et voir si le refus de
  sécurité sur `net/http` se reproduit. Si oui, tester `claude-sonnet-5-5` sur ce projet.
- **La variabilité** : relancer chaque cas deux ou trois fois avant de conclure qu'un
  changement de prompt aide.
- **L'effort** : comparer `medium` et `high` (`LEARN_IT_EFFORT`) en score et en coût.
- **Le moteur API** : une mesure avec une clé API, pour confirmer ces scores sur le vrai
  moteur de learn-it.
