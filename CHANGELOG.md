# Changelog

Les versions suivent `MAJEURE.MINEURE.CORRECTIF`. Avant la première version stable,
une version mineure peut modifier les interfaces. Les changements non publiés restent
dans la section « Unreleased » ; chaque publication reçoit une section datée et un tag.

## [Unreleased]

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

### Corrections

- Lecture et écriture limitées aux chemins autorisés ; exclusion des fichiers sensibles
  et des liens symboliques dans l'analyse et les sorties.
- Stack des exemples et tests affichée à part ; datation remontant aux anciens manifestes.
- Refus des ADR sans preuve vérifiable et avertissements pour les références invalides.
- Commandes sans génération indépendantes de la configuration du modèle.
- Conservation des erreurs de moteur et des vérifications de correction dans les évaluations.
- Application de la limite de tours configurée au moteur Claude Code.

### Performance

- Résolution des imports Go indexée et cache des modules et refus de parsing par contenu.
- Cache syntaxique gzip : environ 225 à 14 Mio sur le dépôt Go, avec un graphe identique.
