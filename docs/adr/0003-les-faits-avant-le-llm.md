# 0003. Les faits avant le LLM

- Statut : acceptée
- Date : 2026-11-16

## Contexte

Un LLM sait inventer une justification plausible à n'importe quel choix technique. Or une bonne partie des faits utiles s'établit sans lui, de façon fiable et gratuite : ce que déclarent les manifestes, quand une dépendance est apparue, quels fichiers changent le plus.

## Décision

- `scan` produit un profil entièrement déterministe, sans aucun appel au LLM : fichiers, langages, stack, date et commit d'adoption de chaque techno, activité, zones chaudes, docs, travail non commité.
- Ce profil fait partie du prompt système de chaque tâche : l'agent part de faits, puis vérifie dans le code.
- Chaque affirmation de l'agent cite sa source, et une décision reconstituée porte un champ `rationale_source` : `documented` quand un commit, une doc ou un commentaire donne la raison, `inferred` quand l'agent la déduit.

## Conséquences

- `scan` est gratuit, rapide, utilisable hors ligne, et ses résultats se testent.
- Les réponses se vérifient, et l'utilisateur sait quand il lit une déduction.
- Chaque écosystème demande son détecteur dans `analyzers/stack.py` : la liste des technos repérées s'enrichira avec l'usage.
