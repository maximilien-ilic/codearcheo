# Sources GitHub, ADR et manifestes

Les projets locaux récupèrent leur origine GitHub depuis `git remote get-url origin`.
Seules les origines `github.com` reconnues sont utilisées ; les identifiants éventuellement
présents dans une URL ne sont jamais inclus dans le profil.

## Retrouver la raison dans une PR

Pour un projet avec origine GitHub, `github_context(commit)` est disponible dans l'agent
et dans MCP. L'outil résout d'abord le SHA dans le dépôt local, puis lit les PR associées,
leurs descriptions, les commentaires de discussion et de revue, et les issues du même
dépôt citées sous la forme `#123`. Les URL présentes dans les textes ne sont jamais suivies.

L'authentification utilise `GITHUB_TOKEN` / `GH_TOKEN`, ou la session `gh` existante. Sans
identifiant, les requêtes anonymes concernent uniquement les données publiques accessibles
à l'API. Les en-têtes de débit sont respectés et un débit épuisé ne déclenche aucune attente
ou répétition automatique. Les erreurs de réseau, droits et authentification sont remontées
à l'agent ; elles ne doivent pas être prises pour une preuve d'absence de justification.

La lecture s'arrête à la première page : 3 PR, 5 commentaires par type et par PR, 5 issues,
15 requêtes au maximum et 18 000 caractères pour l'enveloppe JSON. Chaque réponse API est
également limitée en taille. Les textes sont explicitement marqués non fiables. Une PR qui
explique la raison donne une justification `documented`, avec son URL comme preuve.

Le cas synthétique `evals/github_project.py` rejoue des réponses GitHub enregistrées pour
une raison présente seulement dans une PR. Il ne simule pas la réponse de l'agent.

## Partir des ADR présents

Le scan expose `existing_adrs` : titre, chemin, statut, date, décision, contexte,
conséquences et lignes de preuve. Il reconnaît les sections MADR et Nygard, en anglais et
en français, dans les dossiers `adr`, `adrs` et `decisions`. Il exclut les liens symboliques,
les fichiers hors politique de lecture et les documents sans section de décision.

L'agent doit commencer par ces décisions, vérifier leur concordance avec le code actuel
et signaler les contradictions ou les statuts rejeté/remplacé. Un ADR reste une source
documentée même si le code s'en écarte. Les nouvelles décisions sont ensuite reconstituées.
La lecture est bornée à 100 ADR et 256 Ko par fichier ; un document trop volumineux est ignoré.

## Écosystèmes supplémentaires

Le scan reconnaît Maven (`pom.xml`), Gradle et Kotlin DSL, Ruby (`Gemfile`), Composer,
les projets .NET (`*.csproj`), les providers Terraform, les manifestes Kubernetes et les
dépendances des charts Helm. Spring, Spring Boot, Ktor, Rails, Laravel, ASP.NET Core et
plusieurs bibliothèques de données/tests sont catégorisés ; leur adoption est datée dans Git.

Les parsers n'exécutent jamais Maven, Gradle, Ruby, Terraform ou les templates Helm. Les
déclarations Gradle/Gemfile et Terraform sont limitées aux littéraux visibles : les catalogues,
variables, expressions et dépendances calculées ne sont pas résolus. XML refuse les DTD et
entités, JSON/TOML/YAML sont parsés comme données, et les manifestes invalides sont ignorés.
La taille d'un manifeste est bornée à 2 Mo.
