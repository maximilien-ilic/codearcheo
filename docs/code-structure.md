# Symboles et architecture statique

L'extra `code` ajoute les grammaires tree-sitter Python, JavaScript, TypeScript/TSX,
Go et Rust. Sans cet extra, le scan reste disponible et `code_structure` vaut
`null`. Avec l'extra, le profil contient un résumé du graphe : nombre de modules
et symboles, dépendances internes, modules centraux, points d'entrée candidats,
zones combinant centralité et changements fréquents, et fichiers ignorés.

```bash
uv tool install --editable '.[code,mcp]'
uv run --all-extras pytest tests/test_code_structure.py
```

L'analyse ne charge aucun module du projet dans Python : elle lit uniquement les
fichiers autorisés par l'inventaire puis analyse leur arbre syntaxique. Les liens
symboliques, internes Git et chemins sensibles restent exclus. Chaque analyse
reprend l'état courant des fichiers, y compris les modifications non commitées.

## Données et outils

- `analyzers.code.analyze(root)` produit un `CodeGraph` avec modules, classes,
  fonctions/méthodes/types, imports, lignes et identifiants. Les erreurs de syntaxe
  sont signalées ; le reste du projet reste analysable.
- `find_symbol(name)` renvoie en un appel les définitions et occurrences candidates,
  y compris les alias d'import Python/TypeScript et Rust.
- `module_dependencies(path)` donne les imports réels du module, les fichiers
  internes résolus et les modules qui en dépendent.
- `graph.mermaid()` produit un diagramme déterministe des arêtes internes résolues.
  Une limite de taille explicite sélectionne un sous-graphe et l'indique dans le
  diagramme ; les noms de fichiers sont échappés.
- `graph.export_json()` exporte symboles, imports, arêtes `source`/`target` et limites
  pour les outils externes. Le gros index des occurrences n'est pas injecté dans
  chaque prompt : le profil n'en conserve qu'un résumé.

Le rang central utilise les degrés entrants et sortants. Le score de risque est
leur somme multipliée par le nombre de commits du fichier parmi les changements
récents analysés. Ce score donne un ordre de lecture, pas une preuve de défaut.

## Résolution et limites

Les imports Python locaux/relatifs, modules sous `src/`, imports JavaScript relatifs
et `require`, modules Go locaux déclarés dans `go.mod`, et modules Rust
`crate`/`self`/`super` (avec groupes et alias) sont résolus contre les seuls fichiers
présents. Un import ambigu ou externe reste dans l'index sans arête inventée.

Les occurrences de symboles restent **lexicales** : la liaison des variables,
l'ombrage, les alias personnalisés de bundler, l'exécution dynamique et les
conditions de compilation ne sont pas interprétés. Les points d'entrée sont des
candidats obtenus par convention (`main`) ou garde `__main__`, pas une analyse
d'exécution. Les tests Go ne sont pas ajoutés aux dépendances d'un package importé.

Pour borner coût et mémoire, une source est limitée à 1 Mo et 100 000 nœuds, et un
projet à 50 Mo / 10 000 fichiers analysés. Les dépassements et grammaires manquantes
sont signalés, jamais présentés comme une analyse exhaustive. Les fichiers malformés
restent marqués `syntax_errors` dans l'export.

Les modules analysés sont conservés dans `.learn-it/code-cache.json.gz`, par empreinte
du contenu et version des grammaires. Le cache suit donc aussi les modifications non
commitées. Les refus déterministes sont conservés avec leur motif. L'ancien
`code-cache.json` est réutilisé puis remplacé après une écriture gzip réussie. Un cache
corrompu ou une lecture décompressée dépassant 512 Mio provoque un nouveau parsing.
Un dossier de rapports en lecture seule ou lié ne rend pas l'analyse indisponible.

Le budget de scan a été recontrôlé avec **toutes les grammaires installées, le
graphe, les nouvelles sources et les ADR activés** sur Git (83 007 commits) :
médiane **1,852 s**, contre 2,584 s pour les parcours d'historique de référence ;
profils strictement identiques sur trois paires. L'étape syntaxique prend environ
0,222 s. Voir
[`scan-performance.md`](scan-performance.md) et la mesure brute
[`benchmarks/git-eacee88-integrated.json`](benchmarks/git-eacee88-integrated.json).
