# Revues du code de Claude et Codex

La revue locale surveille `master` de `maximilien-ilic/learn-it` toutes les cinq
minutes avec une automatisation Orca. Elle utilise les connexions locales Codex et
`gh`, sans clé API ajoutée aux secrets GitHub. Un worktree distinct est créé à
chaque exécution utile ; le checkout principal de travail reste disponible.

Tous les nouveaux commits de `master` sont couverts, qu'ils proviennent de Claude,
de Codex ou d'une autre personne. Aucun filtre ne porte sur l'auteur, le committer,
l'agent qui pousse ou les mentions de co-auteur. Les correctifs du relecteur sont
eux aussi revus une fois fusionnés dans `master`.

## Déroulement

1. Le précontrôle `scripts/review_gate.py check` interroge le SHA distant sans
   lancer de modèle. Une erreur réseau/authentification fait sauter l'exécution.
2. L'agent revendique le SHA avec `claim`. Un verrou local et un bail de deux heures
   empêchent deux agents de revendiquer simultanément du travail, y compris quand
   un nouveau push arrive pendant la revue. Un agent bloqué peut être remplacé
   après expiration ; son ancien jeton ne peut plus valider le travail.
3. La revue couvre tous les commits depuis le dernier SHA revu jusqu'au SHA
   revendiqué. Les pushes rapprochés peuvent être regroupés. Un force-push qui casse
   la continuité impose une revue complète. Seule `master` est surveillée ; les
   pushes sur les branches de PR attendent leur fusion dans `master` pour être
   couverts. Leurs auteurs ne changent pas cette règle.
4. L'agent crée ou met à jour des PR et des tickets avec preuves, tâches et tests.
   Il garde les tickets ouverts tant que les PR ne sont pas fusionnées. Sans
   correction, aucun PR vide n'est créé. L'issue #4 reçoit le compte rendu.
5. `complete` publie `codex/review=success` sur le SHA analysé et persiste le checkpoint
   local. Ce statut signifie que la revue a été effectuée, même si des défauts
   restent ouverts. Un push arrivé entretemps reste à traiter. `fail` libère le
   bail sans avancer le checkpoint. Les échecs de publication restent à réessayer.

## Installation locale

Prérequis : Linux, Python 3.11+, `gh` authentifié avec accès au dépôt, Codex connecté
et Orca en fonctionnement. Depuis un checkout de cette PR :

```bash
mkdir -p ~/.local/share/learn-it-review
cp scripts/review_gate.py docs/codex-review-prompt.md ~/.local/share/learn-it-review/
```

Créer ensuite une automatisation Orca via `orca automations create` : fournisseur
`codex`, dépôt `learn-it`, nouveaux worktrees par exécution, cron `*/5 * * * *`,
précontrôle `python3 ~/.local/share/learn-it-review/review_gate.py check`, et prompt
demandant de lire `~/.local/share/learn-it-review/codex-review-prompt.md`. Créer
d'abord désactivé, vérifier le précontrôle et les fichiers, puis activer. Consulter
`orca automations list`, `orca automations show <id>` et `orca automations runs
--id <id>` pour le suivi ; `orca automations edit <id> --disabled` permet la pause.
Employer la commande Orca résolue pour la session (le binaire varie selon l'hôte).

La copie installée reste indépendante du contenu du code analysé. Pour mettre à
jour le mandat ou le précontrôle, relire les modifications avant de recopier les
fichiers. L'état se trouve dans `${XDG_STATE_HOME:-~/.local/state}/learn-it-review/`.

## Limites

Ce mécanisme fait une détection périodique des nouveaux commits, pas un webhook
instantané par événement push. Orca doit rester ouvert et la machine connectée.
Les commits supprimés par force-push avant le prochain contrôle ne sont pas
observables par ce mécanisme. « Run now » contourne le précontrôle Orca, mais le
`claim` du prompt évite de refaire une revue déjà terminée.

Le contrôle ne prouve pas l'absence de faille et ne fusionne aucune PR. La CI
(`.github/workflows/ci.yml`) et l'évaluation des réponses IA (`evals/`) sont décrites
dans le README. Pour une exécution indépendante de la machine et déclenchée à chaque
événement push, il faudra une intégration côté serveur avec ses propres identifiants.
