import json
import re

import geonamescache


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# OFFLINE GEOLOCATION
#
# Uses local GeoNames city/country data.
# No external geocoding API required.
# ============================================================


INPUT_FILE = "events.json"

OUTPUT_FILE = "events.json"


gc = geonamescache.GeonamesCache(
    min_city_population=5000
)


cities = gc.get_cities()

countries = gc.get_countries()


# ============================================================
# COUNTRY ALIASES
# ============================================================

COUNTRY_ALIASES = {

    "usa":
        "United States",

    "u.s.":
        "United States",

    "u.s.a.":
        "United States",

    "us":
        "United States",

    "america":
        "United States",

    "uk":
        "United Kingdom",

    "u.k.":
        "United Kingdom",

    "britain":
        "United Kingdom",

    "russia":
        "Russian Federation",

    "iran":
        "Iran, Islamic Republic of",

    "syria":
        "Syrian Arab Republic",

    "south korea":
        "Korea, Republic of",

    "north korea":
        "Korea, Democratic People's Republic of",

    "venezuela":
        "Venezuela, Bolivarian Republic of"
}


# ============================================================
# CITY INDEX
# ============================================================

city_index = {}


for city in cities.values():


    name = city.get(
        "name",
        ""
    ).strip()


    if not name:

        continue


    key = name.lower()


    city_index.setdefault(
        key,
        []
    ).append(
        city
    )


# Sort ambiguous cities by population

for key in city_index:


    city_index[
        key
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
# NORMALIZE TEXT
# ============================================================

def normalize_text(
    text
):

    if not text:

        return ""


    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )


    text = re.sub(
        r"\s+",
        " ",
        text
    )


    return text.strip()


# ============================================================
# FIND COUNTRY
# ============================================================

def find_country(
    text
):

    text_lower = (
        text.lower()
    )


    # Aliases

    for alias, official in (
        COUNTRY_ALIASES.items()
    ):


        pattern = (

            r"(?<!\w)"

            +

            re.escape(
                alias.lower()
            )

            +

            r"(?!\w)"

        )


        if re.search(
            pattern,
            text_lower
        ):


            country = country_index.get(
                official.lower()
            )


            if country:

                return country


    # Official country names

    matches = []


    for name, country in (
        country_index.items()
    ):


        if len(
            name
        ) < 4:

            continue


        pattern = (

            r"\b"

            +

            re.escape(
                name
            )

            +

            r"\b"

        )


        if re.search(
            pattern,
            text_lower
        ):

            matches.append(
                country
            )


    if matches:


        matches.sort(

            key=lambda country:

                len(
                    country.get(
                        "name",
                        ""
                    )
                ),

            reverse=True

        )


        return matches[
            0
        ]


    return None


# ============================================================
# GENERATE PHRASES FROM TEXT
# ============================================================

def text_phrases(
    text
):

    clean = re.sub(
        r"[^A-Za-zÀ-ÿ0-9\s'-]",
        " ",
        text
    )


    words = [

        word.lower()

        for word in clean.split()

    ]


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

            )


            phrases.append(
                phrase
            )


    return phrases


# ============================================================
# FIND CITY
# ============================================================

def find_city(
    text,
    preferred_country_code=None
):

    candidates = []


    seen = set()


    for phrase in text_phrases(
        text
    ):


        if phrase in seen:

            continue


        seen.add(
            phrase
        )


        entries = city_index.get(
            phrase
        )


        if not entries:

            continue


        for city in entries:


            population = (

                city.get(
                    "population",
                    0
                )

                or

                0

            )


            # Avoid extremely ambiguous tiny 2–3 letter names

            if (

                len(
                    phrase
                ) <= 3

                and

                population < 100000

            ):

                continue


            country_bonus = 0


            if (

                preferred_country_code

                and

                city.get(
                    "countrycode"
                )
                ==
                preferred_country_code

            ):

                country_bonus = 1000000000


            score = (

                country_bonus

                +

                population

                +

                len(
                    phrase
                )
                *
                1000

            )


            candidates.append(

                (
                    score,
                    city
                )

            )


    if not candidates:

        return None


    candidates.sort(

        key=lambda item:
            item[
                0
            ],

        reverse=True

    )


    return candidates[
        0
    ][
        1
    ]


# ============================================================
# GEOLOCATE ONE EVENT
# ============================================================

def geolocate_event(
    event
):

    text = (

        normalize_text(
            event.get(
                "title",
                ""
            )
        )

        +

        " "

        +

        normalize_text(
            event.get(
                "summary",
                ""
            )
        )

    )


    if not text.strip():

        event[
            "location_precision"
        ] = "unknown"

        return event


    country = find_country(
        text
    )


    preferred_country_code = (

        country.get(
            "iso"
        )

        if country

        else None

    )


    city = find_city(

        text,

        preferred_country_code

    )


    # ========================================================
    # CITY LEVEL
    # ========================================================

    if city:


        code = city.get(
            "countrycode"
        )


        country_record = countries.get(
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

            country_record.get(
                "name"
            )

            if country_record

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


        return event


    # ========================================================
    # COUNTRY ONLY
    # ========================================================

    if country:


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


        return event


    # ========================================================
    # UNKNOWN
    # ========================================================

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
        "OFFLINE GEOLOCATION"
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


    city_count = 0

    country_count = 0

    unknown_count = 0


    for number, event in enumerate(
        events,
        start=1
    ):


        geolocate_event(
            event
        )


        precision = event.get(
            "location_precision"
        )


        if precision == "city":

            city_count += 1


        elif precision == "country":

            country_count += 1


        else:

            unknown_count += 1


        if number % 100 == 0:

            print(

                f"Processed "
                f"{number}/"
                f"{len(events)}"

            )


    data[
        "geolocation"
    ] = {

        "method":
            "Offline GeoNames title/summary matching",

        "city_locations":
            city_count,

        "country_only":
            country_count,

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
        f"City-level: "
        f"{city_count}"
    )

    print(
        f"Country-only: "
        f"{country_count}"
    )

    print(
        f"Unknown: "
        f"{unknown_count}"
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":

    main()