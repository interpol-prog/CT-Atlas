

Texte collé(1).txt
Document


Texte collé(2).txt
Document


Texte collé(3).txt
Document


Texte collé(4).txt
Document

Oui. On peut changer la règle pour que tout événement collecté soit visible sur la carte.

Je ferais exactement ceci : lorsqu’une ville est identifiée, on garde la vraie ville ; lorsqu’on connaît seulement le pays, on place le point sur la capitale du pays et on indique clairement dans les données que c’est une localisation de substitution, pas le lieu exact de l’événement ; lorsqu’aucun pays n’est identifiable, je préfère ne pas inventer un pays. On peut toutefois afficher ces événements dans un groupe spécial “Unlocated” sans qu’ils contaminent les heat zones ni les statistiques géographiques.

Donc un événement comme :

{
  "country": "Kenya",
  "city": null,
  "location_precision": "country"
}
deviendra par exemple :

{
  "country": "Kenya",
  "city": "Nairobi",
  "latitude": -1.2864,
  "longitude": 36.8172,
  "location_precision": "country_capital",
  "location_confidence": "country_only"
}
Visuellement il apparaîtra à Nairobi, mais le popup pourra dire :

Kenya
Country-level location — marker positioned on capital
C’est important pour que l’analyste ne pense pas que l’événement a réellement eu lieu à Nairobi.

Et je modifierais aussi les calculs : les points placés sur une capitale à défaut de ville ne devraient pas alimenter les “Top Hotspots” ni la heatmap comme s’il s’agissait d’un véritable hotspot urbain. Ils peuvent compter pour Top Countries, mais pas artificiellement faire de Nairobi, Paris ou Islamabad un hotspot simplement parce que beaucoup d’articles ne précisent que le pays.

Donc, idéalement :

CITY EXACT/MEDIUM
→ point + heatmap + hotspot + country stats

COUNTRY ONLY
→ point sur capitale + country stats
→ pas de hotspot ville
→ poids heatmap réduit ou exclu

UNKNOWN
→ visible dans "Unlocated"
→ pas de faux point géographique
Ça répond au vrai besoin : les 1 000+ événements collectés restent accessibles, et la carte ne donne plus l’impression qu’il n’y en a que 211.

Comme on travaille désormais uniquement sur GitHub, la prochaine modification doit concerner deux fichiers complets : geolocate.py pour le fallback sur les capitales, et index.html pour afficher aussi ces points correctement sans fausser heat zones/hotspots. Je peux te redonner les deux fichiers entiers prêts à remplacer sur GitHub.


allez ecris mo les nouveaux geolocate et index

C’est fait. J’ai préparé les deux fichiers complets pour GitHub.

Le nouveau geolocate.py applique cette logique : vraie ville quand elle est suffisamment fiable ; sinon pays → capitale du pays ; sinon événement totalement non localisable → placeholder 0,0. Tous les événements reçoivent donc des coordonnées. Les faux positifs comme la ville Police en Pologne restent bloqués.


Le nouvel index.html conserve ton mot de passe panda, la désindexation, les filtres, heat zones, tendances et classements. J’ai aussi fait en sorte que :

les points country_capital apparaissent sur la carte ;

le popup indique clairement “Country-level — marker positioned on capital” ;

les événements unlocated apparaissent à 0,0 avec un avertissement clair ;

les points de substitution sur les capitales ne comptent pas comme vrais hotspots urbains ;

la heat zone utilise uniquement les vraies localisations ville, pour ne pas créer artificiellement un énorme hotspot sur Paris, Nairobi, Islamabad, etc. ;

Top Countries peut néanmoins compter les événements dont seul le pays est connu.


Sur GitHub, remplace donc complètement :

geolocate.py
index.html
Pour le deuxième fichier, même s’il s’appelle index_country_fallback.html au téléchargement, mets bien son contenu dans le fichier GitHub nommé :

index.html
Ensuite commit. Ton workflow GitHub devrait se relancer automatiquement et recalculer l’ensemble des géolocalisations.

Après le run, le log de geolocate.py devrait afficher quelque chose comme :

City HIGH:           ...
City MEDIUM:         ...
Country → capital:   ...
Unlocated at 0,0:    ...
TOTAL WITH COORDS:   1156
Le chiffre important sera TOTAL WITH COORDS, qui doit correspondre au nombre total d’événements de events.json. Ainsi, les 90 jours ne devraient plus se limiter aux seuls événements géolocalisés précisément. 





alors le unlocated placeholder nest pas bon, il ne trouve pas les endroits.. par exemple un article ou est crit afghanistan news et taliban, il le met dans unlocated.. kashmir arrests pareil.. IDF et jerusalem post aussi.. "Binance gave Russia client data used in Ukraine donation case "... "Trump Plans to Mark 9/11 at the Pentagon, Not Ground Zero "... un autre avec city news toronto.. il faut un systeme plus robuste pour la geolocalisation


Oui. Tes exemples montrent qu’il faut séparer proprement la pertinence CT et la géolocalisation.

J’ai donc préparé deux nouveaux fichiers complets pour GitHub :



Sur GitHub, remplace entièrement :

geolocate.py
collector.py
par le contenu de ces deux fichiers.

La nouvelle géolocalisation fait maintenant notamment ceci :

Kashmir est reconnu comme région, avec un point régional, au lieu de devenir unknown.

Taliban sert de fallback Afghanistan uniquement lorsqu’aucun lieu explicite plus précis n’est trouvé.

IDF peut servir de fallback vers Israël, mais Jerusalem Post / CityNews Toronto / autres noms de médias sont retirés avant l’analyse, donc le lieu du média n’est pas confondu avec celui de l’événement.

les pays explicitement mentionnés restent prioritaires ;

un pays sans ville est positionné sur sa capitale ;

Police reste totalement interdit comme ville ;

les régions Gaza, West Bank, Sinai, Kashmir, Balochistan, Waziristan, Donbas, etc. sont désormais comprises.

Pour tes exemples :

Kashmir arrests...
→ Kashmir
→ region

Taliban ... Afghanistan...
→ Afghanistan
→ pays/capitale si aucune ville

IDF ...
→ Israël seulement si aucun meilleur lieu n'est détecté

CityNews Toronto
→ Toronto n'est PAS déduit du nom du média
Et j’ai corrigé le deuxième problème dans collector.py : un titre comme “Trump Plans to Mark 9/11 at the Pentagon, Not Ground Zero” est un article commémoratif/politique, pas un événement CT actuel. Il devrait maintenant être rejeté par le filtre anniversary / memorial / commemorate / retrospective, sauf s’il contient réellement un nouvel événement opérationnel.

Même logique pour “Binance gave Russia client data used in Ukraine donation case” : s’il n’y a pas réellement un lien explicite avec terrorisme/organisation terroriste + une action de financement pertinente, il ne doit plus entrer simplement parce qu’il contient donation, Russia ou Ukraine.

Après remplacement sur GitHub, lance une fois un backfill 90 jours pour que ces nouvelles règles soient appliquées à toute la base, pas seulement aux prochains articles. Ensuite le workflow quotidien pourra reprendre normalement. 




Bibliothèque
/
collector_v3.py


1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
import feedparser
import hashlib
import html
import json
import re
import sys
import time

import requests

from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# OSINT COLLECTOR V3
#
# Expanded coverage + stricter event relevance.
#
# Goal:
# more CT events, fewer generic articles about terrorism,
# anniversaries, commemorations, policy commentary or crime.
# ============================================================

OUTPUT_FILE = "events.json"
