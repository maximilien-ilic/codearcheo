# Revue côté serveur avec Claude

Le workflow `.github/workflows/claude-review.yml` relit chaque push sur `master` dans
GitHub Actions, avec Claude Code et le jeton d'abonnement du propriétaire. Aucune clé API
Anthropic n'est nécessaire, et la machine n'a pas besoin d'être allumée (#25).

La revue démarre à la fin de la CI de ce push (`workflow_run`), car `claude-code-action`
refuse l'événement `push`. Les trois premières revues ont échoué pour cette raison le
20 novembre (« Unsupported event type: push »). Une CI annulée par un push plus récent ne
lance pas de revue : la suivante couvre aussi ce commit. On peut aussi lancer une revue à
la main avec `gh workflow run claude-review.yml`.

## Activer la revue

```bash
claude setup-token                                                # affiche un jeton d'abonnement
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo maximilien-ilic/learn-it   # le colle dans GitHub
```

`gh secret set` demande la valeur sans l'afficher : le jeton ne passe ni par un fichier ni
par une conversation. Sans ce secret, le workflow s'arrête sur un simple avertissement.

## Ce que fait la revue

1. Elle saute un commit qui porte déjà le statut `claude/review` réussi.
2. Elle relit la plage depuis le dernier ancêtre marqué `claude/review` réussi parmi
   les 30 premiers parents précédents de `master`. Sans base dans cette fenêtre,
   elle relit l'arbre complet au SHA cible.
3. Elle corrige les défauts clairs sur une branche `claude/review-<sha>`, avec un test,
   puis ouvre une PR. Elle ne pousse jamais sur `master` et ne fusionne rien.
4. Elle ouvre un ticket pour chaque défaut qu'elle ne corrige pas, et écrit son compte
   rendu dans #4.
5. Elle publie enfin le statut `claude/review` sur le commit relu.
6. Elle conserve pendant sept jours un relevé numérique : coût en équivalent API, durée,
   tours et compteurs de tokens. Les prompts, réponses et résultats d'outils ne sont pas
   inclus dans cet artefact. Le script de relevé est copié avant l'analyse pour que le
   changement de branche du relecteur ne modifie pas la collecte.

Les commits utilisent l'identité GitHub du propriétaire du dépôt, conformément au choix
initial du projet. L'attribution automatique de coauteur IA est désactivée dans les
réglages de l'action. Les comptes rendus restent identifiés comme revues serveur Claude.

GitHub exécute une revue à la fois et peut remplacer une revue en attente par un push
plus récent. La base revue permet à l'exécution suivante de couvrir aussi les
changements des exécutions annulées ou échouées.

## Limites du jeton GitHub

- Le jeton `GITHUB_TOKEN` n'a jamais la permission `workflows`. Un correctif de
  `.github/workflows/` est donc joint au ticket sous forme de diff, et un humain le pousse.
- Ouvrir une PR depuis GitHub Actions demande le réglage « Allow GitHub Actions to create and
  approve pull requests » (Settings → Actions → General). Le propriétaire l'a activé le
  20 novembre : la revue ouvre ses PR correctives elle-même. Elle ne fusionne jamais, et les
  permissions par défaut du jeton restent en lecture seule.

## Charge et coût

```bash
python scripts/review_usage.py report --days 7 --output /tmp/revue-serveur.json
```

Cette commande lit l'historique GitHub et les relevés disponibles sans lancer Claude.
Elle compte les déclenchements sur `master`, toutes les tentatives de ces déclenchements,
les appels effectivement démarrés et les exécutions ignorées. Un relevé absent reste
inconnu ; il n'est pas compté comme gratuit.
L'historique inclut les anciens déclenchements directs et les revues lancées par la CI.
Sur learn-it, l'action refusait les anciens déclenchements `push` avant tout appel
à Claude. Ils comptent dans la cadence, avec une consommation Claude nulle.
Les artefacts sont vérifiés contre le dépôt, le numéro d'exécution et sa tentative. Pour les
revues lancées par la CI, le SHA enregistré désigne le commit de la CI. GitHub expose dans
la liste des revues le SHA de la pointe de la branche par défaut au déclenchement.

La projection à 30 jours conserve la cadence observée et suppose une revue du modèle par
déclenchement après activation, avec le nombre moyen de tentatives mesuré. La file GitHub
et la déduplication peuvent réduire ce
nombre. Une fenêtre de moins de sept jours est signalée : la cadence du démarrage du projet
ne permet pas d'établir un budget mensuel représentatif. L'équivalent API moyen n'est
calculé que si tous les appels démarrés ont un relevé de coût.

Pour étudier une hypothèse explicite, par exemple 1 $ d'équivalent API par revue :

```bash
python scripts/review_usage.py report --days 7 --per-review-usd 1 --output /tmp/scenario.json
```

Le rapport marque alors la projection comme scénario fourni par l'utilisateur, avec une
tentative par déclenchement. Ce montant est une hypothèse de calcul ; la commande ne
dépense rien et ne fixe aucun plafond.

Le dépôt est public et utilise `ubuntu-latest`. Le calcul sur les runners standard publics
est [gratuit selon GitHub](https://docs.github.com/en/actions/concepts/billing-and-usage).
Ce poste ne représente pas la facture entière du compte GitHub.

La consommation Claude partage les limites de l'abonnement avec les autres usages. Si les
[crédits d'usage sont activés](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans),
le dépassement de quota peut être facturé séparément. Le relevé lit un équivalent API,
pas les réglages ni la facture du compte Claude ; le champ `claude_invoice_usd` reste inconnu.
L'abonnement existant, les crédits éventuels et les taxes ne sont donc pas reconstitués par
ce rapport.

Le premier relevé daté est conservé dans
[`benchmarks/review-budget-20261118.json`](benchmarks/review-budget-20261118.json).

## Avec la revue Codex locale

La revue Codex d'Orca ([codex-review.md](codex-review.md)) peut continuer en parallèle,
comme solution de repli. Les deux relisent alors les mêmes commits. Pour n'en garder
qu'une, mets l'automatisation Orca en pause (`orca automations edit <id> --disabled`).

## Limites

- Quand la revue ouvre ou met à jour une PR avec `GITHUB_TOKEN`, la CI de la PR
  attend une approbation. Une personne ayant un accès en écriture peut la démarrer
  depuis la PR avec « Approve workflows to run ». Attends que la CI passe avant de
  fusionner. [Règle de déclenchement de GitHub](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs)
- La revue consomme l'abonnement ou les crédits d'usage configurés sur le compte Claude.
- Le relecteur peut lancer `git`, `gh` et `uv` (donc les tests) sur le code déjà fusionné ;
  rien d'autre ne s'exécute.
