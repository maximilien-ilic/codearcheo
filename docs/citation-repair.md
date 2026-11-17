# Correction facultative des citations

La vérification des références reste locale et sans appel IA supplémentaire par défaut.
`Session.repair_citations=True` autorise une seule tentative pour les réponses textuelles
de `ask`, `why` et `overview` lorsque des références sont invalides. Une réponse sans
référence ne déclenche pas d'invention de sources. Les décisions et recommandations
structurées sont vérifiées et signalées, sans correction indépendante de leurs enregistrements.

Le modèle reçoit la réponse initiale, les références invalides, quelques extraits bornés de
fichiers autorisés et des commits récents. Aucun fichier ignoré, lien ou secret connu n'est
ajouté au contexte. Tous les textes du dépôt sont marqués comme données non fiables. La
requête n'a aucun outil et n'autorise qu'une itération ; aucune relance de réparation ne suit
une erreur ou une réponse rejetée. Cette option peut donc consommer un appel API de plus.

Le modèle propose un plan JSON de remplacement des références, pas une nouvelle réponse.
Le programme applique uniquement les références invalides reconnues à leurs positions
exactes : les phrases, conclusions, références valides et le diagramme Mermaid restent
inchangés. Une référence proposée doit exister et ne contenir aucun texte supplémentaire.
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
