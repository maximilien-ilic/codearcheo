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
git clone https://github.com/git/git /tmp/learn-it-benchmark-git
git -C /tmp/learn-it-benchmark-git checkout --detach eacee88cf8a27cb141c64433465da2542806facf
uv run python scripts/benchmark_scan.py /tmp/learn-it-benchmark-git --compare --runs 3
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
uv run --all-extras python scripts/benchmark_scan.py /tmp/learn-it-benchmark-git --compare --runs 3
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
toujours du contenu et des versions des parseurs. Il occupe encore environ 235 Mo :
sa réduction reste une optimisation possible.
