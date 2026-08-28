Oui. J’ai préparé la version AI-first à 100 %.

Désormais, aucun événement ne sera placé parce que Worth, Mobile, Reading, Police, etc. correspondent mécaniquement à un nom de ville. GPT-5.6 Sol analyse sémantiquement chaque événement — titre, résumé, source, catégories et titres des articles fusionnés — puis GeoNames intervient seulement après pour valider/résoudre le lieu en coordonnées. GPT-5.6 Sol est actuellement le modèle OpenAI le plus puissant de cette gamme, et l’API Responses permet de forcer une sortie structurée JSON Schema.

Les deux fichiers à remplacer

geolocate.py — AI-FIRST

.github/workflows/update-map.yml — AI-FIRST

Ton requirements.txt actuel suffit : le script utilise déjà requests et geonamescache.

Avant de lancer le workflow, il faut une seule configuration GitHub : dans ton repository, va dans Settings → Secrets and variables → Actions → New repository secret, crée :

Name:
OPENAI_API_KEY

Secret:
ta_clé_API_OpenAI

Ne mets jamais la clé directement dans geolocate.py.

Ce que fera maintenant GeoLocate

Pour absolument chaque nouvel événement :

Article
  ↓
GPT-5.6 Sol analyse le sens complet
  ↓
Quelle est la localisation DE L'ÉVÉNEMENT ?
  ↓
City / Region / Country / Unknown
  ↓
GeoNames valide le lieu
  ↓
coordonnées

Le prompt lui dit explicitement que :

"Worth" ≠ automatiquement Worth, USA
"Mobile" ≠ automatiquement Mobile, Alabama
"Police" ≠ automatiquement Police, Poland

Jerusalem Post + attack in France
→ France

IDF + operation in Gaza
→ Gaza / Palestinian Territory

Taliban + Afghan security context
→ Afghanistan

Kashmir + Indian authorities
→ Kashmir / India

Kashmir + Pakistani authorities
→ Kashmir / Pakistan

Il peut aussi raisonner à partir d’une personnalité, organisation, institution, média local, tribunal, service de police, nationalité, landmark, région, articles associés, etc.

Il y a même une deuxième passe IA

Si GPT laisse encore quelque chose unlocated, le système lui renvoie ces événements avec une consigne plus poussée :

cherche au minimum le pays le plus probable en utilisant tout le contexte disponible.

Donc ce n’est plus :

règles → IA si échec

mais :

IA → IA plus insistante si échec.

Et ça ne repaye pas toute la base chaque matin

“IA toujours” signifie que chaque décision géographique provient de l’IA. Mais une fois un événement analysé, sa décision est sauvegardée dans events.json :

ai_geo_version
ai_geo_model
ai_geo_fingerprint
ai_geo_complete
ai_geo_reason

Le lendemain, si l’article n’a pas changé, il n’est pas renvoyé inutilement à l’API.

Donc typiquement :

BACKFILL 180 jours
1300 événements
→ 1300 analysés par IA

lendemain
50 nouveaux événements
→ seulement les ~50 nouveaux analysés

lendemain suivant
35 nouveaux
→ seulement les ~35 nouveaux

Et ils sont traités par lots de 20, donc 1 300 événements représentent environ 65 requêtes API plutôt que 1 300 requêtes distinctes.

Le nouveau workflow remet aussi correctement le backfill

Dans Actions → Run workflow, tu auras :

mode
  daily
  backfill

force_ai
  false
  true

Pour la première installation de cette version, fais :

mode: backfill
force_ai: true

Ainsi les 6 mois entiers seront reconstruits et tous les événements seront géolocalisés par GPT-5.6 Sol.

Ensuite, les mises à jour quotidiennes se feront automatiquement avec le cache.

Le modèle Sol est actuellement affiché à $4 par million de tokens d'entrée et $20 par million de tokens de sortie ; le backfill initial coûtera donc plus que les petites mises à jour quotidiennes, mais les réponses géographiques sont très courtes et les appels sont regroupés.

C’est, à mon sens, le changement qui devrait éliminer le plus radicalement les aberrations de géolocalisation qu’on rencontrait avec les systèmes basés sur les mots. 

geolocate_ai_first.py
Code
update-map_ai_first.yml
Code
il y a pas de IA gratuite?

Oui. Pour ton usage, il existe des options gratuites, et on peut tout à fait remplacer OpenAI par une IA gratuite pour la géolocalisation.

La meilleure option gratuite actuellement me semble être Groq Free Tier avec un modèle comme openai/gpt-oss-120b ou qwen/qwen3.8-27b. Groq propose bien un Free Plan avec jusqu’à 1 000 requêtes/jour sur plusieurs de ces modèles et environ 200 000 tokens/jour sur certains modèles.

Pour ton cas, c’est intéressant parce que tu ne fais pas du chat : tu demandes seulement quelque chose comme :

Article:
"Police arrest ISIS suspect in Düsseldorf..."

Return:
country = Germany
city = Düsseldorf
region = North Rhine-Westphalia
confidence = 0.96

Donc les sorties sont très courtes. Et après le premier backfill, seuls les nouveaux événements quotidiens doivent être analysés.

Une autre possibilité est Gemini API, qui possède actuellement un véritable niveau gratuit avec entrée et sortie sans frais sur certains modèles. En revanche, Google précise que, sur le niveau gratuit, le contenu peut être utilisé pour améliorer ses produits. Pour un projet professionnel CT, même si les données sont OSINT, je serais plus prudent avec cette option.

Hugging Face offre aussi du gratuit, mais seulement 0,10 $ de crédits mensuels pour un compte Free, donc ce n’est pas vraiment suffisant pour notre carte.

Ce que je choisirais

Pour commencer :

Groq + openai/gpt-oss-120b

Architecture :

article
   ↓
Groq free API
   ↓
GPT-OSS 120B
   ↓
compréhension sémantique du lieu
   ↓
GeoNames
   ↓
coordonnées

Et on conserve exactement le principe que tu voulais :

100 % des événements passent par l’IA.

Donc plus de :

Worth → Worth, Texas ❌
Police → Police, Poland ❌
Mobile → Mobile, Alabama ❌

simplement parce qu’un mot correspond à une ville.

Avec le quota actuel de Groq, 1 000 requêtes/jour et notre traitement par lots, c’est très largement suffisant pour les mises à jour quotidiennes.

Pour le premier backfill de ~1 000–2 000 événements, on peut aussi envoyer 10–20 événements par requête, ce qui ne représente qu'environ 50–200 requêtes.

Il faudrait simplement créer gratuitement une clé Groq et la mettre dans GitHub Secrets comme :

GROQ_API_KEY

Puis je remplace le geolocate.py OpenAI que je viens de faire par une version Groq AI-first gratuite, et le workflow utilisera Groq automatiquement. C’est probablement la solution que je choisirais pour cette carte avant de payer une API.

si gemini est mieux que groq, fais gemini, je men fous quils collectent

C’est fait. Pour ton cas précis de géolocalisation sémantique, je passe à Gemini 2.5 Flash : raisonnement, sortie JSON structurée et niveau gratuit. Google indique actuellement que l’entrée et la sortie de Gemini 2.5 Flash sont gratuites sur le Free Tier.

1. Remplace entièrement geolocate.py

Télécharger geolocate.py — Gemini AI-first

Cette version fait passer 100 % des événements par Gemini. GeoNames ne décide plus qu’un mot est une ville ; il valide seulement le lieu que Gemini a compris sémantiquement.

Donc :

"Worth considering..."
≠ Worth, USA

"Police said..."
≠ Police, Poland

"Reading the statement..."
≠ Reading, UK

Gemini analyse le titre + résumé + source + catégories + articles liés, puis décide du lieu réel de l’événement.

2. Remplace entièrement le workflow

Télécharger update-map.yml — Gemini

Il utilise :

gemini-2.5-flash
thinking budget: 4096
batch: 20 événements

Gemini 2.5 Flash supporte justement un budget de raisonnement configurable.

3. Crée gratuitement ta clé Gemini

Va dans Google AI Studio et crée une clé API : Créer une clé Gemini API

Puis dans GitHub :

Repository → Settings → Secrets and variables → Actions → New repository secret

Nom :

GEMINI_API_KEY

Valeur : ta clé Gemini.

Ne mets jamais la clé directement dans geolocate.py.

4. Premier lancement

Dans GitHub :

Actions → Daily CT Intelligence Map Update → Run workflow

Choisis :

mode: backfill
force_ai: true

La première fois, Gemini recalculera toute la géolocalisation des 180 jours.

J’ai volontairement changé la version du cache en :

gemini-ai-first-v2

Donc même les événements précédemment géolocalisés par notre ancien système seront réanalysés par Gemini.

Ensuite, les jours suivants :

nouveaux événements
        ↓
Gemini
        ↓
lieu de l'événement
        ↓
GeoNames validation
        ↓
coordonnées
        ↓
carte

Les événements déjà analysés et inchangés restent en cache, donc tu ne consommes pas inutilement le quota gratuit chaque jour.

Gemini renvoie également une confiance, la raison, les éléments géographiques utilisés, et distingue city, region, country ou unknown. Les sorties structurées JSON sont officiellement supportées par l’API Gemini.

Tu n’as pas besoin de modifier collector.py pour passer à Gemini. 

geolocate_gemini_ai_first.py
Code
update-map_gemini_ai_first.yml
Code
