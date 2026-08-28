import json
import math
import re
from collections import defaultdict

import geonamescache


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# CONSERVATIVE OFFLINE GEOLOCATION
#
# - Context-aware city/country detection
# - Title weighted more than summary
# - Event-location expressions rewarded
# - Ambiguous/common English words blocked
# - Confidence scoring
# - Prefer UNKNOWN over false precision
# ============================================================


INPUT_FILE = "events.json"
OUTPUT_FILE = "events.json"


# ============================================================
# GEO DATABASE
# ============================================================

gc = geonamescache.GeonamesCache(
    min_city_population=5000
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
    "united states": "United States",
    "america": "United States",

    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",

    "russia": "Russian Federation",

    "iran": "Iran, Islamic Republic of",

    "syria": "Syrian Arab Republic",

    "south korea": "Korea, Republic of",

    "north korea":
        "Korea, Democratic People's Republic of",

    "venezuela":
        "Venezuela, Bolivarian Republic of",

    "tanzania":
        "Tanzania, United Republic of",

    "bolivia":
        "Bolivia, Plurinational State of",

    "moldova":
        "Moldova, Republic of",

    "laos":
        "Lao People's Democratic Republic of",

    "brunei":
        "Brunei Darussalam"
}


# ============================================================
# IMPORTANT CT CITY ALIASES
# ============================================================

CITY_ALIASES = {

    "mogadishu": "Mogadishu",

    "baghdad": "Baghdad",

    "kabul": "Kabul",

    "maiduguri": "Maiduguri",

    "mosul": "Mosul",

    "raqqa": "Ar Raqqah",

    "idlib": "Idlib",

    "aleppo": "Aleppo",

    "damascus": "Damascus",

    "beirut": "Beirut",

    "gaza city": "Gaza",

    "sanaa": "Sanaa",

    "sana'a": "Sanaa",

    "karachi": "Karachi",

    "peshawar": "Peshawar",

    "quetta": "Quetta",

    "islamabad": "Islamabad",

    "lahore": "Lahore",

    "kirkuk": "Kirkuk",

    "erbil": "Erbil",

    "arbil": "Erbil",

    "bamako": "Bamako",

    "ouagadougou": "Ouagadougou",

    "niamey": "Niamey",

    "ndjamena": "N'Djamena",

    "n'djamena": "N'Djamena",

    "abuja": "Abuja",

    "lagos": "Lagos",

    "nairobi": "Nairobi",

    "mombasa": "Mombasa"
}


# ============================================================
# HARD-BLOCKED CITY TERMS
#
# These may be real place names in GeoNames, but are far too
# common as ordinary English words in CT reporting.
#
# They must NEVER be used as cities.
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

    "office"
}


# ============================================================
# AMBIGUOUS CITY NAMES
#
# Not completely forbidden, but require strong context.
# ============================================================

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

    "normal"
}


# ============================================================
# EVENT WORDS
# ============================================================

EVENT_WORDS = {

    "attack",
    "attacked",
    "attacks",

    "bomb",
    "bombing",
    "bombed",

    "explosion",
    "exploded",
    "blast",

    "shooting",
    "shot",

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

    "seized",
    "seizure",

    "plot",
    "plotting",

    "clash",
    "clashes",

    "kidnapped",
    "kidnapping",

    "hostage",

    "IED",
    "VBIED",

    "suicide bomber",
    "suicide bombing",

    "terrorist attack",
    "terror attack"
}


# ============================================================
# LOCATION PREPOSITIONS
# ============================================================

LOCATION_PREPOSITIONS = {

    "in",
    "near",
    "at",
    "outside",
    "around",
    "inside",
    "across",
    "from"
}


# ============================================================
# NEGATIVE CONTEXTS
# ============================================================

NEGATIVE_PATTERNS = [

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

    r"\baccording to .* in\b",

    r"\bembassy in\b",

    r"\bgovernment in\b"
]


# ============================================================
# CITY INDEX
# ============================================================

city_index = defaultdict(
    list
)


for city in cities.values():

    name = city.get(
        "name",
        ""
    ).strip()

    if not name:
        continue


    key = name.lower()


    # Never even index hard-blocked terms

    if key in BLOCKED_CITY_TERMS:
        continue


    city_index[
        key
    ].append(
        city
    )


for name in city_index:

    city_index[
        name
    ].sort(

        key=lambda city:

            city.get(
                "population",
                0
            )

            or

            0,

        reverse=True
    )


# ============================================================
# COUNTRY INDEX
# ============================================================

country_index = {}


for country in countries.values():

    name = country.get(
        "name",
        ""
    ).strip()

    if name:

        country_index[
            name.lower()
        ] = country


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(
    text
):

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


def normalize_for_search(
    text
):

    text = normalize_text(
        text
    ).lower()


    return (

        text
        .replace(
            "’",
            "'"
        )
        .replace(
            "–",
            "-"
        )
        .replace(
            "—",
            "-"
        )

    )


def word_boundary_pattern(
    phrase
):

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

            word_boundary_pattern(
                phrase
            ),

            text.lower()

        )

    )


# ============================================================
# EVENT CONTEXT
# ============================================================

def has_event_context(
    context
):

    context = normalize_for_search(
        context
    )


    for word in EVENT_WORDS:

        if contains_phrase(
            context,
            word.lower()
        ):

            return True


    return False


# ============================================================
# LOCATION CUE
# ============================================================

def has_location_cue(
    context,
    place_name
):

    context = normalize_for_search(
        context
    )


    place_name = place_name.lower()


    for prep in LOCATION_PREPOSITIONS:

        pattern = (

            r"\b"

            +

            re.escape(
                prep
            )

            +

            r"\s+(?:the\s+)?"

            +

            re.escape(
                place_name
            )

            +

            r"\b"

        )


        if re.search(
            pattern,
            context
        ):

            return True


    return False


# ============================================================
# NEGATIVE CONTEXT
# ============================================================

def has_negative_context(
    context
):

    context = normalize_for_search(
        context
    )


    for pattern in NEGATIVE_PATTERNS:

        if re.search(
            pattern,
            context
        ):

            return True


    return False


# ============================================================
# COUNTRY MENTIONS
# ============================================================

def country_mentions(
    text
):

    text_lower = normalize_for_search(
        text
    )


    matches = []


    # --------------------------------------------------------
    # ALIASES
    # --------------------------------------------------------

    for alias, official in (
        COUNTRY_ALIASES.items()
    ):

        pattern = word_boundary_pattern(
            alias
        )


        for match in re.finditer(
            pattern,
            text_lower
        ):

            country = country_index.get(
                official.lower()
            )


            if country:

                matches.append({

                    "country":
                        country,

                    "matched":
                        alias,

                    "start":
                        match.start(),

                    "end":
                        match.end()

                })


    # --------------------------------------------------------
    # OFFICIAL NAMES
    # --------------------------------------------------------

    for name, country in (
        country_index.items()
    ):

        if len(
            name
        ) < 4:

            continue


        pattern = word_boundary_pattern(
            name
        )


        for match in re.finditer(
            pattern,
            text_lower
        ):

            matches.append({

                "country":
                    country,

                "matched":
                    name,

                "start":
                    match.start(),

                "end":
                    match.end()

            })


    # --------------------------------------------------------
    # REMOVE DUPLICATES
    # --------------------------------------------------------

    unique = {}


    for item in matches:

        key = (

            item[
                "country"
            ].get(
                "iso"
            ),

            item[
                "start"
            ],

            item[
                "end"
            ]

        )


        unique[
            key
        ] = item


    return list(
        unique.values()
    )


# ============================================================
# SCORE COUNTRIES
# ============================================================

def score_country_mentions(
    title,
    summary
):

    scores = defaultdict(
        float
    )


    # ========================================================
    # TITLE
    # ========================================================

    for mention in country_mentions(
        title
    ):

        code = mention[
            "country"
        ].get(
            "iso"
        )


        score = 80


        if mention[
            "start"
        ] < 40:

            score += 20


        context = normalize_for_search(
            title
        )[

            max(
                0,
                mention[
                    "start"
                ]
                -
                70
            )

            :

            min(
                len(
                    title
                ),
                mention[
                    "end"
                ]
                +
                70
            )

        ]


        if has_event_context(
            context
        ):

            score += 70


        if has_location_cue(
            context,
            mention[
                "matched"
            ]
        ):

            score += 40


        if has_negative_context(
            context
        ):

            score -= 70


        scores[
            code
        ] += score


    # ========================================================
    # SUMMARY
    # ========================================================

    for mention in country_mentions(
        summary
    ):

        code = mention[
            "country"
        ].get(
            "iso"
        )


        score = 25


        context = normalize_for_search(
            summary
        )[

            max(
                0,
                mention[
                    "start"
                ]
                -
                80
            )

            :

            min(
                len(
                    summary
                ),
                mention[
                    "end"
                ]
                +
                80
            )

        ]


        if has_event_context(
            context
        ):

            score += 35


        if has_location_cue(
            context,
            mention[
                "matched"
            ]
        ):

            score += 20


        if has_negative_context(
            context
        ):

            score -= 40


        scores[
            code
        ] += score


    return scores


# ============================================================
# BEST COUNTRY
# ============================================================

def find_best_country(
    title,
    summary
):

    scores = score_country_mentions(
        title,
        summary
    )


    if not scores:

        return None


    ranked = sorted(

        scores.items(),

        key=lambda item:
            item[
                1
            ],

        reverse=True
    )


    best_code, best_score = ranked[
        0
    ]


    second_score = (

        ranked[
            1
        ][
            1
        ]

        if len(
            ranked
        ) > 1

        else None

    )


    country = countries.get(
        best_code
    )


    if not country:

        return None


    return {

        "country":
            country,

        "score":
            best_score,

        "second_score":
            second_score

    }


# ============================================================
# CANDIDATE CITY PHRASES
# ============================================================

def candidate_phrases(
    text
):

    clean = re.sub(

        r"[^A-Za-zÀ-ÿ0-9\s'\-]",

        " ",

        normalize_text(
            text
        )

    )


    words = clean.split()


    phrases = []


    for length in (
        4,
        3,
        2,
        1
    ):

        for index in range(

            0,

            len(
                words
            )
            -
            length
            +
            1

        ):

            phrase = " ".join(

                words[
                    index:
                    index
                    +
                    length
                ]

            ).lower()


            # ------------------------------------------------
            # HARD BLOCK
            # ------------------------------------------------

            if phrase in BLOCKED_CITY_TERMS:

                continue


            phrases.append(
                phrase
            )


    return phrases


# ============================================================
# CITY MENTIONS
# ============================================================

def city_mentions(
    text
):

    normalized = normalize_for_search(
        text
    )


    results = []


    names_to_check = set()


    for phrase in candidate_phrases(
        text
    ):

        # ----------------------------------------------------
        # HARD-BLOCK AGAIN FOR SAFETY
        # ----------------------------------------------------

        if phrase in BLOCKED_CITY_TERMS:

            continue


        if phrase in city_index:

            names_to_check.add(
                phrase
            )


        if phrase in CITY_ALIASES:

            alias_target = CITY_ALIASES[
                phrase
            ].lower()


            if alias_target in city_index:

                names_to_check.add(
                    alias_target
                )


    for city_name in names_to_check:

        if city_name in BLOCKED_CITY_TERMS:

            continue


        aliases = {
            city_name
        }


        for alias, canonical in (
            CITY_ALIASES.items()
        ):

            if (
                canonical.lower()
                ==
                city_name
            ):

                aliases.add(
                    alias
                )


        for alias in aliases:

            if alias in BLOCKED_CITY_TERMS:

                continue


            pattern = word_boundary_pattern(
                alias
            )


            for match in re.finditer(
                pattern,
                normalized
            ):

                for city in city_index[
                    city_name
                ]:

                    results.append({

                        "city":
                            city,

                        "matched":
                            alias,

                        "start":
                            match.start(),

                        "end":
                            match.end()

                    })


    return results


# ============================================================
# CITY SCORE
# ============================================================

def score_city_mention(
    mention,
    full_text,
    source_weight,
    preferred_country_code=None
):

    city = mention[
        "city"
    ]


    matched = mention[
        "matched"
    ].lower()


    # ========================================================
    # ABSOLUTE REJECTION
    # ========================================================

    if matched in BLOCKED_CITY_TERMS:

        return -100000


    population = (

        city.get(
            "population",
            0
        )

        or

        0

    )


    score = source_weight


    # ========================================================
    # SMALL POPULATION BONUS
    # ========================================================

    if population > 0:

        score += min(

            18,

            math.log10(
                population
                +
                1
            )
            *
            3

        )


    # ========================================================
    # TITLE POSITION
    # ========================================================

    if mention[
        "start"
    ] < 45:

        score += 10


    # ========================================================
    # COUNTRY COHERENCE
    # ========================================================

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

            score -= 90


    # ========================================================
    # LOCAL CONTEXT
    # ========================================================

    context_start = max(

        0,

        mention[
            "start"
        ]
        -
        90

    )


    context_end = min(

        len(
            full_text
        ),

        mention[
            "end"
        ]
        +
        90

    )


    context = full_text[
        context_start:
        context_end
    ]


    if has_event_context(
        context
    ):

        score += 65


    if has_location_cue(
        context,
        matched
    ):

        score += 75


    if has_negative_context(
        context
    ):

        score -= 100


    # ========================================================
    # AMBIGUOUS ENGLISH WORD
    # ========================================================

    if matched in AMBIGUOUS_CITY_NAMES:

        score -= 100


    # ========================================================
    # SHORT PLACE NAMES
    # ========================================================

    if len(
        matched
    ) <= 3:

        score -= 50


    return score


# ============================================================
# FIND BEST CITY
# ============================================================

def find_best_city(
    title,
    summary,
    preferred_country_code=None
):

    candidates = defaultdict(
        lambda: {

            "score":
                0,

            "city":
                None

        }
    )


    # ========================================================
    # TITLE
    # ========================================================

    for mention in city_mentions(
        title
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

            normalize_for_search(
                title
            ),

            source_weight=85,

            preferred_country_code=
                preferred_country_code

        )


        if score <= -10000:

            continue


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


    # ========================================================
    # SUMMARY
    # ========================================================

    for mention in city_mentions(
        summary
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

            normalize_for_search(
                summary
            ),

            source_weight=25,

            preferred_country_code=
                preferred_country_code

        )


        if score <= -10000:

            continue


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


    best = ranked[
        0
    ]


    best[
        "second_score"
    ] = (

        ranked[
            1
        ][
            "score"
        ]

        if len(
            ranked
        ) > 1

        else None

    )


    return best


# ============================================================
# CLEAR LOCATION
# ============================================================

def clear_location(
    event
):

    event[
        "city"
    ] = None


    event[
        "country"
    ] = None


    event[
        "country_code"
    ] = None


    event[
        "latitude"
    ] = None


    event[
        "longitude"
    ] = None


    event[
        "location_precision"
    ] = "unknown"


    event[
        "location_confidence"
    ] = "low"


    event[
        "location_score"
    ] = 0


    event[
        "location_method"
    ] = "conservative_offline_geonames_v2"


# ============================================================
# SET CITY
# ============================================================

def set_city_location(
    event,
    city,
    score,
    confidence
):

    code = city.get(
        "countrycode"
    )


    country = countries.get(
        code
    )


    event[
        "city"
    ] = city.get(
        "name"
    )


    event[
        "country_code"
    ] = code


    event[
        "country"
    ] = (

        country.get(
            "name"
        )

        if country

        else None

    )


    event[
        "latitude"
    ] = float(
        city.get(
            "latitude"
        )
    )


    event[
        "longitude"
    ] = float(
        city.get(
            "longitude"
        )
    )


    event[
        "location_precision"
    ] = "city"


    event[
        "location_confidence"
    ] = confidence


    event[
        "location_score"
    ] = round(
        score,
        1
    )


    event[
        "location_method"
    ] = "conservative_offline_geonames_v2"


# ============================================================
# SET COUNTRY
# ============================================================

def set_country_location(
    event,
    country,
    score,
    confidence
):

    event[
        "city"
    ] = None


    event[
        "country"
    ] = country.get(
        "name"
    )


    event[
        "country_code"
    ] = country.get(
        "iso"
    )


    event[
        "latitude"
    ] = None


    event[
        "longitude"
    ] = None


    event[
        "location_precision"
    ] = "country"


    event[
        "location_confidence"
    ] = confidence


    event[
        "location_score"
    ] = round(
        score,
        1
    )


    event[
        "location_method"
    ] = "conservative_offline_geonames_v2"


# ============================================================
# GEOLOCATE EVENT
# ============================================================

def geolocate_event(
    event
):

    clear_location(
        event
    )


    title = normalize_text(
        event.get(
            "title",
            ""
        )
    )


    summary = normalize_text(
        event.get(
            "summary",
            ""
        )
    )


    if not title and not summary:

        return event


    # ========================================================
    # COUNTRY FIRST
    # ========================================================

    country_result = find_best_country(
        title,
        summary
    )


    preferred_country_code = None


    if (

        country_result

        and

        country_result[
            "score"
        ]
        >=
        70

    ):

        preferred_country_code = (

            country_result[
                "country"
            ].get(
                "iso"
            )

        )


    # ========================================================
    # CITY
    # ========================================================

    city_result = find_best_city(

        title,

        summary,

        preferred_country_code

    )


    if city_result:

        score = city_result[
            "score"
        ]


        city = city_result[
            "city"
        ]


        second_score = city_result.get(
            "second_score"
        )


        ambiguous = False


        if second_score is not None:

            if (
                score
                -
                second_score
                <
                30
            ):

                ambiguous = True


        if (

            score
            >=
            180

            and

            not ambiguous

        ):

            set_city_location(

                event,
                city,
                score,
                "high"

            )


            return event


        if (

            score
            >=
            135

            and

            not ambiguous

        ):

            set_city_location(

                event,
                city,
                score,
                "medium"

            )


            return event


    # ========================================================
    # COUNTRY FALLBACK
    # ========================================================

    if country_result:

        score = country_result[
            "score"
        ]


        second_score = country_result.get(
            "second_score"
        )


        ambiguous = False


        if second_score is not None:

            if (
                score
                -
                second_score
                <
                35
            ):

                ambiguous = True


        if (

            score
            >=
            135

            and

            not ambiguous

        ):

            set_country_location(

                event,

                country_result[
                    "country"
                ],

                score,

                "high"

            )


            return event


        if (

            score
            >=
            80

            and

            not ambiguous

        ):

            set_country_location(

                event,

                country_result[
                    "country"
                ],

                score,

                "medium"

            )


            return event


    return event


# ============================================================
# VALIDATE
# ============================================================

def validate_event_location(
    event
):

    if (
        event.get(
            "location_precision"
        )
        ==
        "city"
    ):

        # ----------------------------------------------------
        # HARD SAFETY CHECK
        # ----------------------------------------------------

        city_name = (

            event.get(
                "city"
            )

            or

            ""

        ).lower()


        if city_name in BLOCKED_CITY_TERMS:

            clear_location(
                event
            )


            return event


        if (

            event.get(
                "latitude"
            )
            is None

            or

            event.get(
                "longitude"
            )
            is None

        ):

            clear_location(
                event
            )


    if (
        event.get(
            "location_precision"
        )
        ==
        "country"
    ):

        event[
            "city"
        ] = None


        event[
            "latitude"
        ] = None


        event[
            "longitude"
        ] = None


    return event


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print(
        "=" * 70
    )


    print(
        "INTERPOL CT Intelligence Map"
    )


    print(
        "CONSERVATIVE GEOLOCATION V2"
    )


    print(
        "=" * 70
    )


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
        f"Events loaded: "
        f"{len(events)}"
    )


    city_high = 0

    city_medium = 0

    country_high = 0

    country_medium = 0

    unknown_count = 0


    for number, event in enumerate(

        events,

        start=1

    ):

        geolocate_event(
            event
        )


        validate_event_location(
            event
        )


        precision = event.get(
            "location_precision"
        )


        confidence = event.get(
            "location_confidence"
        )


        if (

            precision
            ==
            "city"

            and

            confidence
            ==
            "high"

        ):

            city_high += 1


        elif (

            precision
            ==
            "city"

            and

            confidence
            ==
            "medium"

        ):

            city_medium += 1


        elif (

            precision
            ==
            "country"

            and

            confidence
            ==
            "high"

        ):

            country_high += 1


        elif (

            precision
            ==
            "country"

            and

            confidence
            ==
            "medium"

        ):

            country_medium += 1


        else:

            unknown_count += 1


        if number % 100 == 0:

            print(

                f"Processed "
                f"{number}/"
                f"{len(events)}"

            )


    city_total = (

        city_high
        +
        city_medium

    )


    country_total = (

        country_high
        +
        country_medium

    )


    data[
        "geolocation"
    ] = {

        "method":
            "Conservative offline GeoNames contextual matching v2",

        "strategy":
            "Blocked ambiguous common-language city names",

        "city_locations":
            city_total,

        "city_high_confidence":
            city_high,

        "city_medium_confidence":
            city_medium,

        "country_only":
            country_total,

        "country_high_confidence":
            country_high,

        "country_medium_confidence":
            country_medium,

        "unknown":
            unknown_count

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

    print(
        "=" * 70
    )


    print(
        "GEOLOCATION COMPLETE"
    )


    print(
        "=" * 70
    )


    print(
        f"City-level HIGH:   "
        f"{city_high}"
    )


    print(
        f"City-level MEDIUM: "
        f"{city_medium}"
    )


    print(
        f"City-level TOTAL:  "
        f"{city_total}"
    )


    print()


    print(
        f"Country HIGH:      "
        f"{country_high}"
    )


    print(
        f"Country MEDIUM:    "
        f"{country_medium}"
    )


    print(
        f"Country TOTAL:     "
        f"{country_total}"
    )


    print()


    print(
        f"Unknown:           "
        f"{unknown_count}"
    )


    print(
        "=" * 70
    )


    print(
        "events.json updated."
    )


    print(
        "=" * 70
    )


if __name__ == "__main__":

    main()
