# Correction facultative des citations

```bash
learn-it ask "Comment fonctionne le stockage ?" --repair-citations --max-requests 4
learn-it why src/storage.py --repair-citations --max-output-tokens 2048
```

La vérification des références reste locale et sans appel IA supplémentaire par défaut.
`Session.repair_citations=True` autorise une seule tentative pour les réponses textuelles
de `ask`, `why` et `overview` lorsque des références sont invalides. Une réponse sans
référence ne déclenche pas d'invention de sources. Les décisions et recommandations
structurées sont vérifiées et signalées, sans correction indépendante de leurs enregistrements.

L'export ADR vérifie aussi les citations du titre, du contexte, de la décision, de la
justification, des alternatives et des conséquences. Les références invalides figurent
dans « Preuves non vérifiées ». Une citation dans ce texte ne remplace pas la liste des
preuves déclarées : sans preuve déclarée vérifiable, `--allow-unproven` reste nécessaire
et l'ADR conserve son avertissement.

Une complétion locale précède désormais cette étape pour les réponses non diffusées et
les preuves structurées : `timed.py:170` devient le chemin complet si l'inventaire ou les
chemins déjà cités lèvent l'ambiguïté. Elle préserve les chemins existants à la racine,
les chemins explicites `./…` et les blocs de code ; les lignes sont ensuite vérifiées.
Elle ne consomme aucun appel IA. En streaming API et dans `chat`, le corps déjà affiché
reste intact et ses références originales sont contrôlées. Les métriques de correction IA
comparent la réponse après cette complétion à la proposition du modèle ; elles ne mesurent
pas séparément le gain de la complétion locale.

Le modèle reçoit la réponse initiale, les références invalides, quelques extraits bornés de
fichiers autorisés et des commits récents. Aucun fichier ignoré, lien ou secret connu n'est
ajouté au contexte. Tous les textes du dépôt sont marqués comme données non fiables. La
requête n'a aucun outil et n'autorise qu'une itération. Elle possède un garde local d'une
tentative réseau et désactive les retries automatiques ; aucune relance de réparation ne
suit une erreur ou une réponse rejetée. Sa sortie est bornée à 4 096 tokens, ou à la limite
de sortie choisie si elle est inférieure. Cette option peut consommer un appel API de plus.
La même limite globale de session couvre l'analyse et la correction. Si le quota est épuisé,
la réponse initiale et ses avertissements sont conservés.

Avec `LEARN_IT_BACKEND=claude-code`, la correction passe aussi par l'abonnement : un appel
`claude -p` d'un seul tour, sans outil intégré ni serveur MCP, avec le même prompt système
et la même acceptation locale. `claude -p` ne permet pas de borner la sortie, et ce moteur
n'a pas de limite locale de requêtes : la seule garantie est l'unique tour.

Le modèle propose un plan JSON de remplacement des références, pas une nouvelle réponse.
Le programme applique uniquement les références invalides reconnues à leurs positions
exactes : le texte extérieur à ces fragments, les références valides et le diagramme
Mermaid restent inchangés. Il n'accepte jamais une réécriture libre de la réponse.
Une référence proposée doit exister et ne contenir aucun texte supplémentaire.
Le modèle doit choisir un remplacement seulement si l'extrait soutient la même affirmation.
Les blocs de code ou Mermaid, fermés ou non, sont exclus des références à corriger.
Les formes réseau reconnues (IP, URL, nom d'hôte sans suffixe de code/texte) avec port
ne déclenchent pas de correction. Pour éviter de les confondre avec des sources, un
nom de fichier isolé exige une extension de code/texte reconnue ou un nom de manifeste
connu ; une extension personnalisée doit utiliser un chemin explicite, par exemple
`./schema.custom:1`. Ce classement reste lexical : un nom de domaine portant aussi une
extension de source, tel que `server.go`, reste ambigu.
Une référence isolée à un fichier absent, telle que `missing.py:9`, reste signalée mais
n'est jamais devinée ni modifiée ; elle ne provoque aucun appel supplémentaire si aucune
autre référence n'est corrigeable. Une référence de cette forme n'est éligible que si le
fichier existe dans l'inventaire autorisé, ou si un chemin explicite (`./missing.py:9`,
`src/missing.py:9`) indique l'intention de citer une source. Cette prudence conserve aussi
un hôte `server.go:8080` qui ne correspond à aucun fichier source.

La proposition est retenue uniquement si le nombre de références invalides baisse, si les
références valides initiales sont conservées et si au moins une référence valide subsiste.
Les références valides de l'instantané initial restent exigées même si le projet change
pendant la requête : leur disparition ne peut pas être masquée par d'autres corrections.
Retirer toutes les sources n'est jamais une amélioration. Une erreur, un plan vide, une
réécriture libre ou une régression conserve la réponse initiale et ses avertissements.
Les réponses trop longues (12 000 caractères), plus de 20 références invalides ou un contexte
trop volumineux ne déclenchent pas de correction. Les extraits totalisent au plus 8 000
caractères ; le contenu complet des fichiers n'est pas envoyé.

En mode correction, le texte est mis en mémoire avant affichage pour éviter de mélanger une
première réponse et sa version corrigée. Le rapport indique les comptes mécaniques avant et
après. `Session.last_repair` expose une copie de ces métriques, la réponse initiale exacte et
la réponse retenue pour des comparaisons hors réseau. Le dossier `.learn-it/` conserve aussi
un rapport `overview-initial-<empreinte>.md` lorsqu'une correction d'overview est retenue.

Les tests avec client simulé mesurent les références existantes, les refus et la conservation
du contenu. Ils ne prouvent ni l'implication logique d'une source ni la vérité des affirmations.
Aucun gain sur les vraies réponses de Claude n'est revendiqué : sa mesure reste suivie dans
le ticket #10 avec les accès et dépenses API correspondants.

## Comparer plus tard avec l'API réelle

```bash
uv run python -m evals.run shop --compare-citations --max-requests 6 --max-output-tokens 2048
```

Cette commande consomme des tokens API ; elle n'a pas été exécutée pour ce travail.
Sur l'abonnement, sans clé API ni plafond local :

```bash
uv run --all-extras python -m evals.run --backend claude-code --compare-citations
```

`--compare-citations` conserve les réponses initiale et retenue, les références invalides,
les contrôles et les scores avant/après issus de la même analyse. Les tokens, le coût estimé
et la durée sont enregistrés par cas. Il n'y a pas deux analyses de départ indépendantes.
Les cas structurés `decisions` et `review` sont évalués normalement, sans réparation
indépendante de leurs enregistrements.

Le plafond de requêtes est partagé par tous les cas et projets de l'exécution, pas
réinitialisé à chaque cas. Une limite trop courte peut arrêter l'évaluation ; ce résultat
incomplet ne constitue pas une mesure de qualité du modèle. Ces plafonds ne garantissent
aucun montant de facture, notamment pour les tokens d'entrée et les traitements internes
du fournisseur. `--repair-citations` seul active la correction sans enregistrer les scores
comparatifs ; le mode normal conserve les vérifications et n'ajoute aucun appel de correction.
