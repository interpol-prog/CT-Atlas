import json
import math
import re
from collections import Counter, defaultdict

import geonamescache


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# CONTEXTUAL GEOLOCATION V4
#
# Multi-signal, two-pass geolocation:
#
# PASS 1 — intrinsic evidence
#   1. Explicit city
#   2. Landmark / facility
#   3. Region / province
#   4. Explicit country
#   5. Demonym / nationality
#   6. Institution / security service
#   7. Known organisation
#   8. Known public personality
#
# LEARNING
#   - Learns recurring source -> country associations
#   - Learns recurring named-entity -> country associations
#     from high-confidence events in the same 90-day database.
#
# PASS 2 — unresolved / weak events
#   - Re-runs city matching using the inferred country
#   - Uses learned entities
#   - Uses local/regional source country as a LOW-confidence fallback
#
# FINAL FALLBACK
#   - If only the country can be inferred, marker is positioned on
#     that country's capital and explicitly marked country_capital.
#   - If absolutely no geographic signal exists, event is left at
#     the neutral 0,0 placeholder and marked unlocated.
#
# The source/outlet is NEVER treated as the event location unless
# no better evidence exists; it is a final country-level fallback.
# ============================================================


INPUT_FILE = "events.json"
OUTPUT_FILE = "events.json"

MIN_CITY_POPULATION = 5000

gc = geonamescache.GeonamesCache(
    min_city_population=MIN_CITY_POPULATION
)

cities = gc.get_cities()
countries = gc.get_countries()


# ============================================================
# COUNTRY ALIASES
# ============================================================

COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "us": "United States",
    "america": "United States",

    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",

    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "emirates": "United Arab Emirates",

    "drc": "Congo, The Democratic Republic of the",
    "dr congo": "Congo, The Democratic Republic of the",
    "democratic republic of congo": "Congo, The Democratic Republic of the",

    "congo kinshasa": "Congo, The Democratic Republic of the",
    "congo-kinshasa": "Congo, The Democratic Republic of the",

    "congo brazzaville": "Congo",
    "congo-brazzaville": "Congo",

    "ivory coast": "Côte d'Ivoire",

    "russia": "Russian Federation",
    "iran": "Iran, Islamic Republic of",
    "syria": "Syrian Arab Republic",
    "south korea": "Korea, Republic of",
    "north korea": "Korea, Democratic People's Republic of",
    "venezuela": "Venezuela, Bolivarian Republic of",
    "tanzania": "Tanzania, United Republic of",
    "bolivia": "Bolivia, Plurinational State of",
    "moldova": "Moldova, Republic of",
    "laos": "Lao People's Democratic Republic of",
    "brunei": "Brunei Darussalam",

    "palestine": "Palestinian Territory",
    "palestinian territories": "Palestinian Territory",
    "palestinian territory": "Palestinian Territory",

    "czech republic": "Czechia",
    "burma": "Myanmar",

    "cape verde": "Cabo Verde",

    "eswatini": "Eswatini",
    "swaziland": "Eswatini",
}


# ============================================================
# DEMONYMS / NATIONALITY TERMS
#
# Particularly useful when a headline says "Iraqi official",
# "Afghan Taliban", "Somali militants", etc. without naming
# the country explicitly.
# ============================================================

DEMONYMS = {
    "afghan": "AF",
    "afghans": "AF",
    "afghanistani": "AF",

    "algerian": "DZ",
    "angolan": "AO",
    "argentine": "AR",
    "argentinian": "AR",
    "australian": "AU",
    "austrian": "AT",

    "bahraini": "BH",
    "bangladeshi": "BD",
    "belgian": "BE",
    "beninese": "BJ",
    "burkinabe": "BF",
    "burkinabè": "BF",

    "cameroonian": "CM",
    "canadian": "CA",
    "chadian": "TD",
    "chilean": "CL",
    "chinese": "CN",
    "colombian": "CO",
    "congolese": "CD",

    "danish": "DK",
    "dutch": "NL",

    "egyptian": "EG",
    "emirati": "AE",
    "ethiopian": "ET",

    "french": "FR",

    "german": "DE",
    "ghanaian": "GH",
    "greek": "GR",

    "indian": "IN",
    "indonesian": "ID",
    "iranian": "IR",
    "iraqi": "IQ",
    "irish": "IE",
    "israeli": "IL",
    "italian": "IT",

    "jordanian": "JO",

    "kenyan": "KE",
    "kuwaiti": "KW",

    "lebanese": "LB",
    "libyan": "LY",

    "malaysian": "MY",
    "malian": "ML",
    "mauritanian": "MR",
    "moroccan": "MA",
    "mozambican": "MZ",
    "myanmar": "MM",
    "burmese": "MM",

    "nigerian": "NG",
    "nigerien": "NE",

    "pakistani": "PK",
    "palestinian": "PS",
    "philippine": "PH",
    "filipino": "PH",
    "polish": "PL",

    "qatari": "QA",

    "russian": "RU",
    "rwandan": "RW",

    "saudi": "SA",
    "senegalese": "SN",
    "somali": "SO",
    "somalian": "SO",
    "south african": "ZA",
    "spanish": "ES",
    "sudanese": "SD",
    "syrian": "SY",

    "tajik": "TJ",
    "tunisian": "TN",
    "turkish": "TR",

    "ugandan": "UG",
    "ukrainian": "UA",
    "uzbek": "UZ",

    "yemeni": "YE",

    "zimbabwean": "ZW",

    "american": "US",
    "british": "GB",
}


# ============================================================
# REGIONAL GAZETTEER
#
# Representative coordinates, not exact incident coordinates.
# ============================================================

REGIONS = {
    "jammu and kashmir": ("Jammu and Kashmir", "IN", 34.0837, 74.7973),
    "indian-administered kashmir": ("Indian-administered Kashmir", "IN", 34.0837, 74.7973),
    "india-administered kashmir": ("Indian-administered Kashmir", "IN", 34.0837, 74.7973),
    "azad kashmir": ("Azad Kashmir", "PK", 34.3700, 73.4700),
    "pakistan-administered kashmir": ("Pakistan-administered Kashmir", "PK", 34.3700, 73.4700),
    "pakistani-administered kashmir": ("Pakistan-administered Kashmir", "PK", 34.3700, 73.4700),
    "kashmir": ("Kashmir", None, 34.0837, 74.7973),

    "gaza strip": ("Gaza Strip", "PS", 31.5017, 34.4668),
    "gaza": ("Gaza Strip", "PS", 31.5017, 34.4668),
    "west bank": ("West Bank", "PS", 31.9466, 35.3027),

    "sinai peninsula": ("Sinai", "EG", 29.5000, 33.8000),
    "sinai": ("Sinai", "EG", 29.5000, 33.8000),

    "balochistan": ("Balochistan", "PK", 28.5000, 65.0000),
    "baluchistan": ("Balochistan", "PK", 28.5000, 65.0000),
    "khyber pakhtunkhwa": ("Khyber Pakhtunkhwa", "PK", 34.0000, 71.5000),
    "kp province": ("Khyber Pakhtunkhwa", "PK", 34.0000, 71.5000),
    "north waziristan": ("North Waziristan", "PK", 32.9500, 69.9000),
    "south waziristan": ("South Waziristan", "PK", 32.3000, 69.9000),
    "waziristan": ("Waziristan", "PK", 32.7500, 69.8500),

    "kurdistan region": ("Kurdistan Region", "IQ", 36.1900, 44.0000),
    "iraqi kurdistan": ("Kurdistan Region", "IQ", 36.1900, 44.0000),

    "dagestan": ("Dagestan", "RU", 42.9800, 47.5000),
    "chechnya": ("Chechnya", "RU", 43.3000, 45.7000),
    "ingushetia": ("Ingushetia", "RU", 43.1700, 44.8200),
    "north caucasus": ("North Caucasus", "RU", 43.5000, 44.0000),

    "donbas": ("Donbas", "UA", 48.0000, 37.8000),
    "donbass": ("Donbas", "UA", 48.0000, 37.8000),

    "cabo delgado": ("Cabo Delgado", "MZ", -12.5000, 40.0000),

    "puntland": ("Puntland", "SO", 8.4000, 48.5000),
    "somaliland": ("Somaliland", "SO", 9.5500, 44.0500),

    "mindanao": ("Mindanao", "PH", 7.5000, 125.0000),
    "sulu": ("Sulu", "PH", 5.9500, 121.1000),

    "rakhine": ("Rakhine State", "MM", 20.1500, 93.1000),
    "rakhine state": ("Rakhine State", "MM", 20.1500, 93.1000),
    "shan state": ("Shan State", "MM", 21.5000, 98.0000),

    "sahel": ("Sahel", None, 15.5000, 2.0000),
    "lake chad basin": ("Lake Chad Basin", None, 13.0000, 14.0000),
}


# ============================================================
# LANDMARKS / FACILITIES
#
# These are strong geographic clues even when a city/country
# name is absent.
# ============================================================

LANDMARK_HINTS = {
    "pentagon": ("US", "Washington"),
    "ground zero": ("US", "New York City"),
    "world trade center": ("US", "New York City"),
    "white house": ("US", "Washington"),
    "capitol hill": ("US", "Washington"),

    "downing street": ("GB", "London"),
    "westminster": ("GB", "London"),

    "elysee palace": ("FR", "Paris"),
    "élysée palace": ("FR", "Paris"),

    "kremlin": ("RU", "Moscow"),

    "knesset": ("IL", "Jerusalem"),

    "kamiti": ("KE", "Nairobi"),
    "kamiti maximum security prison": ("KE", "Nairobi"),

    "bagram": ("AF", "Bagram"),
    "bagram air base": ("AF", "Bagram"),

    "guantanamo bay": ("CU", None),
    "guantánamo bay": ("CU", None),

    "pul-e-charkhi": ("AF", "Kabul"),
    "pul-i-charkhi": ("AF", "Kabul"),
}


# ============================================================
# INSTITUTIONS / SECURITY SERVICES / PUBLIC AUTHORITIES
# ============================================================

ENTITY_HINTS = {
    # United States
    "fbi": "US",
    "federal bureau of investigation": "US",
    "cia": "US",
    "central intelligence agency": "US",
    "department of homeland security": "US",
    "homeland security": "US",
    "us department of justice": "US",
    "u.s. department of justice": "US",
    "us treasury": "US",
    "u.s. treasury": "US",
    "centcom": "US",

    # Canada
    "rcmp": "CA",
    "royal canadian mounted police": "CA",
    "csis": "CA",

    # United Kingdom
    "mi5": "GB",
    "mi6": "GB",
    "scotland yard": "GB",
    "metropolitan police": "GB",
    "counter terrorism policing": "GB",

    # France
    "dgsi": "FR",
    "dgse": "FR",
    "gign": "FR",

    # Germany
    "bka": "DE",
    "bundeskriminalamt": "DE",
    "bfv": "DE",

    # Israel
    "idf": "IL",
    "israel defense forces": "IL",
    "israel defence forces": "IL",
    "shin bet": "IL",
    "shabak": "IL",
    "mossad": "IL",

    # India
    "nia": "IN",
    "national investigation agency": "IN",
    "crpf": "IN",
    "bsf": "IN",

    # Pakistan
    "nacta": "PK",
    "isi": "PK",
    "pakistan ctd": "PK",
    "counter terrorism department": "PK",

    # Russia / Ukraine
    "fsb": "RU",
    "sbu": "UA",

    # Nigeria
    "dss nigeria": "NG",
    "nigerian dss": "NG",

    # Kenya
    "atpu": "KE",
    "anti-terrorism police unit": "KE",
    "dci kenya": "KE",

    # Somalia
    "nisa": "SO",
    "somalia nisa": "SO",
}


# ============================================================
# TERRORIST / MILITANT ORGANISATION PRIORS
#
# Low-to-medium country evidence only.
# ============================================================

ORG_HINTS = {
    "taliban": "AF",
    "haqqani network": "AF",
    "isis-k": "AF",
    "isis k": "AF",
    "islamic state khorasan": "AF",
    "islamic state-khorasan": "AF",

    "ttp": "PK",
    "tehrik-i-taliban pakistan": "PK",
    "tehreek-e-taliban pakistan": "PK",
    "lashkar-e-taiba": "PK",
    "jaish-e-mohammed": "PK",

    "al-shabaab": "SO",
    "al shabaab": "SO",

    "boko haram": "NG",
    "iswap": "NG",

    "hamas": "PS",
    "palestinian islamic jihad": "PS",

    "hezbollah": "LB",
    "hizballah": "LB",
    "hizbollah": "LB",

    "houthis": "YE",
    "ansar allah": "YE",
}


# ============================================================
# PUBLIC PERSONALITY PRIORS
#
# These are LOW-to-medium evidence and never override a clear
# event location. They exist solely as a fallback.
# ============================================================

PERSON_HINTS = {
    "donald trump": "US",
    "trump": "US",
    "jd vance": "US",
    "joe biden": "US",
    "biden": "US",
    "zohran mamdani": "US",
    "mamdani": "US",

    "emmanuel macron": "FR",
    "macron": "FR",

    "keir starmer": "GB",
    "starmer": "GB",

    "vladimir putin": "RU",
    "putin": "RU",

    "volodymyr zelensky": "UA",
    "volodymyr zelenskyy": "UA",
    "zelensky": "UA",
    "zelenskyy": "UA",

    "narendra modi": "IN",
    "modi": "IN",

    "benjamin netanyahu": "IL",
    "netanyahu": "IL",

    "recep tayyip erdogan": "TR",
    "erdogan": "TR",
    "erdoğan": "TR",

    "ali khamenei": "IR",
    "khamenei": "IR",
    "masoud pezeshkian": "IR",
    "pezeshkian": "IR",

    "ahmed al-sharaa": "SY",
    "al-sharaa": "SY",

    "mohammed shia al-sudani": "IQ",
    "al-sudani": "IQ",

    "shehbaz sharif": "PK",
    "asim munir": "PK",

    "bola tinubu": "NG",
    "tinubu": "NG",

    "william ruto": "KE",
    "ruto": "KE",

    "nnamdi kanu": "NG",
    "taif sami": "IQ",

    "sirajuddin haqqani": "AF",
}


# ============================================================
# STATIC SOURCE COUNTRY HINTS
#
# Only local/regional sources should be used here.
# Global outlets are intentionally excluded.
# ============================================================

SOURCE_HINTS = {
    "punch newspapers": "NG",
    "the punch": "NG",
    "premium times nigeria": "NG",
    "daily trust": "NG",
    "thisday": "NG",
    "vanguard nigeria": "NG",
    "channels television": "NG",
    "zagazola": "NG",

    "the eastleigh voice": "KE",
    "nation africa": "KE",
    "the standard kenya": "KE",
    "capital news kenya": "KE",

    "afghanistan international": "AF",
    "tolonews": "AF",
    "khaama press": "AF",
    "amu tv": "AF",

    "dawn": "PK",
    "geo news": "PK",
    "the news international pakistan": "PK",
    "ary news": "PK",
    "tribune pakistan": "PK",

    "times of india": "IN",
    "hindustan times": "IN",
    "the hindu": "IN",
    "india today": "IN",
    "ndtv": "IN",
    "news18": "IN",

    "jerusalem post": "IL",
    "times of israel": "IL",
    "israel hayom": "IL",
    "ynet": "IL",

    "shafaq news": "IQ",
    "kurdistan24": "IQ",
    "rudaw": "IQ",
    "iraqi news": "IQ",

    "khaleej times": "AE",
    "gulf news": "AE",
    "the national uae": "AE",

    "arab news": "SA",
    "saudi gazette": "SA",

    "daily sabah": "TR",
    "hurriyet daily news": "TR",

    "ukrinform": "UA",
    "kyiv independent": "UA",
    "kyiv post": "UA",

    "tass": "RU",
    "interfax": "RU",

    "citynews": "CA",
    "cbc": "CA",
    "ctv news": "CA",
    "global news canada": "CA",
    "toronto star": "CA",
    "owen sound sun times": "CA",

    "wpde": "US",
    "abc7 eyewitness news": "US",
    "patch": "US",

    "daily maverick": "ZA",
    "news24": "ZA",

    "ghanaweb": "GH",
    "graphic online": "GH",

    "daily monitor uganda": "UG",
    "new vision uganda": "UG",

    "the reporter ethiopia": "ET",

    "somali guardian": "SO",
    "garowe online": "SO",
}


# ============================================================
# GLOBAL / MULTINATIONAL SOURCES
#
# Do not learn or infer event country from these.
# ============================================================

GLOBAL_SOURCES = {
    "reuters",
    "associated press",
    "ap news",
    "bbc",
    "bbc news",
    "cnn",
    "al jazeera",
    "france 24",
    "france24",
    "dw",
    "deutsche welle",
    "the guardian",
    "newsweek",
    "sky news",
    "euronews",
    "the independent",
    "new york times",
    "washington post",
    "bloomberg",
    "financial times",
}


# ============================================================
# COUNTRY TLD HINTS
# ============================================================

COUNTRY_TLDS = {
    ".af": "AF",
    ".au": "AU",
    ".at": "AT",
    ".be": "BE",
    ".bd": "BD",
    ".ca": "CA",
    ".ch": "CH",
    ".ci": "CI",
    ".cm": "CM",
    ".de": "DE",
    ".dz": "DZ",
    ".eg": "EG",
    ".et": "ET",
    ".fr": "FR",
    ".gh": "GH",
    ".in": "IN",
    ".id": "ID",
    ".il": "IL",
    ".iq": "IQ",
    ".ir": "IR",
    ".jo": "JO",
    ".ke": "KE",
    ".lb": "LB",
    ".lk": "LK",
    ".ly": "LY",
    ".ma": "MA",
    ".ml": "ML",
    ".mm": "MM",
    ".my": "MY",
    ".ne": "NE",
    ".ng": "NG",
    ".nl": "NL",
    ".nz": "NZ",
    ".ph": "PH",
    ".pk": "PK",
    ".pl": "PL",
    ".qa": "QA",
    ".ru": "RU",
    ".sa": "SA",
    ".sd": "SD",
    ".sn": "SN",
    ".so": "SO",
    ".sy": "SY",
    ".tj": "TJ",
    ".tn": "TN",
    ".tr": "TR",
    ".ua": "UA",
    ".ug": "UG",
    ".uk": "GB",
    ".uz": "UZ",
    ".ye": "YE",
    ".za": "ZA",
    ".zw": "ZW",
}


# ============================================================
# CITY SAFETY
# ============================================================

BLOCKED_CITY_TERMS = {
    "as",
    "be",
    "by",
    "do",
    "go",
    "he",
    "in",
    "is",
    "it",
    "me",
    "no",
    "of",
    "on",
    "or",
    "so",
    "to",
    "up",
    "us",

    "police",
    "security",
    "justice",
    "market",
    "church",
    "airport",
    "mission",
    "union",
    "college",
    "commerce",
    "enterprise",
    "liberty",
    "independence",
    "peace",
    "war",
    "hope",
    "center",
    "centre",
    "government",
    "state",
    "court",
    "capital",
    "army",
    "military",
    "intelligence",
    "embassy",
    "border",
    "camp",
    "base",
    "station",
    "office",
    "city",
    "news",
    "today",
    "daily",
    "times",
    "post",
    "press",
    "voice",
    "standard",
    "nation",
    "report",
    "review",
    "watch",
    "alert",
    "global",
    "international",
}


AMBIGUOUS_CITY_NAMES = {
    "reading",
    "mobile",
    "nice",
    "orange",
    "split",
    "bath",
    "sale",
    "most",
    "beer",
    "boom",
    "victoria",
    "normal",
    "union",
    "commerce",
}


SHORT_CITY_ALLOWLIST = {
    "gao",
    "lod",
}


# ============================================================
# EVENT LOCATION CONTEXT
# ============================================================

EVENT_TERMS = {
    "attack",
    "attacked",
    "attacks",
    "bomb",
    "bombing",
    "bombed",
    "explosion",
    "blast",
    "shooting",
    "shot",
    "stabbing",
    "stabbed",
    "killed",
    "killing",
    "murdered",
    "assassinated",
    "assassination",
    "raid",
    "raided",
    "arrest",
    "arrested",
    "arrests",
    "detained",
    "detention",
    "charged",
    "convicted",
    "sentenced",
    "trial",
    "court",
    "seized",
    "seizure",
    "plot",
    "plotting",
    "clash",
    "clashes",
    "kidnapped",
    "kidnapping",
    "hostage",
    "ied",
    "vbied",
    "suicide bomber",
    "suicide bombing",
    "sanctioned",
    "sanctions",
    "assets frozen",
    "assets seized",
    "designation",
    "watchlist",
    "terror watchlist",
    "prosecution",
    "investigation",
}


NEGATIVE_CONTEXT_PATTERNS = [
    r"\b[a-zA-Z]+-based\b",
    r"\bbased in\b",
    r"\bheadquartered in\b",
    r"\bheadquarters in\b",
    r"\boffice in\b",
    r"\bcorrespondent in\b",
    r"\breporter in\b",
    r"\bresearcher in\b",
    r"\banalyst in\b",
    r"\bspeaking in\b",
    r"\bmeeting in\b",
    r"\bconference in\b",
    r"\bsummit in\b",
]


# ============================================================
# NAMED ENTITY LEARNING FILTERS
# ============================================================

ENTITY_STOPWORDS = {
    "why",
    "how",
    "what",
    "when",
    "where",
    "who",
    "this",
    "that",
    "new",
    "latest",
    "breaking",
    "terror",
    "terrorist",
    "terrorism",
    "attack",
    "attacks",
    "arrest",
    "arrests",
    "police",
    "court",
    "trial",
    "news",
    "report",
    "reports",
    "government",
    "minister",
    "president",
    "prime minister",
    "army",
    "military",
    "official",
    "officials",
    "security",
    "forces",
    "state",
    "city",
    "country",
    "international",
}


# ============================================================
# BUILD INDEXES
# ============================================================

city_index = defaultdict(list)

for city in cities.values():
    name = city.get(
        "name",
        ""
    ).strip()

    if not name:
        continue

    key = name.lower()

    if key in BLOCKED_CITY_TERMS:
        continue

    if (
        len(key) <= 3
        and
        key not in SHORT_CITY_ALLOWLIST
    ):
        continue

    city_index[key].append(city)


for name in city_index:
    city_index[name].sort(
        key=lambda c:
            c.get(
                "population",
                0
            )
            or
            0,
        reverse=True,
    )


country_index = {}
country_code_index = {}

for country in countries.values():
    name = country.get(
        "name",
        ""
    ).strip()

    code = country.get(
        "iso"
    )

    if name:
        country_index[
            name.lower()
        ] = country

    if code:
        country_code_index[
            code
        ] = country


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        str(text)
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize(text):
    return (
        clean_text(text)
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
    )


def phrase_pattern(phrase):
    return (
        r"(?<!\w)"
        +
        re.escape(
            phrase.lower()
        )
        +
        r"(?!\w)"
    )


def contains_phrase(
    text,
    phrase
):
    return bool(
        re.search(
            phrase_pattern(
                phrase
            ),
            normalize(text)
        )
    )


def strip_source_name(
    text,
    source
):
    text = clean_text(text)
    source = clean_text(source)

    if not source:
        return text

    text = re.sub(
        re.escape(source),
        " ",
        text,
        flags=re.IGNORECASE
    )

    return clean_text(text)


def local_context(
    text,
    start,
    end,
    window=110
):
    n = normalize(text)

    return n[
        max(
            0,
            start - window
        )
        :
        min(
            len(n),
            end + window
        )
    ]


def has_event_context(text):
    return any(
        contains_phrase(
            text,
            term
        )
        for term in EVENT_TERMS
    )


def has_negative_context(text):
    n = normalize(text)

    return any(
        re.search(
            pattern,
            n
        )
        for pattern
        in NEGATIVE_CONTEXT_PATTERNS
    )


def explicit_location_relation(
    context,
    place
):
    p = re.escape(
        place.lower()
    )

    patterns = [
        rf"\b(?:in|near|at|outside|inside|around|across|from)\s+(?:the\s+)?{p}\b",
        rf"\b{p}\s+(?:attack|bombing|blast|shooting|arrest|raid|trial|court|police)\b",
        rf"\b(?:attack|bombing|blast|shooting|arrest|raid|trial|sentenced|detained|killed|wounded|seized)\b.{0,45}\b{p}\b",
    ]

    n = normalize(context)

    return any(
        re.search(
            pattern,
            n
        )
        for pattern in patterns
    )


def add_evidence(
    evidence,
    code,
    score,
    reason
):
    if not code:
        return

    if code not in country_code_index:
        return

    evidence[
        code
    ][
        "score"
    ] += score

    evidence[
        code
    ][
        "reasons"
    ].append(
        reason
    )


# ============================================================
# COUNTRY / CAPITAL HELPERS
# ============================================================

def country_by_code(code):
    return country_code_index.get(
        code
    )


def country_by_name(name):
    if not name:
        return None

    normalized_name = normalize(name)

    official = COUNTRY_ALIASES.get(
        normalized_name,
        name
    )

    return country_index.get(
        official.lower()
    )


def find_capital_city(
    country_code,
    capital_name
):
    if not capital_name:
        return None

    candidates = city_index.get(
        capital_name.lower(),
        []
    )

    same_country = [
        city
        for city in candidates
        if city.get(
            "countrycode"
        )
        ==
        country_code
    ]

    if same_country:
        return same_country[0]

    return (
        candidates[0]
        if candidates
        else None
    )


def find_named_city(
    city_name,
    country_code=None
):
    if not city_name:
        return None

    candidates = city_index.get(
        normalize(city_name),
        []
    )

    if not candidates:
        return None

    if country_code:
        same_country = [
            city
            for city in candidates
            if city.get(
                "countrycode"
            )
            ==
            country_code
        ]

        if same_country:
            return same_country[0]

    return candidates[0]


# ============================================================
# LOCATION SETTERS
# ============================================================

def clear_location(event):
    event["city"] = None
    event["region"] = None
    event["country"] = None
    event["country_code"] = None
    event["latitude"] = None
    event["longitude"] = None
    event["location_precision"] = "unknown"
    event["location_confidence"] = "low"
    event["location_score"] = 0
    event["location_method"] = "contextual_geolocation_v4"
    event["location_evidence"] = []


def set_city(
    event,
    city,
    confidence,
    score,
    method,
    reasons
):
    code = city.get(
        "countrycode"
    )

    country = country_by_code(
        code
    )

    event["city"] = city.get(
        "name"
    )

    event["region"] = None

    event["country"] = (
        country.get(
            "name"
        )
        if country
        else None
    )

    event["country_code"] = code

    event["latitude"] = float(
        city.get(
            "latitude"
        )
    )

    event["longitude"] = float(
        city.get(
            "longitude"
        )
    )

    event["location_precision"] = "city"
    event["location_confidence"] = confidence
    event["location_score"] = round(
        score,
        1
    )
    event["location_method"] = method
    event["location_evidence"] = reasons[:8]


def set_region(
    event,
    region_label,
    country_code,
    latitude,
    longitude,
    confidence,
    score,
    reasons
):
    country = country_by_code(
        country_code
    )

    event["city"] = None
    event["region"] = region_label

    event["country"] = (
        country.get(
            "name"
        )
        if country
        else None
    )

    event["country_code"] = country_code
    event["latitude"] = float(latitude)
    event["longitude"] = float(longitude)
    event["location_precision"] = "region"
    event["location_confidence"] = confidence
    event["location_score"] = round(
        score,
        1
    )
    event["location_method"] = "region_context"
    event["location_evidence"] = reasons[:8]


def set_country_capital(
    event,
    country_code,
    confidence,
    score,
    method,
    reasons
):
    country = country_by_code(
        country_code
    )

    if not country:
        return False

    capital = country.get(
        "capital"
    )

    city = find_capital_city(
        country_code,
        capital
    )

    if city is None:
        return False

    event["city"] = city.get(
        "name"
    )

    event["region"] = None

    event["country"] = country.get(
        "name"
    )

    event["country_code"] = country_code

    event["latitude"] = float(
        city.get(
            "latitude"
        )
    )

    event["longitude"] = float(
        city.get(
            "longitude"
        )
    )

    event["location_precision"] = "country_capital"
    event["location_confidence"] = confidence
    event["location_score"] = round(
        score,
        1
    )
    event["location_method"] = method
    event["location_evidence"] = reasons[:8]

    return True


def set_unlocated(event):
    event["city"] = None
    event["region"] = None
    event["country"] = None
    event["country_code"] = None
    event["latitude"] = 0.0
    event["longitude"] = 0.0
    event["location_precision"] = "unlocated"
    event["location_confidence"] = "low"
    event["location_score"] = 0
    event["location_method"] = "no_geographic_signal"
    event["location_evidence"] = []


# ============================================================
# EXPLICIT COUNTRY / DEMONYM EVIDENCE
# ============================================================

def collect_country_evidence(
    title,
    summary
):
    evidence = defaultdict(
        lambda: {
            "score": 0.0,
            "reasons": []
        }
    )

    for text, base, label in [
        (
            title,
            130,
            "title"
        ),
        (
            summary,
            45,
            "summary"
        ),
    ]:
        n = normalize(text)

        # Country aliases
        for alias, official in COUNTRY_ALIASES.items():
            country = country_by_name(
                official
            )

            if not country:
                continue

            for match in re.finditer(
                phrase_pattern(
                    alias
                ),
                n
            ):
                score = base

                if (
                    label == "title"
                    and
                    match.start() < 45
                ):
                    score += 25

                context = local_context(
                    text,
                    match.start(),
                    match.end()
                )

                if explicit_location_relation(
                    context,
                    alias
                ):
                    score += 70

                if has_event_context(
                    context
                ):
                    score += 20

                if has_negative_context(
                    context
                ):
                    score -= 50

                add_evidence(
                    evidence,
                    country.get(
                        "iso"
                    ),
                    score,
                    f"country:{alias}:{label}"
                )

        # Official country names
        for name, country in country_index.items():
            if len(name) < 4:
                continue

            for match in re.finditer(
                phrase_pattern(
                    name
                ),
                n
            ):
                score = base

                if (
                    label == "title"
                    and
                    match.start() < 45
                ):
                    score += 25

                context = local_context(
                    text,
                    match.start(),
                    match.end()
                )

                if explicit_location_relation(
                    context,
                    name
                ):
                    score += 70

                if has_event_context(
                    context
                ):
                    score += 20

                add_evidence(
                    evidence,
                    country.get(
                        "iso"
                    ),
                    score,
                    f"country:{name}:{label}"
                )

        # Demonyms
        for demonym, code in DEMONYMS.items():
            for match in re.finditer(
                phrase_pattern(
                    demonym
                ),
                n
            ):
                score = (
                    95
                    if label == "title"
                    else 30
                )

                if (
                    label == "title"
                    and
                    match.start() < 45
                ):
                    score += 25

                add_evidence(
                    evidence,
                    code,
                    score,
                    f"demonym:{demonym}:{label}"
                )

    return evidence


# ============================================================
# STATIC ENTITY / LANDMARK EVIDENCE
# ============================================================

def collect_static_entity_evidence(
    title,
    summary
):
    evidence = defaultdict(
        lambda: {
            "score": 0.0,
            "reasons": []
        }
    )

    landmark_city_candidates = []

    for text, label in [
        (
            title,
            "title"
        ),
        (
            summary,
            "summary"
        ),
    ]:
        n = normalize(text)

        # Landmarks / facilities
        for phrase, (
            code,
            city_name
        ) in LANDMARK_HINTS.items():
            if re.search(
                phrase_pattern(
                    phrase
                ),
                n
            ):
                score = (
                    150
                    if label == "title"
                    else 55
                )

                add_evidence(
                    evidence,
                    code,
                    score,
                    f"landmark:{phrase}:{label}"
                )

                if city_name:
                    landmark_city_candidates.append(
                        (
                            score,
                            code,
                            city_name,
                            phrase
                        )
                    )

        # Institutions
        for phrase, code in ENTITY_HINTS.items():
            if re.search(
                phrase_pattern(
                    phrase
                ),
                n
            ):
                add_evidence(
                    evidence,
                    code,
                    (
                        85
                        if label == "title"
                        else 30
                    ),
                    f"institution:{phrase}:{label}"
                )

        # Organisations
        for phrase, code in ORG_HINTS.items():
            if re.search(
                phrase_pattern(
                    phrase
                ),
                n
            ):
                add_evidence(
                    evidence,
                    code,
                    (
                        70
                        if label == "title"
                        else 25
                    ),
                    f"organisation:{phrase}:{label}"
                )

        # Personalities
        for phrase, code in PERSON_HINTS.items():
            if re.search(
                phrase_pattern(
                    phrase
                ),
                n
            ):
                add_evidence(
                    evidence,
                    code,
                    (
                        75
                        if label == "title"
                        else 25
                    ),
                    f"person:{phrase}:{label}"
                )

    return evidence, landmark_city_candidates


# ============================================================
# REGION DETECTION
# ============================================================

def best_region(
    title,
    summary,
    preferred_country_code=None
):
    candidates = []

    for region_phrase, (
        label,
        code,
        lat,
        lon
    ) in REGIONS.items():
        score = 0
        reasons = []

        for text, base, source_label in [
            (
                title,
                150,
                "title"
            ),
            (
                summary,
                45,
                "summary"
            ),
        ]:
            n = normalize(text)

            match = re.search(
                phrase_pattern(
                    region_phrase
                ),
                n
            )

            if not match:
                continue

            local_score = base

            context = local_context(
                text,
                match.start(),
                match.end()
            )

            if explicit_location_relation(
                context,
                region_phrase
            ):
                local_score += 85

            if has_event_context(
                context
            ):
                local_score += 25

            if (
                preferred_country_code
                and
                code
                and
                code == preferred_country_code
            ):
                local_score += 40

            score += local_score

            reasons.append(
                f"region:{region_phrase}:{source_label}"
            )

        if score > 0:
            candidates.append(
                {
                    "score": score,
                    "label": label,
                    "code": code,
                    "lat": lat,
                    "lon": lon,
                    "reasons": reasons,
                }
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item:
            item[
                "score"
            ],
        reverse=True
    )

    return candidates[0]


# ============================================================
# CITY DETECTION
# ============================================================

def city_mentions(text):
    n = normalize(text)

    words = re.findall(
        r"[a-zA-ZÀ-ÿ0-9'\-]+",
        n
    )

    phrases = set()

    for size in (
        4,
        3,
        2,
        1
    ):
        for index in range(
            0,
            len(words)
            -
            size
            +
            1
        ):
            phrase = " ".join(
                words[
                    index:
                    index + size
                ]
            )

            if phrase in BLOCKED_CITY_TERMS:
                continue

            if (
                len(phrase) <= 3
                and
                phrase not in SHORT_CITY_ALLOWLIST
            ):
                continue

            if phrase in city_index:
                phrases.add(
                    phrase
                )

    results = []

    for phrase in phrases:
        for match in re.finditer(
            phrase_pattern(
                phrase
            ),
            n
        ):
            for city in city_index[
                phrase
            ]:
                results.append(
                    {
                        "city": city,
                        "matched": phrase,
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

    return results


def score_city_mention(
    mention,
    text,
    base,
    preferred_country_code=None
):
    city = mention[
        "city"
    ]

    matched = mention[
        "matched"
    ]

    population = (
        city.get(
            "population",
            0
        )
        or
        0
    )

    score = base

    if population > 0:
        score += min(
            16,
            math.log10(
                population + 1
            )
            *
            2.5
        )

    if mention[
        "start"
    ] < 45:
        score += 20

    context = local_context(
        text,
        mention[
            "start"
        ],
        mention[
            "end"
        ]
    )

    if explicit_location_relation(
        context,
        matched
    ):
        score += 110

    if has_event_context(
        context
    ):
        score += 35

    if has_negative_context(
        context
    ):
        score -= 100

    if matched in AMBIGUOUS_CITY_NAMES:
        score -= 90

    if preferred_country_code:
        if (
            city.get(
                "countrycode"
            )
            ==
            preferred_country_code
        ):
            score += 80
        else:
            score -= 110

    return score


def best_city(
    title,
    summary,
    preferred_country_code=None
):
    candidates = defaultdict(
        lambda: {
            "score": 0.0,
            "city": None,
            "reasons": []
        }
    )

    for text, base, label in [
        (
            title,
            120,
            "title"
        ),
        (
            summary,
            32,
            "summary"
        ),
    ]:
        for mention in city_mentions(
            text
        ):
            city = mention[
                "city"
            ]

            key = (
                city.get(
                    "name"
                ),
                city.get(
                    "countrycode"
                ),
                city.get(
                    "latitude"
                ),
                city.get(
                    "longitude"
                )
            )

            score = score_city_mention(
                mention,
                text,
                base,
                preferred_country_code
            )

            candidates[
                key
            ][
                "score"
            ] += score

            candidates[
                key
            ][
                "city"
            ] = city

            candidates[
                key
            ][
                "reasons"
            ].append(
                f"city:{mention['matched']}:{label}"
            )

    if not candidates:
        return None

    ranked = sorted(
        candidates.values(),
        key=lambda item:
            item[
                "score"
            ],
        reverse=True
    )

    best = ranked[0]

    best[
        "second_score"
    ] = (
        ranked[1][
            "score"
        ]
        if len(
            ranked
        ) > 1
        else None
    )

    return best


# ============================================================
# SOURCE HINTS
# ============================================================

def is_global_source(source):
    s = normalize(source)

    return any(
        global_name
        in
        s
        for global_name
        in GLOBAL_SOURCES
    )


def static_source_country(source):
    s = normalize(source)

    if not s:
        return None

    for source_hint, code in SOURCE_HINTS.items():
        if source_hint in s:
            return (
                code,
                f"source_static:{source_hint}"
            )

    # Country words in source names, e.g. Afghanistan International
    evidence = collect_country_evidence(
        source,
        ""
    )

    ranked = rank_country_evidence(
        evidence
    )

    if ranked:
        code, score, reasons = ranked[0]

        if score >= 90:
            return (
                code,
                "source_country_name"
            )

    # ccTLD if source is rendered as a domain
    for tld, code in COUNTRY_TLDS.items():
        if (
            tld in s
            and
            re.search(
                re.escape(
                    tld
                )
                +
                r"(?:\b|/|$)",
                s
            )
        ):
            return (
                code,
                f"source_tld:{tld}"
            )

    return None


# ============================================================
# ENTITY EXTRACTION FOR SELF-LEARNING
# ============================================================

def extract_title_entities(title):
    original = clean_text(title)

    # Sequences such as Donald Trump, Nnamdi Kanu, Taif Sami,
    # National Investigation Agency, IDF, FBI, etc.
    candidates = re.findall(
        r"\b(?:[A-Z][A-Za-zÀ-ÿ'\-]{2,}|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-zÀ-ÿ'\-]{2,}|[A-Z]{2,})){0,3}\b",
        original
    )

    cleaned = set()

    for candidate in candidates:
        entity = clean_text(
            candidate
        )

        lower = normalize(
            entity
        )

        if lower in ENTITY_STOPWORDS:
            continue

        words = lower.split()

        if not words:
            continue

        if all(
            word in ENTITY_STOPWORDS
            for word in words
        ):
            continue

        # Single capitalized word is too risky unless it is an acronym.
        if (
            len(words) == 1
            and
            not entity.isupper()
        ):
            continue

        if len(lower) < 4:
            continue

        cleaned.add(
            lower
        )

    return cleaned


# ============================================================
# COUNTRY EVIDENCE RANKING
# ============================================================

def merge_country_evidence(
    *evidence_sets
):
    merged = defaultdict(
        lambda: {
            "score": 0.0,
            "reasons": []
        }
    )

    for evidence in evidence_sets:
        for code, payload in evidence.items():
            merged[
                code
            ][
                "score"
            ] += payload[
                "score"
            ]

            merged[
                code
            ][
                "reasons"
            ].extend(
                payload[
                    "reasons"
                ]
            )

    return merged


def rank_country_evidence(
    evidence
):
    ranked = []

    for code, payload in evidence.items():
        ranked.append(
            (
                code,
                payload[
                    "score"
                ],
                payload[
                    "reasons"
                ]
            )
        )

    ranked.sort(
        key=lambda item:
            item[1],
        reverse=True
    )

    return ranked


def choose_country(
    evidence,
    minimum_score=70,
    minimum_gap=25
):
    ranked = rank_country_evidence(
        evidence
    )

    if not ranked:
        return None

    best_code, best_score, reasons = ranked[
        0
    ]

    second_score = (
        ranked[1][1]
        if len(ranked) > 1
        else None
    )

    if best_score < minimum_score:
        return None

    if (
        second_score is not None
        and
        best_score
        -
        second_score
        <
        minimum_gap
    ):
        return None

    return {
        "code": best_code,
        "score": best_score,
        "reasons": reasons,
        "second_score": second_score,
    }


# ============================================================
# FIRST PASS
# ============================================================

def intrinsic_analysis(event):
    source = event.get(
        "source",
        ""
    )

    # Remove source branding from title/summary before location parsing.
    title = strip_source_name(
        event.get(
            "title",
            ""
        ),
        source
    )

    summary = strip_source_name(
        event.get(
            "summary",
            ""
        ),
        source
    )

    explicit = collect_country_evidence(
        title,
        summary
    )

    static_entities, landmark_cities = (
        collect_static_entity_evidence(
            title,
            summary
        )
    )

    combined = merge_country_evidence(
        explicit,
        static_entities
    )

    provisional_country = choose_country(
        combined,
        minimum_score=70,
        minimum_gap=20
    )

    preferred_code = (
        provisional_country[
            "code"
        ]
        if provisional_country
        else None
    )

    # Landmark city is very strong.
    if landmark_cities:
        landmark_cities.sort(
            key=lambda item:
                item[0],
            reverse=True
        )

        score, code, city_name, phrase = (
            landmark_cities[0]
        )

        city = find_named_city(
            city_name,
            code
        )

        if city:
            return {
                "type": "city",
                "city": city,
                "confidence": "high",
                "score": score + 70,
                "method": "landmark_city",
                "reasons": [
                    f"landmark:{phrase}"
                ],
                "title": title,
                "summary": summary,
                "country_evidence": combined,
            }

    city_result = best_city(
        title,
        summary,
        preferred_code
    )

    if city_result:
        score = city_result[
            "score"
        ]

        second_score = city_result.get(
            "second_score"
        )

        ambiguous = (
            second_score is not None
            and
            score
            -
            second_score
            <
            35
        )

        if (
            score >= 205
            and
            not ambiguous
        ):
            return {
                "type": "city",
                "city": city_result[
                    "city"
                ],
                "confidence": "high",
                "score": score,
                "method": "explicit_context_city",
                "reasons": city_result[
                    "reasons"
                ],
                "title": title,
                "summary": summary,
                "country_evidence": combined,
            }

        if (
            score >= 165
            and
            not ambiguous
        ):
            return {
                "type": "city",
                "city": city_result[
                    "city"
                ],
                "confidence": "medium",
                "score": score,
                "method": "context_city",
                "reasons": city_result[
                    "reasons"
                ],
                "title": title,
                "summary": summary,
                "country_evidence": combined,
            }

    region_result = best_region(
        title,
        summary,
        preferred_code
    )

    if (
        region_result
        and
        region_result[
            "score"
        ] >= 125
        and
        (
            region_result[
                "code"
            ]
            or
            preferred_code
        )
    ):
        # For ambiguous cross-border regions such as generic "Kashmir",
        # use another independent signal (country/person/source in pass 2)
        # before assigning the event to a country.
        if (
            region_result[
                "code"
            ] is None
            and
            preferred_code
        ):
            region_result = dict(
                region_result
            )
            region_result[
                "code"
            ] = preferred_code

        return {
            "type": "region",
            "region": region_result,
            "confidence": (
                "high"
                if region_result[
                    "score"
                ] >= 220
                else
                "medium"
            ),
            "score": region_result[
                "score"
            ],
            "method": "region_context",
            "reasons": region_result[
                "reasons"
            ],
            "title": title,
            "summary": summary,
            "country_evidence": combined,
        }

    country_result = choose_country(
        combined,
        minimum_score=90,
        minimum_gap=30
    )

    if country_result:
        return {
            "type": "country",
            "country": country_result,
            "confidence": (
                "high"
                if country_result[
                    "score"
                ] >= 180
                else
                "medium"
            ),
            "score": country_result[
                "score"
            ],
            "method": "intrinsic_country",
            "reasons": country_result[
                "reasons"
            ],
            "title": title,
            "summary": summary,
            "country_evidence": combined,
        }

    return {
        "type": "unresolved",
        "title": title,
        "summary": summary,
        "country_evidence": combined,
    }


def apply_intrinsic_result(
    event,
    result
):
    if result[
        "type"
    ] == "city":
        set_city(
            event,
            result[
                "city"
            ],
            result[
                "confidence"
            ],
            result[
                "score"
            ],
            result[
                "method"
            ],
            result[
                "reasons"
            ]
        )

        return True

    if result[
        "type"
    ] == "region":
        region = result[
            "region"
        ]

        set_region(
            event,
            region[
                "label"
            ],
            region[
                "code"
            ],
            region[
                "lat"
            ],
            region[
                "lon"
            ],
            result[
                "confidence"
            ],
            result[
                "score"
            ],
            result[
                "reasons"
            ]
        )

        return True

    if result[
        "type"
    ] == "country":
        country = result[
            "country"
        ]

        return set_country_capital(
            event,
            country[
                "code"
            ],
            result[
                "confidence"
            ],
            result[
                "score"
            ],
            "intrinsic_country_capital",
            result[
                "reasons"
            ]
        )

    return False


# ============================================================
# LEARN SOURCE -> COUNTRY
# ============================================================

def learn_source_countries(
    events
):
    counts = defaultdict(
        Counter
    )

    for event in events:
        source = clean_text(
            event.get(
                "source",
                ""
            )
        )

        code = event.get(
            "country_code"
        )

        precision = event.get(
            "location_precision"
        )

        confidence = event.get(
            "location_confidence"
        )

        if not source or not code:
            continue

        if precision not in {
            "city",
            "region",
            "country_capital",
        }:
            continue

        if confidence not in {
            "high",
            "medium",
        }:
            continue

        if is_global_source(
            source
        ):
            continue

        counts[
            normalize(source)
        ][
            code
        ] += 1

    model = {}

    for source, country_counts in counts.items():
        total = sum(
            country_counts.values()
        )

        code, best_count = (
            country_counts.most_common(
                1
            )[0]
        )

        dominance = (
            best_count
            /
            total
        )

        if (
            best_count >= 3
            and
            dominance >= 0.80
        ):
            model[
                source
            ] = {
                "code": code,
                "support": best_count,
                "dominance": dominance,
            }

    return model


# ============================================================
# LEARN NAMED ENTITY -> COUNTRY
# ============================================================

def learn_entity_countries(
    events
):
    counts = defaultdict(
        Counter
    )

    for event in events:
        code = event.get(
            "country_code"
        )

        confidence = event.get(
            "location_confidence"
        )

        precision = event.get(
            "location_precision"
        )

        if not code:
            continue

        if confidence not in {
            "high",
            "medium",
        }:
            continue

        if precision not in {
            "city",
            "region",
            "country_capital",
        }:
            continue

        for entity in extract_title_entities(
            event.get(
                "title",
                ""
            )
        ):
            counts[
                entity
            ][
                code
            ] += 1

    model = {}

    for entity, country_counts in counts.items():
        total = sum(
            country_counts.values()
        )

        code, best_count = (
            country_counts.most_common(
                1
            )[0]
        )

        dominance = (
            best_count
            /
            total
        )

        if (
            best_count >= 2
            and
            dominance >= 0.85
        ):
            model[
                entity
            ] = {
                "code": code,
                "support": best_count,
                "dominance": dominance,
            }

    return model


# ============================================================
# LEARNED FALLBACK EVIDENCE
# ============================================================

def collect_learned_evidence(
    event,
    source_model,
    entity_model
):
    evidence = defaultdict(
        lambda: {
            "score": 0.0,
            "reasons": []
        }
    )

    title = clean_text(
        event.get(
            "title",
            ""
        )
    )

    source = clean_text(
        event.get(
            "source",
            ""
        )
    )

    # Learned entities
    for entity in extract_title_entities(
        title
    ):
        learned = entity_model.get(
            entity
        )

        if learned:
            add_evidence(
                evidence,
                learned[
                    "code"
                ],
                70,
                (
                    f"learned_entity:{entity}:"
                    f"{learned['support']}"
                )
            )

    # Static local source
    static_source = static_source_country(
        source
    )

    if (
        static_source
        and
        not is_global_source(
            source
        )
    ):
        code, reason = (
            static_source
        )

        add_evidence(
            evidence,
            code,
            60,
            reason
        )

    # Learned source model
    learned_source = source_model.get(
        normalize(source)
    )

    if (
        learned_source
        and
        not is_global_source(
            source
        )
    ):
        add_evidence(
            evidence,
            learned_source[
                "code"
            ],
            55,
            (
                "learned_source:"
                +
                normalize(source)
                +
                ":"
                +
                str(
                    learned_source[
                        "support"
                    ]
                )
            )
        )

    return evidence


# ============================================================
# SECOND PASS
# ============================================================

def second_pass_geolocate(
    event,
    first_result,
    source_model,
    entity_model
):
    title = first_result[
        "title"
    ]

    summary = first_result[
        "summary"
    ]

    intrinsic_evidence = first_result[
        "country_evidence"
    ]

    learned_evidence = collect_learned_evidence(
        event,
        source_model,
        entity_model
    )

    combined = merge_country_evidence(
        intrinsic_evidence,
        learned_evidence
    )

    country_result = choose_country(
        combined,
        minimum_score=50,
        minimum_gap=15
    )

    preferred_code = (
        country_result[
            "code"
        ]
        if country_result
        else None
    )

    # A weak city mention can become reliable once source/entity
    # evidence identifies the country.
    city_result = best_city(
        title,
        summary,
        preferred_code
    )

    if city_result:
        score = city_result[
            "score"
        ]

        second_score = city_result.get(
            "second_score"
        )

        ambiguous = (
            second_score is not None
            and
            score
            -
            second_score
            <
            30
        )

        if (
            score >= 175
            and
            not ambiguous
        ):
            set_city(
                event,
                city_result[
                    "city"
                ],
                "medium",
                score,
                "country_assisted_city",
                (
                    city_result[
                        "reasons"
                    ]
                    +
                    (
                        country_result[
                            "reasons"
                        ]
                        if country_result
                        else []
                    )
                )
            )

            return True

    region_result = best_region(
        title,
        summary,
        preferred_code
    )

    if (
        region_result
        and
        region_result[
            "score"
        ] >= 100
    ):
        # If Kashmir is generic but another signal identifies India/Pakistan,
        # attach the region to the inferred country while keeping regional coords.
        region_code = region_result[
            "code"
        ]

        if (
            region_code is None
            and
            preferred_code
        ):
            region_code = preferred_code

        set_region(
            event,
            region_result[
                "label"
            ],
            region_code,
            region_result[
                "lat"
            ],
            region_result[
                "lon"
            ],
            "medium",
            region_result[
                "score"
            ],
            (
                region_result[
                    "reasons"
                ]
                +
                (
                    country_result[
                        "reasons"
                    ]
                    if country_result
                    else []
                )
            )
        )

        return True

    if country_result:
        return set_country_capital(
            event,
            country_result[
                "code"
            ],
            "low",
            country_result[
                "score"
            ],
            "inferred_country_capital",
            country_result[
                "reasons"
            ]
        )

    return False


# ============================================================
# MAIN TWO-PASS PIPELINE
# ============================================================

def main():
    print()
    print("=" * 72)
    print("INTERPOL CT Intelligence Map")
    print("CONTEXTUAL GEOLOCATION V4 — TWO-PASS ENTITY INFERENCE")
    print("=" * 72)

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        data = json.load(
            file
        )

    events = data.get(
        "events",
        []
    )

    print(
        f"Events loaded: {len(events)}"
    )

    first_results = []

    # --------------------------------------------------------
    # PASS 1
    # --------------------------------------------------------

    print()
    print("PASS 1 — explicit/contextual geolocation")

    for number, event in enumerate(
        events,
        start=1
    ):
        clear_location(
            event
        )

        result = intrinsic_analysis(
            event
        )

        first_results.append(
            result
        )

        apply_intrinsic_result(
            event,
            result
        )

        if number % 100 == 0:
            print(
                f"Processed "
                f"{number}/{len(events)}"
            )

    # --------------------------------------------------------
    # LEARN FROM HIGH/MEDIUM CONFIDENCE EVENTS
    # --------------------------------------------------------

    print()
    print(
        "Learning recurring source and entity geography..."
    )

    source_model = learn_source_countries(
        events
    )

    entity_model = learn_entity_countries(
        events
    )

    print(
        f"Learned local sources: "
        f"{len(source_model)}"
    )

    print(
        f"Learned named entities: "
        f"{len(entity_model)}"
    )

    # --------------------------------------------------------
    # PASS 2
    # --------------------------------------------------------

    print()
    print(
        "PASS 2 — learned source/entity inference"
    )

    recovered = 0

    for index, event in enumerate(
        events
    ):
        if event.get(
            "location_precision"
        ) in {
            "city",
            "region",
            "country_capital",
        }:
            continue

        if second_pass_geolocate(
            event,
            first_results[
                index
            ],
            source_model,
            entity_model
        ):
            recovered += 1

    print(
        f"Recovered on pass 2: "
        f"{recovered}"
    )

    # --------------------------------------------------------
    # FINAL PLACEHOLDER
    # --------------------------------------------------------

    for event in events:
        if event.get(
            "latitude"
        ) is None:
            set_unlocated(
                event
            )

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    precision_counts = Counter(
        event.get(
            "location_precision",
            "unknown"
        )
        for event in events
    )

    method_counts = Counter(
        event.get(
            "location_method",
            "unknown"
        )
        for event in events
    )

    confidence_counts = Counter(
        event.get(
            "location_confidence",
            "low"
        )
        for event in events
    )

    country_counts = Counter(
        event.get(
            "country"
        )
        for event in events
        if event.get(
            "country"
        )
    )

    data[
        "geolocation"
    ] = {
        "method":
            "Contextual GeoNames + entity/source inference V4",
        "strategy":
            "Two-pass multi-signal country inference",
        "city":
            precision_counts[
                "city"
            ],
        "region":
            precision_counts[
                "region"
            ],
        "country_capital":
            precision_counts[
                "country_capital"
            ],
        "unlocated":
            precision_counts[
                "unlocated"
            ],
        "mapped_total":
            (
                len(events)
                -
                precision_counts[
                    "unlocated"
                ]
            ),
        "high_confidence":
            confidence_counts[
                "high"
            ],
        "medium_confidence":
            confidence_counts[
                "medium"
            ],
        "low_confidence":
            confidence_counts[
                "low"
            ],
        "learned_sources":
            len(
                source_model
            ),
        "learned_entities":
            len(
                entity_model
            ),
        "pass2_recovered":
            recovered,
        "methods":
            dict(
                method_counts
            ),
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 72)
    print("GEOLOCATION COMPLETE")
    print("=" * 72)

    print(
        f"City:              "
        f"{precision_counts['city']}"
    )

    print(
        f"Region:            "
        f"{precision_counts['region']}"
    )

    print(
        f"Country → capital: "
        f"{precision_counts['country_capital']}"
    )

    print(
        f"Unlocated:         "
        f"{precision_counts['unlocated']}"
    )

    print(
        f"Mapped total:      "
        f"{len(events) - precision_counts['unlocated']}"
        f"/{len(events)}"
    )

    print()
    print(
        f"High confidence:   "
        f"{confidence_counts['high']}"
    )

    print(
        f"Medium confidence: "
        f"{confidence_counts['medium']}"
    )

    print(
        f"Low confidence:    "
        f"{confidence_counts['low']}"
    )

    print()
    print(
        f"Learned sources:   "
        f"{len(source_model)}"
    )

    print(
        f"Learned entities:  "
        f"{len(entity_model)}"
    )

    print(
        f"Pass-2 recovered:  "
        f"{recovered}"
    )

    print()
    print("Top mapped countries:")

    for country, count in country_counts.most_common(
        10
    ):
        print(
            f"  {country}: {count}"
        )

    print("=" * 72)


if __name__ == "__main__":
    main()
