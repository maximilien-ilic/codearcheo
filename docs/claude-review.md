# Revue côté serveur avec Claude

Le workflow `.github/workflows/claude-review.yml` relit chaque push sur `master` dans
GitHub Actions, avec Claude Code. Il tourne sur l'abonnement Claude du propriétaire : il
n'y a pas de clé API à payer, et la machine n'a pas besoin d'être allumée (#25).

## Activer la revue

```bash
claude setup-token                                                # affiche un jeton d'abonnement
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo maximilien-ilic/learn-it   # le colle dans GitHub
```

`gh secret set` demande la valeur sans l'afficher : le jeton ne passe ni par un fichier ni
par une conversation. Sans ce secret, le workflow s'arrête sur un simple avertissement.

## Ce que fait la revue

1. Elle saute un commit qui porte déjà le statut `claude/review` réussi.
2. Elle relit la plage poussée, du précédent HEAD de `master` au nouveau.
3. Elle corrige les défauts clairs sur une branche `claude/review-<sha>`, avec un test,
   puis ouvre une PR. Elle ne pousse jamais sur `master` et ne fusionne rien.
4. Elle ouvre un ticket pour chaque défaut qu'elle ne corrige pas, et écrit son compte
   rendu dans #4.
5. Elle publie enfin le statut `claude/review` sur le commit relu.

Les revues passent une par une : un push qui arrive pendant une revue attend son tour.

## Avec la revue Codex locale

La revue Codex d'Orca ([codex-review.md](codex-review.md)) peut continuer en parallèle,
comme solution de repli. Les deux relisent alors les mêmes commits. Pour n'en garder
qu'une, mets l'automatisation Orca en pause (`orca automations edit <id> --disabled`).

## Limites

- Les PR ouvertes avec le jeton du workflow ne déclenchent pas la CI : c'est une règle de
  GitHub. Relance la CI depuis la PR, ou pousse un commit, avant de fusionner.
- La revue consomme le quota de l'abonnement, une revue par push sur `master`.
- Le relecteur peut lancer `git`, `gh` et `uv` (donc les tests) sur le code déjà fusionné ;
  rien d'autre ne s'exécute.
