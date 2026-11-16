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
