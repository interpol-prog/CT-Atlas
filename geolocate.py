import json
import math
import re
from collections import defaultdict

import geonamescache

INPUT_FILE = "events.json"
OUTPUT_FILE = "events.json"

# Every collected event will receive coordinates:
# 1) real city when sufficiently reliable
# 2) national capital when only the country is reliable
# 3) 0,0 placeholder when no country can be identified

UNLOCATED_LATITUDE = 0.0
UNLOCATED_LONGITUDE = 0.0

gc = geonamescache.GeonamesCache(min_city_population=5000)
cities = gc.get_cities()
countries = gc.get_countries()

COUNTRY_ALIASES = {
    "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "us": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom",
    "great britain": "United Kingdom", "russia": "Russian Federation",
    "iran": "Iran, Islamic Republic of", "syria": "Syrian Arab Republic",
    "south korea": "Korea, Republic of",
    "north korea": "Korea, Democratic People's Republic of",
    "venezuela": "Venezuela, Bolivarian Republic of",
    "tanzania": "Tanzania, United Republic of",
    "bolivia": "Bolivia, Plurinational State of",
    "moldova": "Moldova, Republic of",
    "laos": "Lao People's Democratic Republic of",
    "brunei": "Brunei Darussalam",
}

CITY_ALIASES = {
    "raqqa": "Ar Raqqah", "arbil": "Erbil", "sana'a": "Sanaa",
    "ndjamena": "N'Djamena", "n'djamena": "N'Djamena",
    "gaza city": "Gaza",
}

# Real cities with names that are common English/news words must never be selected.
BLOCKED_CITY_TERMS = {
    "police", "security", "justice", "market", "church", "airport", "mission",
    "union", "college", "commerce", "enterprise", "liberty", "independence",
    "peace", "war", "hope", "center", "centre", "government", "state", "court",
    "capital", "army", "military", "intelligence", "embassy", "border", "camp",
    "base", "station", "office",
}

AMBIGUOUS_CITY_NAMES = {
    "reading", "mobile", "nice", "orange", "split", "bath", "sale", "most",
    "beer", "boom", "victoria", "normal",
}

EVENT_WORDS = {
    "attack", "attacked", "attacks", "bomb", "bombing", "bombed", "explosion",
    "exploded", "blast", "shooting", "shot", "killed", "killing", "murdered",
    "assassinated", "assassination", "raid", "raided", "arrest", "arrested",
    "arrests", "detained", "detention", "charged", "convicted", "sentenced",
    "trial", "seized", "seizure", "plot", "plotting", "clash", "clashes",
    "kidnapped", "kidnapping", "hostage", "ied", "vbied", "suicide bomber",
    "suicide bombing", "terrorist attack", "terror attack",
}

LOCATION_PREPOSITIONS = {"in", "near", "at", "outside", "around", "inside", "across", "from"}

NEGATIVE_PATTERNS = [
    r"\b[a-zA-Z]+-based\b", r"\bbased in\b", r"\bheadquartered in\b",
    r"\bheadquarters in\b", r"\boffice in\b", r"\bcorrespondent in\b",
    r"\breporter in\b", r"\bresearcher in\b", r"\banalyst in\b",
    r"\bspeaking in\b", r"\bmeeting in\b", r"\bconference in\b",
    r"\bsummit in\b", r"\bembassy in\b",
]

city_index = defaultdict(list)
for city in cities.values():
    name = city.get("name", "").strip()
    if not name or name.lower() in BLOCKED_CITY_TERMS:
        continue
    city_index[name.lower()].append(city)

for name in city_index:
    city_index[name].sort(key=lambda c: c.get("population", 0) or 0, reverse=True)

country_index = {}
for country in countries.values():
    name = country.get("name", "").strip()
    if name:
        country_index[name.lower()] = country


def normalize_text(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_search(text):
    return normalize_text(text).lower().replace("’", "'").replace("–", "-").replace("—", "-")


def boundary(phrase):
    return r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)"


def contains_phrase(text, phrase):
    return bool(re.search(boundary(phrase), text.lower()))


def has_event_context(context):
    context = normalize_for_search(context)
    return any(contains_phrase(context, word) for word in EVENT_WORDS)


def has_location_cue(context, place):
    context = normalize_for_search(context)
    for prep in LOCATION_PREPOSITIONS:
        pattern = r"\b" + re.escape(prep) + r"\s+(?:the\s+)?" + re.escape(place.lower()) + r"\b"
        if re.search(pattern, context):
            return True
    return False


def has_negative_context(context):
    context = normalize_for_search(context)
    return any(re.search(pattern, context) for pattern in NEGATIVE_PATTERNS)


def country_mentions(text):
    text_lower = normalize_for_search(text)
    matches = []
    for alias, official in COUNTRY_ALIASES.items():
        for match in re.finditer(boundary(alias), text_lower):
            country = country_index.get(official.lower())
            if country:
                matches.append((country, alias, match.start(), match.end()))
    for name, country in country_index.items():
        if len(name) < 4:
            continue
        for match in re.finditer(boundary(name), text_lower):
            matches.append((country, name, match.start(), match.end()))
    unique = {}
    for country, matched, start, end in matches:
        unique[(country.get("iso"), start, end)] = (country, matched, start, end)
    return list(unique.values())


def score_country_mentions(title, summary):
    scores = defaultdict(float)
    for text, base in ((title, 80), (summary, 25)):
        normalized = normalize_for_search(text)
        for country, matched, start, end in country_mentions(text):
            score = base
            if base == 80 and start < 40:
                score += 20
            context = normalized[max(0, start - 80): min(len(normalized), end + 80)]
            if has_event_context(context):
                score += 60 if base == 80 else 30
            if has_location_cue(context, matched):
                score += 40 if base == 80 else 20
            if has_negative_context(context):
                score -= 70 if base == 80 else 40
            scores[country.get("iso")] += score
    return scores


def find_best_country(title, summary):
    scores = score_country_mentions(title, summary)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    code, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else None
    country = countries.get(code)
    if not country:
        return None
    return {"country": country, "score": score, "second_score": second}


def candidate_phrases(text):
    clean = re.sub(r"[^A-Za-zÀ-ÿ0-9\s'\-]", " ", normalize_text(text))
    words = clean.split()
    result = []
    for length in (4, 3, 2, 1):
        for i in range(0, len(words) - length + 1):
            phrase = " ".join(words[i:i + length]).lower()
            if phrase not in BLOCKED_CITY_TERMS:
                result.append(phrase)
    return result


def city_mentions(text):
    normalized = normalize_for_search(text)
    names = set()
    for phrase in candidate_phrases(text):
        if phrase in city_index:
            names.add(phrase)
        if phrase in CITY_ALIASES:
            canonical = CITY_ALIASES[phrase].lower()
            if canonical in city_index:
                names.add(canonical)
    results = []
    for city_name in names:
        if city_name in BLOCKED_CITY_TERMS:
            continue
        aliases = {city_name}
        for alias, canonical in CITY_ALIASES.items():
            if canonical.lower() == city_name:
                aliases.add(alias)
        for alias in aliases:
            if alias in BLOCKED_CITY_TERMS:
                continue
            for match in re.finditer(boundary(alias), normalized):
                for city in city_index[city_name]:
                    results.append({"city": city, "matched": alias, "start": match.start(), "end": match.end()})
    return results


def score_city_mention(mention, full_text, base, preferred_country_code=None):
    city = mention["city"]
    matched = mention["matched"].lower()
    if matched in BLOCKED_CITY_TERMS:
        return -100000
    population = city.get("population", 0) or 0
    score = base + min(18, math.log10(population + 1) * 3)
    if mention["start"] < 45:
        score += 10
    if preferred_country_code:
        score += 80 if city.get("countrycode") == preferred_country_code else -90
    context = full_text[max(0, mention["start"] - 90): min(len(full_text), mention["end"] + 90)]
    if has_event_context(context):
        score += 65
    if has_location_cue(context, matched):
        score += 75
    if has_negative_context(context):
        score -= 100
    if matched in AMBIGUOUS_CITY_NAMES:
        score -= 100
    if len(matched) <= 3:
        score -= 50
    return score


def find_best_city(title, summary, preferred_country_code=None):
    candidates = defaultdict(lambda: {"score": 0, "city": None})
    for text, base in ((title, 85), (summary, 25)):
        normalized = normalize_for_search(text)
        for mention in city_mentions(text):
            city = mention["city"]
            key = (city.get("name"), city.get("countrycode"), city.get("latitude"), city.get("longitude"))
            score = score_city_mention(mention, normalized, base, preferred_country_code)
            if score <= -10000:
                continue
            candidates[key]["score"] += score
            candidates[key]["city"] = city
    if not candidates:
        return None
    ranked = sorted(candidates.values(), key=lambda x: x["score"], reverse=True)
    best = ranked[0]
    best["second_score"] = ranked[1]["score"] if len(ranked) > 1 else None
    return best


def find_capital_city(country):
    capital = normalize_text(country.get("capital", ""))
    code = country.get("iso")
    if not capital:
        return None
    candidates = city_index.get(capital.lower(), [])
    same_country = [c for c in candidates if c.get("countrycode") == code]
    if same_country:
        return same_country[0]
    # Some capitals may be below the min population threshold. Search all cities as a fallback.
    fallback = []
    for city in cities.values():
        if city.get("countrycode") == code and normalize_text(city.get("name", "")).lower() == capital.lower():
            fallback.append(city)
    fallback.sort(key=lambda c: c.get("population", 0) or 0, reverse=True)
    return fallback[0] if fallback else None


def set_city(event, city, score, confidence):
    code = city.get("countrycode")
    country = countries.get(code)
    event.update({
        "city": city.get("name"),
        "country": country.get("name") if country else None,
        "country_code": code,
        "latitude": float(city.get("latitude")),
        "longitude": float(city.get("longitude")),
        "location_precision": "city",
        "location_confidence": confidence,
        "location_score": round(score, 1),
        "location_method": "contextual_city",
    })


def set_country_capital(event, country, score, confidence):
    capital_city = find_capital_city(country)
    if capital_city:
        event.update({
            "city": capital_city.get("name"),
            "country": country.get("name"),
            "country_code": country.get("iso"),
            "latitude": float(capital_city.get("latitude")),
            "longitude": float(capital_city.get("longitude")),
            "location_precision": "country_capital",
            "location_confidence": confidence,
            "location_score": round(score, 1),
            "location_method": "country_fallback_to_capital",
        })
        return True
    return False


def set_unlocated(event):
    event.update({
        "city": None,
        "country": None,
        "country_code": None,
        "latitude": UNLOCATED_LATITUDE,
        "longitude": UNLOCATED_LONGITUDE,
        "location_precision": "unlocated",
        "location_confidence": "unknown",
        "location_score": 0,
        "location_method": "unlocated_placeholder_0_0",
    })


def geolocate_event(event):
    title = normalize_text(event.get("title", ""))
    summary = normalize_text(event.get("summary", ""))
    country_result = find_best_country(title, summary)
    preferred_code = None
    if country_result and country_result["score"] >= 70:
        preferred_code = country_result["country"].get("iso")

    city_result = find_best_city(title, summary, preferred_code)
    if city_result:
        score = city_result["score"]
        second = city_result.get("second_score")
        ambiguous = second is not None and score - second < 30
        if score >= 180 and not ambiguous:
            set_city(event, city_result["city"], score, "high")
            return event
        if score >= 135 and not ambiguous:
            set_city(event, city_result["city"], score, "medium")
            return event

    if country_result:
        score = country_result["score"]
        second = country_result.get("second_score")
        ambiguous = second is not None and score - second < 35
        if not ambiguous and score >= 80:
            confidence = "high" if score >= 135 else "medium"
            if set_country_capital(event, country_result["country"], score, confidence):
                return event

    set_unlocated(event)
    return event


def main():
    print("=" * 70)
    print("INTERPOL CT Intelligence Map")
    print("GEOLOCATION — ALL EVENTS MAPPED")
    print("=" * 70)

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    events = data.get("events", [])
    print(f"Events loaded: {len(events)}")

    city_high = city_medium = capital_count = unlocated_count = 0

    for number, event in enumerate(events, start=1):
        geolocate_event(event)
        precision = event.get("location_precision")
        confidence = event.get("location_confidence")
        if precision == "city" and confidence == "high":
            city_high += 1
        elif precision == "city":
            city_medium += 1
        elif precision == "country_capital":
            capital_count += 1
        else:
            unlocated_count += 1
        if number % 100 == 0:
            print(f"Processed {number}/{len(events)}")

    data["geolocation"] = {
        "method": "Contextual GeoNames with country-to-capital fallback",
        "all_events_have_coordinates": True,
        "city_locations": city_high + city_medium,
        "city_high_confidence": city_high,
        "city_medium_confidence": city_medium,
        "country_capital_fallback": capital_count,
        "unlocated_placeholder": unlocated_count,
        "unlocated_coordinates": [UNLOCATED_LATITUDE, UNLOCATED_LONGITUDE],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print("GEOLOCATION COMPLETE")
    print("=" * 70)
    print(f"City HIGH:           {city_high}")
    print(f"City MEDIUM:         {city_medium}")
    print(f"Country → capital:   {capital_count}")
    print(f"Unlocated at 0,0:    {unlocated_count}")
    print(f"TOTAL WITH COORDS:   {len(events)}")
    print("=" * 70)
    print("events.json updated.")


if __name__ == "__main__":
    main()
