# Changelog

Les versions suivent `MAJEURE.MINEURE.CORRECTIF`. Avant la première version stable,
une version mineure peut modifier les interfaces. Les changements non publiés restent
dans la section « Unreleased » ; chaque publication reçoit une section datée et un tag.

## [Unreleased]

- Les tests des limites API et du rejeu GitHub passent aussi lorsque
  `CODEARCHEO_BACKEND=claude-code` est exporté.
- Les cas `t3-database` et `t3-review` exigent des citations numérotées pour la
  base Drizzle/PostgreSQL et l'API tRPC.

## [0.2.0] - 2026-11-20

Le projet s'appelait `learn-it` jusqu'au 20 novembre 2026 : ce nom ressemblait trop à d'autres
projets et `learnit` est déjà pris sur PyPI. La commande, le paquet, le module, le dossier
`.codearcheo/` et les variables `CODEARCHEO_*` portent le nouveau nom. Les anciennes variables
`LEARN_IT_*` restent lues quand les nouvelles sont absentes.

### Ajouts

- CLI locale pour analyser un dossier ou un dépôt GitHub : `scan`, `overview`, `ask`,
  `decisions`, `why`, `review`, `chat`, `diff` et `serve`.
- Profil déterministe : stack, dates d'adoption à travers les migrations de manifestes,
  activité Git, ADR existants et graphe syntaxique optionnel pour cinq langages.
- Analyse IA avec preuves vérifiées, distinction entre faits et déductions, correction
  facultative des citations et export des décisions en ADR.
- Recommandations structurées, publication explicite en tickets et suivi par révision Git.
- Moteur API Anthropic et moteur Claude Code utilisant l'authentification de son CLI.
- Catalogue d'évaluation, archivage des réponses par cas et recalcul hors ligne.
- Licence MIT et préparation de la publication par Trusted Publishing.
- Correction des citations disponible sur l'abonnement Claude (moteur `claude-code`).
- `review --path` pour une revue limitée à un fichier ou un dossier.
- Projets PHP sans `composer.json` : PHP et base de données déduite de la connexion PDO
  ou mysqli.
- Indicateur avec le temps écoulé pendant l'analyse du moteur `claude-code`.
- Revue Claude côté serveur après la CI de chaque push sur `master`.

### Corrections

- Lecture et écriture limitées aux chemins autorisés ; exclusion des fichiers sensibles
  et des liens symboliques dans l'analyse et les sorties.
- Stack des exemples et tests affichée à part ; datation remontant aux anciens manifestes.
- Refus des ADR sans preuve vérifiable et avertissements pour les références invalides.
- Commandes sans génération indépendantes de la configuration du modèle.
- Conservation des erreurs de moteur et des vérifications de correction dans les évaluations.
- Application de la limite de tours configurée au moteur Claude Code.
- Complétion locale des chemins abrégés : suffixe unique et nom unique dans le périmètre
  d'une revue ciblée.

### Performance

- Résolution des imports Go indexée et cache des modules et refus de parsing par contenu.
- Cache syntaxique gzip : environ 225 à 14 Mio sur le dépôt Go, avec un graphe identique.
- Effort `medium` par défaut : 32 % de coût en moins que `high`, sans perte mesurée.
- Profil et résultats d'outils en JSON compact : prompt système plus court de 22 à 35 %.
- Sur golang/go : scan à chaud de 7,8 à 6,5 s, `find_symbol` de 3,5 à 0,45 s par appel,
  démarrage de `codearcheo serve` de 9,5 à 1 s.
