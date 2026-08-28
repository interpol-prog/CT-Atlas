import json
import math
import re
from collections import defaultdict

import geonamescache


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# CONTEXTUAL GEOLOCATION V3
#
# Strategy:
# 1) Explicit city/place tied to event wording
# 2) Explicit region tied to event wording
# 3) Explicit country tied to event wording
# 4) CT-organisation geographic prior as fallback only
# 5) Country -> capital fallback
#
# Never use the news outlet/source as the event location.
# ============================================================

INPUT_FILE = "events.json"
OUTPUT_FILE = "events.json"

gc = geonamescache.GeonamesCache(min_city_population=5000)
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
}


# ============================================================
# REGIONAL GAZETTEER
#
# Representative coordinates are for regional placement only.
# They must not be interpreted as exact incident coordinates.
# ============================================================

REGIONS = {
    "kashmir": {
        "label": "Kashmir",
        "country": "India",
        "country_code": "IN",
        "lat": 34.0837,
        "lon": 74.7973,
    },
    "jammu and kashmir": {
        "label": "Jammu and Kashmir",
        "country": "India",
        "country_code": "IN",
        "lat": 34.0837,
        "lon": 74.7973,
    },
    "gaza": {
        "label": "Gaza Strip",
        "country": "Palestinian Territory",
        "country_code": "PS",
        "lat": 31.5017,
        "lon": 34.4668,
    },
    "gaza strip": {
        "label": "Gaza Strip",
        "country": "Palestinian Territory",
        "country_code": "PS",
        "lat": 31.5017,
        "lon": 34.4668,
    },
    "west bank": {
        "label": "West Bank",
        "country": "Palestinian Territory",
        "country_code": "PS",
        "lat": 31.9466,
        "lon": 35.3027,
    },
    "sinai": {
        "label": "Sinai",
        "country": "Egypt",
        "country_code": "EG",
        "lat": 29.5000,
        "lon": 33.8000,
    },
    "sahel": {
        "label": "Sahel",
        "country": None,
        "country_code": None,
        "lat": 15.5000,
        "lon": 2.0000,
    },
    "donbas": {
        "label": "Donbas",
        "country": "Ukraine",
        "country_code": "UA",
        "lat": 48.0000,
        "lon": 37.8000,
    },
    "donbass": {
        "label": "Donbas",
        "country": "Ukraine",
        "country_code": "UA",
        "lat": 48.0000,
        "lon": 37.8000,
    },
    "north waziristan": {
        "label": "North Waziristan",
        "country": "Pakistan",
        "country_code": "PK",
        "lat": 32.9500,
        "lon": 69.9000,
    },
    "south waziristan": {
        "label": "South Waziristan",
        "country": "Pakistan",
        "country_code": "PK",
        "lat": 32.3000,
        "lon": 69.9000,
    },
    "balochistan": {
        "label": "Balochistan",
        "country": "Pakistan",
        "country_code": "PK",
        "lat": 28.5000,
        "lon": 65.0000,
    },
    "baluchistan": {
        "label": "Balochistan",
        "country": "Pakistan",
        "country_code": "PK",
        "lat": 28.5000,
        "lon": 65.0000,
    },
}


# ============================================================
# CT ORGANISATION / ACTOR PRIORS
#
# Used ONLY when no explicit usable place is found.
# ============================================================

ORG_PRIORS = {
    "taliban": ("Afghanistan", "AF"),
    "isis-k": ("Afghanistan", "AF"),
    "isis k": ("Afghanistan", "AF"),
    "islamic state khorasan": ("Afghanistan", "AF"),
    "ttp": ("Pakistan", "PK"),
    "tehrik-i-taliban pakistan": ("Pakistan", "PK"),
    "tehreek-e-taliban pakistan": ("Pakistan", "PK"),
    "al-shabaab": ("Somalia", "SO"),
    "al shabaab": ("Somalia", "SO"),
    "boko haram": ("Nigeria", "NG"),
    "iswap": ("Nigeria", "NG"),
    "idf": ("Israel", "IL"),
    "israel defense forces": ("Israel", "IL"),
    "israel defence forces": ("Israel", "IL"),
    "hamas": ("Palestinian Territory", "PS"),
    "palestinian islamic jihad": ("Palestinian Territory", "PS"),
    "hezbollah": ("Lebanon", "LB"),
    "hizballah": ("Lebanon", "LB"),
    "hizbollah": ("Lebanon", "LB"),
}


# ============================================================
# TERMS THAT MUST NEVER BE TREATED AS CITY NAMES
# ============================================================

BLOCKED_CITY_TERMS = {
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
}


# ============================================================
# EVENT CONTEXT
# ============================================================

EVENT_TERMS = {
    "attack",
    "attacked",
    "bombing",
    "bombed",
    "explosion",
    "blast",
    "shooting",
    "shot",
    "stabbing",
    "killed",
    "murdered",
    "assassinated",
    "raid",
    "raided",
    "arrest",
    "arrested",
    "detained",
    "charged",
    "convicted",
    "sentenced",
    "trial",
    "seized",
    "plot",
    "clash",
    "kidnapped",
    "kidnapping",
    "hostage",
    "ied",
    "vbied",
    "suicide bombing",
    "suicide bomber",
    "terrorist attack",
    "terror attack",
    "sanctions",
    "assets frozen",
    "assets seized",
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
    r"\bembassy in\b",
]


# ============================================================
# CITY INDEX
# ============================================================

city_index = defaultdict(list)

for city in cities.values():
    name = city.get("name", "").strip()
    if not name:
        continue

    key = name.lower()

    if key in BLOCKED_CITY_TERMS:
        continue

    city_index[key].append(city)

for name in city_index:
    city_index[name].sort(
        key=lambda c: c.get("population", 0) or 0,
        reverse=True,
    )


country_index = {}

for country in countries.values():
    name = country.get("name", "").strip()
    if name:
        country_index[name.lower()] = country


# ============================================================
# HELPERS
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize(text):
    return (
        clean_text(text)
        .lower()
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
    )


def phrase_pattern(phrase):
    return r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"


def contains_phrase(text, phrase):
    return bool(re.search(phrase_pattern(phrase), normalize(text)))


def strip_source_name(text, source):
    """
    Source/outlet names are not event locations.
    Remove the source name from text before geolocation scoring.
    """
    text = clean_text(text)
    source = clean_text(source)

    if not source:
        return text

    return re.sub(
        re.escape(source),
        " ",
        text,
        flags=re.IGNORECASE,
    )


def has_event_context(text):
    n = normalize(text)

    return any(
        contains_phrase(n, term)
        for term in EVENT_TERMS
    )


def has_negative_context(text):
    n = normalize(text)

    return any(
        re.search(pattern, n)
        for pattern in NEGATIVE_CONTEXT_PATTERNS
    )


def local_context(text, start, end, window=100):
    n = normalize(text)

    return n[
        max(0, start - window):
        min(len(n), end + window)
    ]


def explicit_location_relation(context, place):
    """
    Stronger than merely mentioning a place.
    Examples:
      attack in Kabul
      arrested near Srinagar
      bombing outside Mogadishu
    """
    place = re.escape(place.lower())

    patterns = [
        rf"\b(?:in|near|at|outside|inside|around|across)\s+(?:the\s+)?{place}\b",
        rf"\b{place}\s+(?:attack|bombing|blast|shooting|arrest|raid|court|trial)\b",
        rf"\b(?:attack|bombing|blast|shooting|arrest|raid|trial|sentenced|detained)\b.{0,35}\b{place}\b",
    ]

    return any(
        re.search(pattern, normalize(context))
        for pattern in patterns
    )


# ============================================================
# COUNTRY / CAPITAL HELPERS
# ============================================================

def country_by_name(name):
    if not name:
        return None

    official = COUNTRY_ALIASES.get(
        normalize(name),
        name,
    )

    return country_index.get(
        official.lower()
    )


def country_by_code(code):
    if not code:
        return None

    return countries.get(code)


def find_capital_city(country_code, capital_name):
    if not capital_name:
        return None

    candidates = city_index.get(
        capital_name.lower(),
        []
    )

    same_country = [
        city
        for city in candidates
        if city.get("countrycode") == country_code
    ]

    if same_country:
        return same_country[0]

    return candidates[0] if candidates else None


def set_country_capital(event, country, method, confidence="medium"):
    if not country:
        return False

    code = country.get("iso")
    capital = country.get("capital")

    city = find_capital_city(
        code,
        capital,
    )

    if city is None:
        return False

    event["city"] = city.get("name")
    event["country"] = country.get("name")
    event["country_code"] = code
    event["latitude"] = float(city.get("latitude"))
    event["longitude"] = float(city.get("longitude"))
    event["location_precision"] = "country_capital"
    event["location_confidence"] = confidence
    event["location_method"] = method

    return True


# ============================================================
# REGION DETECTION
# ============================================================

def find_region(title, summary):
    scored = []

    for region_name, region in REGIONS.items():
        title_match = re.search(
            phrase_pattern(region_name),
            normalize(title),
        )

        summary_match = re.search(
            phrase_pattern(region_name),
            normalize(summary),
        )

        score = 0

        if title_match:
            score += 150

            context = local_context(
                title,
                title_match.start(),
                title_match.end(),
            )

            if explicit_location_relation(
                context,
                region_name,
            ):
                score += 100

            if has_event_context(context):
                score += 40

        if summary_match:
            score += 45

            context = local_context(
                summary,
                summary_match.start(),
                summary_match.end(),
            )

            if explicit_location_relation(
                context,
                region_name,
            ):
                score += 50

        if score:
            scored.append(
                (score, region)
            )

    if not scored:
        return None

    scored.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    return scored[0]


# ============================================================
# COUNTRY DETECTION
# ============================================================

def country_mentions(text):
    n = normalize(text)
    results = []

    # Aliases
    for alias, official in COUNTRY_ALIASES.items():
        for match in re.finditer(
            phrase_pattern(alias),
            n,
        ):
            country = country_index.get(
                official.lower()
            )

            if country:
                results.append(
                    (match.start(), match.end(), alias, country)
                )

    # Official names
    for name, country in country_index.items():
        if len(name) < 4:
            continue

        for match in re.finditer(
            phrase_pattern(name),
            n,
        ):
            results.append(
                (match.start(), match.end(), name, country)
            )

    return results


def best_country(title, summary):
    scores = defaultdict(float)
    objects = {}

    for text, base in [
        (title, 100),
        (summary, 30),
    ]:
        for start, end, matched, country in country_mentions(text):
            code = country.get("iso")
            score = base

            context = local_context(
                text,
                start,
                end,
            )

            if explicit_location_relation(
                context,
                matched,
            ):
                score += 90

            if has_event_context(context):
                score += 40

            if has_negative_context(context):
                score -= 70

            scores[code] += score
            objects[code] = country

    if not scores:
        return None

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    code, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else None

    return {
        "country": objects[code],
        "score": score,
        "second_score": second,
    }


# ============================================================
# CITY DETECTION
# ============================================================

def city_mentions(text):
    n = normalize(text)
    found = []

    # Longer names first
    words = re.findall(
        r"[a-zA-ZÀ-ÿ0-9'\-]+",
        n,
    )

    phrases = set()

    for size in (4, 3, 2, 1):
        for i in range(
            0,
            len(words) - size + 1,
        ):
            phrase = " ".join(
                words[i:i + size]
            )

            if phrase in BLOCKED_CITY_TERMS:
                continue

            if phrase in city_index:
                phrases.add(phrase)

    for phrase in phrases:
        if phrase in BLOCKED_CITY_TERMS:
            continue

        for match in re.finditer(
            phrase_pattern(phrase),
            n,
        ):
            for city in city_index[phrase]:
                found.append(
                    {
                        "city": city,
                        "matched": phrase,
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

    return found


def score_city_mention(
    mention,
    text,
    base,
    preferred_country_code=None,
):
    city = mention["city"]
    matched = mention["matched"]

    if matched in BLOCKED_CITY_TERMS:
        return -100000

    score = base
    population = city.get("population", 0) or 0

    if population:
        score += min(
            15,
            math.log10(population + 1) * 2.5,
        )

    context = local_context(
        text,
        mention["start"],
        mention["end"],
    )

    if explicit_location_relation(
        context,
        matched,
    ):
        score += 110

    if has_event_context(context):
        score += 45

    if has_negative_context(context):
        score -= 100

    if matched in AMBIGUOUS_CITY_NAMES:
        score -= 90

    if len(matched) <= 3:
        score -= 50

    if preferred_country_code:
        if city.get("countrycode") == preferred_country_code:
            score += 80
        else:
            score -= 100

    return score


def best_city(
    title,
    summary,
    preferred_country_code=None,
):
    candidates = defaultdict(
        lambda: {
            "score": 0,
            "city": None,
        }
    )

    for text, base in [
        (title, 120),
        (summary, 35),
    ]:
        for mention in city_mentions(text):
            city = mention["city"]

            key = (
                city.get("name"),
                city.get("countrycode"),
                city.get("latitude"),
                city.get("longitude"),
            )

            score = score_city_mention(
                mention,
                text,
                base,
                preferred_country_code,
            )

            if score <= -10000:
                continue

            candidates[key]["score"] += score
            candidates[key]["city"] = city

    if not candidates:
        return None

    ranked = sorted(
        candidates.values(),
        key=lambda x: x["score"],
        reverse=True,
    )

    result = ranked[0]
    result["second_score"] = (
        ranked[1]["score"]
        if len(ranked) > 1
        else None
    )

    return result


# ============================================================
# ORGANISATION FALLBACK
# ============================================================

def organisation_prior(title, summary):
    text = normalize(
        title + " " + summary
    )

    matches = []

    for name, (country_name, code) in ORG_PRIORS.items():
        if contains_phrase(
            text,
            name,
        ):
            matches.append(
                (name, country_name, code)
            )

    if not matches:
        return None

    # If multiple priors point to different countries,
    # do not guess.
    codes = {
        item[2]
        for item in matches
    }

    if len(codes) != 1:
        return None

    name, country_name, code = matches[0]

    country = country_by_code(code)

    if not country:
        country = country_by_name(
            country_name
        )

    return {
        "actor": name,
        "country": country,
    }


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
    event["location_method"] = "contextual_geolocation_v3"


def set_city(event, city, confidence, method):
    code = city.get("countrycode")
    country = countries.get(code)

    event["city"] = city.get("name")
    event["region"] = None
    event["country"] = (
        country.get("name")
        if country
        else None
    )
    event["country_code"] = code
    event["latitude"] = float(
        city.get("latitude")
    )
    event["longitude"] = float(
        city.get("longitude")
    )
    event["location_precision"] = "city"
    event["location_confidence"] = confidence
    event["location_method"] = method


def set_region(event, region, confidence="medium"):
    event["city"] = None
    event["region"] = region.get("label")
    event["country"] = region.get("country")
    event["country_code"] = region.get("country_code")
    event["latitude"] = float(
        region.get("lat")
    )
    event["longitude"] = float(
        region.get("lon")
    )
    event["location_precision"] = "region"
    event["location_confidence"] = confidence
    event["location_method"] = "explicit_region"


# ============================================================
# GEOLOCATE ONE EVENT
# ============================================================

def geolocate_event(event):
    clear_location(event)

    # Source name must never determine incident location.
    source = event.get(
        "source",
        ""
    )

    title = strip_source_name(
        event.get("title", ""),
        source,
    )

    summary = strip_source_name(
        event.get("summary", ""),
        source,
    )

    if not title and not summary:
        return event

    # --------------------------------------------------------
    # 1. Explicit country
    # --------------------------------------------------------

    country_result = best_country(
        title,
        summary,
    )

    preferred_code = None

    if (
        country_result
        and
        country_result["score"] >= 80
    ):
        preferred_code = (
            country_result["country"].get("iso")
        )

    # --------------------------------------------------------
    # 2. Explicit city
    # --------------------------------------------------------

    city_result = best_city(
        title,
        summary,
        preferred_code,
    )

    if city_result:
        score = city_result["score"]
        second = city_result.get(
            "second_score"
        )

        ambiguous = (
            second is not None
            and
            score - second < 35
        )

        if (
            score >= 205
            and
            not ambiguous
        ):
            set_city(
                event,
                city_result["city"],
                "high",
                "explicit_context_city",
            )
            return event

        if (
            score >= 155
            and
            not ambiguous
        ):
            set_city(
                event,
                city_result["city"],
                "medium",
                "context_city",
            )
            return event

    # --------------------------------------------------------
    # 3. Region
    # --------------------------------------------------------

    region_result = find_region(
        title,
        summary,
    )

    if region_result:
        region_score, region = (
            region_result
        )

        if region_score >= 100:
            set_region(
                event,
                region,
                (
                    "high"
                    if region_score >= 220
                    else "medium"
                ),
            )
            return event

    # --------------------------------------------------------
    # 4. Explicit country -> capital
    # --------------------------------------------------------

    if country_result:
        score = country_result["score"]
        second = country_result.get(
            "second_score"
        )

        ambiguous = (
            second is not None
            and
            score - second < 40
        )

        if (
            score >= 80
            and
            not ambiguous
        ):
            if set_country_capital(
                event,
                country_result["country"],
                "explicit_country_capital",
                (
                    "high"
                    if score >= 160
                    else "medium"
                ),
            ):
                return event

    # --------------------------------------------------------
    # 5. Organisation prior -> country capital
    # --------------------------------------------------------

    prior = organisation_prior(
        title,
        summary,
    )

    if (
        prior
        and
        prior["country"]
    ):
        if set_country_capital(
            event,
            prior["country"],
            "organisation_country_prior",
            "low",
        ):
            return event

    # Truly no usable evidence.
    return event


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("=" * 70)
    print("INTERPOL CT Intelligence Map")
    print("CONTEXTUAL GEOLOCATION V3")
    print("=" * 70)

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    events = data.get(
        "events",
        [],
    )

    print(
        f"Events loaded: {len(events)}"
    )

    counts = defaultdict(int)

    for number, event in enumerate(
        events,
        start=1,
    ):
        geolocate_event(event)

        precision = event.get(
            "location_precision",
            "unknown",
        )

        confidence = event.get(
            "location_confidence",
            "low",
        )

        counts[
            f"{precision}_{confidence}"
        ] += 1

        if number % 100 == 0:
            print(
                f"Processed "
                f"{number}/{len(events)}"
            )

    mapped = sum(
        value
        for key, value in counts.items()
        if not key.startswith("unknown")
    )

    unknown = sum(
        value
        for key, value in counts.items()
        if key.startswith("unknown")
    )

    data["geolocation"] = {
        "method":
            "Contextual offline GeoNames geolocation V3",
        "city_high":
            counts["city_high"],
        "city_medium":
            counts["city_medium"],
        "region_high":
            counts["region_high"],
        "region_medium":
            counts["region_medium"],
        "country_capital_high":
            counts["country_capital_high"],
        "country_capital_medium":
            counts["country_capital_medium"],
        "country_capital_low":
            counts["country_capital_low"],
        "mapped_total":
            mapped,
        "unknown":
            unknown,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 70)
    print("GEOLOCATION COMPLETE")
    print("=" * 70)
    print(
        f"City HIGH:             "
        f"{counts['city_high']}"
    )
    print(
        f"City MEDIUM:           "
        f"{counts['city_medium']}"
    )
    print(
        f"Region HIGH:           "
        f"{counts['region_high']}"
    )
    print(
        f"Region MEDIUM:         "
        f"{counts['region_medium']}"
    )
    print(
        f"Country capital HIGH:  "
        f"{counts['country_capital_high']}"
    )
    print(
        f"Country capital MEDIUM:"
        f" {counts['country_capital_medium']}"
    )
    print(
        f"Organisation fallback: "
        f"{counts['country_capital_low']}"
    )
    print(
        f"Unknown:               "
        f"{unknown}"
    )
    print(
        f"Mapped total:          "
        f"{mapped}/{len(events)}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
