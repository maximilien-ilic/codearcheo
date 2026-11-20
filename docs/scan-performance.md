# Mesure du scan

Mesure du 16 novembre 2026 sur Linux, Python 3.12, avec le dépôt public
[git/git](https://github.com/git/git/tree/eacee88cf8a27cb141c64433465da2542806facf)
au SHA `eacee88cf8a27cb141c64433465da2542806facf` : **83 007 commits**,
4 876 fichiers suivis, dont **4 871 autorisés** par le filtre de l'inventaire.
Le clone complet occupe environ 386 Mio. Aucun fichier du projet n'est exécuté.

Trois mesures alternent le scan optimisé et une référence indépendante qui garde
les appels `git log -S` individuels et les anciens parcours d'activité. Le cache
du système de fichiers est chaud ; le temps de clonage n'est pas inclus. D'autres
agents travaillaient sur la même machine, ces chiffres ne sont pas un SLA.

| Mesure | Optimisé | Référence complète |
|---|---:|---:|
| Durée médiane | **1,728 s** | 2,416 s |
| Appels Git par scan | **9** | 18 |
| Inventaire médian | 0,175 s | 0,146 s |
| Détection de stack médiane | 0,036 s | 0,037 s |
| Datation médiane | 0,617 s | 0,597 s |
| Historique récent médian | 0,156 s | 0,153 s |
| Activité médiane | **0,704 s** | 1,463 s |

Les profils sérialisés sont **strictement identiques sur les trois paires**. La
mesure détaillée est conservée dans `benchmarks/git-eacee88.json`. Pour reproduire :

```bash
git clone https://github.com/git/git /tmp/codearcheo-benchmark-git
git -C /tmp/codearcheo-benchmark-git checkout --detach eacee88cf8a27cb141c64433465da2542806facf
uv run python scripts/benchmark_scan.py /tmp/codearcheo-benchmark-git --compare --runs 3
```

Les choix qui réduisent le coût :

- Un seul parcours d'activité donne le nombre de commits, les auteurs après
  `.mailmap` et les dates des racines ; cela remplace plusieurs parcours complets.
- Une lecture de l'historique des patches par manifeste date tous ses choix
  techniques. Le delta du nombre d'occurrences reproduit le critère littéral de
  `git log -S`. Les cas multilignes utilisent la fonction de référence.
- Les fichiers, manifestes et changements non commités sont toujours recalculés.
  Aucun cache de profil périmé n'est réintroduit pour atteindre le budget.

La CI vérifie l'équivalence de la datation après suppression, réintroduction et
renommage, ainsi qu'avec plusieurs racines et une mailmap. Elle borne les appels
Git quand on ajoute des dépendances au même manifeste. Un seuil de durée sur une
machine CI variable ne remplace pas la mesure reproductible ci-dessus.

## Avec le graphe syntaxique activé

Après ajout de l'extra `code`, une seconde série de trois paires a été exécutée
avec toutes les grammaires installées et `code_structure` calculé à chaque scan.
Les profils optimisés et de référence restent strictement identiques :

| Mesure | Optimisé + graphe | Référence + graphe |
|---|---:|---:|
| Durée médiane | **1,791 s** | 2,531 s |
| Analyse syntaxique médiane | 0,227 s | 0,226 s |
| Appels Git | 9 | 18 |

Le JSON brut est `benchmarks/git-eacee88-code.json`. Commande de reproduction :

```bash
uv run --all-extras python scripts/benchmark_scan.py /tmp/codearcheo-benchmark-git --compare --runs 3
```

## Vérification après intégration des sources et ADR

Une dernière série utilise le code intégré, avec l'origine GitHub, les ADR
existants, les nouveaux parseurs de stack et toutes les grammaires activés. Les
deux versions ont exactement les mêmes enrichissements ; seuls les parcours de
datation et d'activité sont remplacés pour la référence.

| Mesure | Optimisé intégré | Référence intégrée |
|---|---:|---:|
| Durée médiane | **1,852 s** | 2,584 s |
| Appels Git | **10** | 19 |
| Détection de stack médiane | 0,092 s | 0,091 s |
| Analyse syntaxique médiane | 0,222 s | 0,221 s |
| Origine GitHub médiane | 0,0015 s | 0,0016 s |
| Lecture des ADR médiane | 0,0017 s | 0,0017 s |

Les profils sont encore strictement identiques sur les trois paires. Le dixième
appel Git lit l'origine du projet : il n'ajoute pas de parcours d'historique.
La mesure complète est `benchmarks/git-eacee88-integrated.json`.

## Analyse Go avec le cache chaud, 18 novembre 2026

Sur golang/go au SHA `cc2737b0ca9c8a1a0d1fcc26142277e27152a1f2`, l'analyse
syntaxique à chaud (`code.analyze` avec son inventaire, sans le reste du profil) passe
de 12,5 s à **8,4–8,6 s** sur la même machine. Ce temps n'est pas celui du scan complet.
Le graphe reste identique à celui de la version précédente, à froid comme à chaud :
3 749 modules, 8 259 fichiers ignorés, mêmes symboles et imports résolus.

Les refus déterministes de parsing, notamment le dépassement du budget de nœuds sur
neuf gros fichiers générés, sont désormais mis en cache avec leur motif. Les modules
déjà sérialisés ne sont plus sérialisés une seconde fois, et la sélection de la racine
Go utilise un préfixe de chemin plutôt qu'un parcours des parents. Le cache dépend
toujours du contenu et des versions des parseurs. Cette mesure utilisait encore un cache
JSON d'environ 235 Mo ; la mesure suivante réduit son stockage.

## Cache Go compressé, 18 novembre 2026

Sur le même SHA Go, le cache passe de **224,9 Mio à 14,0 Mio**, soit environ **94 % de
moins**, avec gzip au niveau 1. Les 3 749 modules et 2 537 099 occurrences lexicales sont
conservés. L'empreinte SHA-256 du graphe complet reste identique avant la migration,
pendant celle-ci, sans cache et sur les trois passages suivants.

| État | Durée de `code.analyze` | Nombre de mesures |
|---|---:|---:|
| Ancien cache JSON chaud | 7,75 s | 1 |
| Migration du JSON vers gzip | 9,18 s | 1 |
| Cache vide : parsing et écriture gzip | 26,05 s | 1 |
| Cache gzip chaud | médiane 7,45 s (7,41–7,45 s) | 3 |

Chaque mesure utilise un nouveau processus Python 3.12 sous Linux et exclut le calcul
de l'empreinte finale. Il s'agit de l'analyse syntaxique, sans le reste du scan. Le gain
principal est l'espace disque ; ces quelques passages ne prouvent pas un gain de vitesse
général. Les données sont dans
[`benchmarks/go-code-cache-cc2737b.json`](benchmarks/go-code-cache-cc2737b.json).

Le premier passage réutilise les modules de l'ancien JSON, écrit le cache gzip puis retire
le fichier ancien seulement après une écriture réussie. Un cache absent, invalide ou
trop volumineux entraîne un nouveau parsing ; il n'empêche pas le scan. La lecture est
bornée à 512 Mio de données décompressées. Les tests couvrent aussi l'échec d'écriture,
les liens symboliques et une entrée de module corrompue qui doit être réparée durablement.

Pour mesurer un passage chaud sur le clone local de l'évaluation :

```bash
uv run --all-extras python - <<'PY'
import hashlib
import time
from pathlib import Path
from codearcheo.analyzers import code
root = Path.home() / ".cache/codearcheo/evals/go"
started = time.perf_counter()
graph = code.analyze(root)
print("secondes", time.perf_counter() - started)
print("graphe SHA-256", hashlib.sha256(graph.model_dump_json().encode()).hexdigest())
PY
```
