# Préparer et publier une version

Le ticket #24 prévoit une première publication `v0.2.0`. La version du code est passée à
`0.2.0` le 20 novembre 2026, et ses notes sont dans [`CHANGELOG.md`](../CHANGELOG.md).
Les changements suivants iront dans la section `Unreleased`.

## Vérifier le paquet avant la publication

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run pytest
uv build --no-sources
uv run python -m scripts.check_dist --smoke
```

La construction produit un wheel à partir de l'archive source. Le contrôle vérifie les
versions du projet, du module et des métadonnées, les noms des archives et la licence MIT.
Le test d'installation installe chaque archive dans un environnement isolé, importe le
module installé puis lance un scan local sans génération. Il n'utilise pas le checkout
comme paquet installé. `uv build --no-sources` évite de dépendre d'éventuels chemins locaux
de construction. Voir le [guide de construction uv](https://docs.astral.sh/uv/guides/package/).

Ces contrôles tournent aussi en CI sous Python 3.11 et 3.14. Le workflow `release.yml`
peut être lancé manuellement pour reconstruire et conserver les archives pendant sept jours :

```bash
gh workflow run release.yml --ref master --repo maximilien-ilic/codearcheo
```

Ce lancement manuel exécute uniquement la préparation. Le job de publication exige une
release GitHub stable publiée dans le dépôt d'origine et un tag correspondant à la version.

Après la construction, un second job télécharge l'artefact GitHub et revérifie les archives
dans un nouveau runner. Il installe les deux paquets depuis cet artefact et refait leur scan
local. La publication dépend de cette vérification, qui teste aussi le transfert des fichiers
entre les jobs. Seul le job final `publish` possède la permission OIDC.

Cette préparation complète a été vérifiée sur GitHub le 18 novembre 2026 :
[exécution 44306945361](https://github.com/maximilien-ilic/codearcheo/actions/runs/44306945361),
construction et vérification des archives réussies, publication ignorée. Le
[relevé](benchmarks/release-preparation-20261118.json) conserve le commit testé et
l'empreinte de l'artefact. Cette validation ne constitue pas une publication PyPI.

## Configurer Trusted Publishing

Depuis le compte PyPI du propriétaire, ajouter un éditeur GitHub avec ces valeurs :

| Champ | Valeur |
|---|---|
| Projet PyPI demandé | `codearcheo` |
| Propriétaire GitHub | `maximilien-ilic` |
| Dépôt | `codearcheo` |
| Fichier du workflow | `release.yml` |
| Environnement GitHub | `pypi` |

Pour un premier envoi, utiliser un [éditeur en attente](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
dans les réglages du compte PyPI. Il crée le projet lors de la première publication et
ne réserve pas son nom à l'avance. Pour un projet existant, configurer son
[éditeur autorisé](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

Dans GitHub, créer l'environnement `pypi` et définir les personnes autorisées à approuver
une publication. L'identité OIDC est limitée au job `publish` ; la construction et les tests
n'ont pas cette permission. Ce job télécharge les archives vérifiées, puis l'action PyPA
publie sans jeton PyPI stocké et produit les attestations. Le
[guide PyPI](https://docs.pypi.org/trusted-publishers/using-a-publisher/) décrit cette identité.

## Publier la première version

La PR #131 a intégré la version `0.2.0`, le verrou actualisé et les notes datées.
Une fois Trusted Publishing configuré et la date de publication décidée :

1. Choisir sur `master` le commit validé par la CI qui doit porter le tag `v0.2.0`.
   Vérifier que ses notes dans `CHANGELOG.md` décrivent les changements à publier.
2. Depuis ce commit, refaire la construction avec `uv build --no-sources`, puis lancer
   `uv run python -m scripts.check_dist --tag v0.2.0 --smoke`.
3. Créer le tag `v0.2.0` sur le commit vérifié, puis publier la release GitHub stable
   avec les notes correspondantes.

Le workflow reconstruit, teste les archives et vérifie que le commit appartient à
l'historique de `master`. Une version différente du tag, des notes datées manquantes ou une
installation défectueuse arrêtent le processus avant le job PyPI. Une préversion GitHub
ne lance pas cette publication stable.

Après publication, vérifier depuis un autre dossier :

```bash
uv tool install 'codearcheo[mcp,code]==0.2.0'
codearcheo --help
codearcheo scan /chemin/vers/un/projet
```

Pour une installation minimale, utiliser `uv tool install codearcheo`. Ces commandes depuis
PyPI ne deviennent utilisables qu'après la publication effective. Les commandes IA exigent
toujours leur authentification propre.
