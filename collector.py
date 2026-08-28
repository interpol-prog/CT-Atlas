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
# OSINT COLLECTOR
#
# - Google News RSS
# - English-language reporting
# - 8 CT categories
# - 90-day rolling database
# - Daily 3-day lookback
# - Event-level deduplication
# - Multi-category events supported
# ============================================================


OUTPUT_FILE = "events.json"

RETENTION_DAYS = 90

DAILY_LOOKBACK_DAYS = 3


GOOGLE_NEWS_BASE = (
    "https://news.google.com/rss/search"
)

GOOGLE_LANGUAGE = "en-US"

GOOGLE_COUNTRY = "US"

GOOGLE_EDITION = "US:en"


# ============================================================
# CT CATEGORIES
# ============================================================

CATEGORIES = {

    "Terrorist Financing": [

        '"terrorist financing"',

        '"terror financing"',

        '"financing terrorism"',

        '"terrorist funding"',

        '"terrorist cryptocurrency"',

        '"terror finance network"'
    ],


    "Weapons": [

        '"terrorist weapons"',

        '"terrorist arms"',

        '"weapons smuggling" terrorism',

        '"arms trafficking" terrorism',

        '"terrorist drone"',

        '"terrorist explosives"'
    ],


    "CBRN": [

        '"chemical terrorism"',

        '"biological terrorism"',

        '"radiological terrorism"',

        '"nuclear terrorism"',

        '"CBRN terrorism"',

        '"chemical terrorist attack"',

        '"biological terrorist attack"'
    ],


    "Online Radicalization / Cyberterrorism": [

        '"online radicalization" terrorism',

        '"online radicalisation" terrorism',

        '"terrorist propaganda" online',

        '"terrorist recruitment" online',

        '"cyberterrorism"',

        '"cyber terrorism"',

        '"terrorist cyber attack"',

        '"terrorist social media"'
    ],


    "Attacks": [

        '"terrorist attack"',

        '"terror attack"',

        '"suicide bombing"',

        '"suicide bomber"',

        '"IED attack"',

        '"car bomb" terrorism',

        '"vehicle bomb" terrorism',

        '"jihadist attack"',

        '"terrorist shooting"',

        '"terrorist assassination"'
    ],


    "Arrests": [

        '"terrorist arrested"',

        '"terrorists arrested"',

        '"terror suspect arrested"',

        '"terror suspects arrested"',

        '"terrorism arrest"',

        '"terror suspect detained"',

        '"terrorism suspect detained"'
    ],


    "Legal / Judicial": [

        '"terrorism trial"',

        '"terrorist trial"',

        '"terrorist sentenced"',

        '"terrorist convicted"',

        '"terrorism conviction"',

        '"terror suspect charged"',

        '"terrorism charges"'
    ],


    "Disinformation / Emerging Technologies / AI": [

        '"terrorist artificial intelligence"',

        '"terrorism artificial intelligence"',

        '"terrorist use of AI"',

        '"terrorists using AI"',

        '"terrorist generative AI"',

        '"terrorist deepfake"',

        '"terrorist disinformation"',

        '"terrorist emerging technology"'
    ]
}


# ============================================================
# SOURCE PRIORITY
# ============================================================

SOURCE_PRIORITY = {

    "Reuters": 100,

    "Associated Press": 95,

    "AP News": 95,

    "BBC": 90,

    "BBC News": 90,

    "Al Jazeera": 85,

    "CNN": 80,

    "France 24": 78,

    "France24": 78,

    "DW": 75,

    "Deutsche Welle": 75,

    "The Guardian": 70
}


STOPWORDS = {

    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "after",
    "over",
    "into",
    "as",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "this",
    "that",
    "these",
    "those",
    "says",
    "say",
    "said",
    "new",
    "latest",
    "report",
    "reports"
}


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 CT-Intelligence-Map/1.0"
})


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(text):

    if not text:

        return ""


    text = html.unescape(
        text
    )


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
# NORMALIZE TITLE
# ============================================================

def normalize_title(title):

    title = clean_text(
        title
    ).lower()


    title = re.sub(
        r"[^a-z0-9\s]",
        " ",
        title
    )


    words = [

        word

        for word in title.split()

        if word not in STOPWORDS

    ]


    return " ".join(
        words
    )


# ============================================================
# SOURCE NAME
# ============================================================

def get_source(entry):

    try:

        return clean_text(
            entry.source.get(
                "title",
                ""
            )
        )

    except Exception:

        return ""


# ============================================================
# REMOVE SOURCE SUFFIX FROM TITLE
# ============================================================

def remove_source_suffix(
    title,
    source
):

    title = clean_text(
        title
    )


    source = clean_text(
        source
    )


    if source:

        suffix = (
            " - "
            +
            source
        )


        if title.endswith(
            suffix
        ):

            title = title[
                :-len(suffix)
            ]


    return title.strip()


# ============================================================
# PARSE DATE
# ============================================================

def parse_date(value):

    if not value:

        return None


    try:

        dt = parsedate_to_datetime(
            value
        )


        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )


        return dt.astimezone(
            timezone.utc
        )


    except Exception:

        return None


# ============================================================
# INTERNAL EVENT ID
# ============================================================

def create_event_id(
    title,
    published
):

    key = (

        normalize_title(
            title
        )

        +

        "|"

        +

        str(
            published
        )[:10]

    )


    return hashlib.sha256(
        key.encode(
            "utf-8"
        )
    ).hexdigest()[:16]


# ============================================================
# SOURCE PRIORITY
# ============================================================

def source_rank(source):

    if not source:

        return 0


    source_lower = (
        source.lower()
    )


    for name, score in (
        SOURCE_PRIORITY.items()
    ):

        if (
            name.lower()
            in
            source_lower
        ):

            return score


    return 10


# ============================================================
# GOOGLE NEWS URL
# ============================================================

def build_google_url(
    term,
    days
):

    query = (

        term

        +

        f" when:{days}d"

    )


    encoded = quote_plus(
        query
    )


    return (

        f"{GOOGLE_NEWS_BASE}"

        f"?q={encoded}"

        f"&hl={GOOGLE_LANGUAGE}"

        f"&gl={GOOGLE_COUNTRY}"

        f"&ceid={GOOGLE_EDITION}"

    )


# ============================================================
# FETCH ONE QUERY
# ============================================================

def collect_query(
    category,
    term,
    days
):

    url = build_google_url(
        term,
        days
    )


    for attempt in range(
        1,
        4
    ):

        try:

            response = session.get(
                url,
                timeout=30
            )


            response.raise_for_status()


            feed = feedparser.parse(
                response.content
            )


            results = []


            for entry in feed.entries:


                article_url = entry.get(
                    "link"
                )


                if not article_url:

                    continue


                source = get_source(
                    entry
                )


                title = remove_source_suffix(

                    entry.get(
                        "title",
                        ""
                    ),

                    source

                )


                if not title:

                    continue


                summary = clean_text(
                    entry.get(
                        "summary",
                        ""
                    )
                )


                published_dt = parse_date(
                    entry.get(
                        "published",
                        ""
                    )
                )


                published = (

                    published_dt.isoformat()

                    if published_dt

                    else None

                )


                results.append({

                    "id":
                        create_event_id(
                            title,
                            published
                        ),

                    "category":
                        category,

                    "categories":
                        [
                            category
                        ],

                    "title":
                        title,

                    "summary":
                        summary,

                    "published":
                        published,

                    "source":
                        source,

                    "source_count":
                        1,

                    "url":
                        article_url,

                    "collector":
                        "Google News RSS",

                    "country":
                        None,

                    "country_code":
                        None,

                    "city":
                        None,

                    "latitude":
                        None,

                    "longitude":
                        None,

                    "location_precision":
                        "unknown"

                })


            return results


        except Exception as error:


            print(

                f"      Attempt "
                f"{attempt}/3 failed: "
                f"{error}"

            )


            if attempt < 3:

                time.sleep(
                    attempt * 3
                )


    return []


# ============================================================
# COLLECT ALL CATEGORIES
# ============================================================

def collect_all(
    days
):

    print()

    print(
        "=" * 70
    )

    print(
        "INTERPOL CT Intelligence Map"
    )

    print(
        "OSINT Collector"
    )

    print(
        "=" * 70
    )

    print(
        f"Window: {days} days"
    )

    print(
        "Language: English"
    )


    records = []


    for category_number, (
        category,
        terms
    ) in enumerate(
        CATEGORIES.items(),
        start=1
    ):


        print()

        print(
            f"[{category_number}/"
            f"{len(CATEGORIES)}] "
            f"{category}"
        )


        subtotal = 0


        for query_number, term in enumerate(
            terms,
            start=1
        ):


            print(

                f"   Query "
                f"{query_number}/"
                f"{len(terms)}: "
                f"{term}"

            )


            results = collect_query(
                category,
                term,
                days
            )


            records.extend(
                results
            )


            subtotal += len(
                results
            )


            print(
                f"      → {len(results)}"
            )


            time.sleep(
                0.5
            )


        print(
            f"   CATEGORY TOTAL: {subtotal}"
        )


    return records


# ============================================================
# TITLE SIMILARITY
# ============================================================

def title_similarity(
    title1,
    title2
):

    a = normalize_title(
        title1
    )


    b = normalize_title(
        title2
    )


    if not a or not b:

        return 0.0


    sequence = SequenceMatcher(
        None,
        a,
        b
    ).ratio()


    tokens_a = set(
        a.split()
    )


    tokens_b = set(
        b.split()
    )


    if not tokens_a or not tokens_b:

        overlap = 0.0


    else:

        overlap = (

            len(
                tokens_a
                &
                tokens_b
            )

            /

            len(
                tokens_a
                |
                tokens_b
            )

        )


    return max(
        sequence,
        overlap
    )


# ============================================================
# SAME EVENT?
# ============================================================

def same_event(
    event1,
    event2
):

    # Exact URL = same record/event

    if (

        event1.get(
            "url"
        )

        and

        event1.get(
            "url"
        )
        ==
        event2.get(
            "url"
        )

    ):

        return True


    date1 = event1.get(
        "published"
    )


    date2 = event2.get(
        "published"
    )


    if date1 and date2:

        try:

            dt1 = datetime.fromisoformat(
                date1
            )


            dt2 = datetime.fromisoformat(
                date2
            )


            if abs(
                (
                    dt1
                    -
                    dt2
                ).days
            ) > 3:

                return False


        except Exception:

            pass


    score = title_similarity(

        event1.get(
            "title",
            ""
        ),

        event2.get(
            "title",
            ""
        )

    )


    tokens1 = set(

        normalize_title(
            event1.get(
                "title",
                ""
            )
        ).split()

    )


    tokens2 = set(

        normalize_title(
            event2.get(
                "title",
                ""
            )
        ).split()

    )


    shared = (
        tokens1
        &
        tokens2
    )


    if score >= 0.82:

        return True


    if (

        score >= 0.60

        and

        len(
            shared
        ) >= 5

    ):

        return True


    return False


# ============================================================
# MERGE DUPLICATE EVENT
# ============================================================

def merge_event(
    existing,
    new
):

    existing[
        "source_count"
    ] = (

        existing.get(
            "source_count",
            1
        )

        +

        1

    )


    existing_categories = existing.get(
        "categories",
        [
            existing.get(
                "category"
            )
        ]
    )


    new_categories = new.get(
        "categories",
        [
            new.get(
                "category"
            )
        ]
    )


    for category in new_categories:

        if (

            category

            and

            category not in existing_categories

        ):

            existing_categories.append(
                category
            )


    existing[
        "categories"
    ] = existing_categories


    if (

        source_rank(
            new.get(
                "source",
                ""
            )
        )

        >

        source_rank(
            existing.get(
                "source",
                ""
            )
        )

    ):


        existing[
            "source"
        ] = new.get(
            "source"
        )


        existing[
            "url"
        ] = new.get(
            "url"
        )


        existing[
            "title"
        ] = new.get(
            "title"
        )


        existing[
            "summary"
        ] = new.get(
            "summary"
        )


    old_date = existing.get(
        "published"
    )


    new_date = new.get(
        "published"
    )


    if old_date and new_date:

        if new_date < old_date:

            existing[
                "published"
            ] = new_date


# ============================================================
# EVENT-LEVEL DEDUPLICATION
# ============================================================

def deduplicate_events(
    records
):

    print()

    print(
        "Deduplicating events..."
    )


    events = []


    for number, record in enumerate(
        records,
        start=1
    ):


        duplicate = None


        for existing in events:


            if same_event(
                record,
                existing
            ):

                duplicate = existing

                break


        if duplicate is None:

            events.append(
                record
            )


        else:

            merge_event(
                duplicate,
                record
            )


        if number % 250 == 0:

            print(

                f"   Processed "
                f"{number}/"
                f"{len(records)}"

            )


    print(
        f"Raw records: {len(records)}"
    )


    print(
        f"Unique events: {len(events)}"
    )


    return events


# ============================================================
# LOAD EXISTING DATABASE
# ============================================================

def load_existing():

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )


            return data.get(
                "events",
                []
            )


    except Exception:

        return []


# ============================================================
# REMOVE EVENTS OLDER THAN 90 DAYS
# ============================================================

def prune_old(
    events
):

    cutoff = (

        datetime.now(
            timezone.utc
        )

        -

        timedelta(
            days=RETENTION_DAYS
        )

    )


    result = []


    for event in events:


        published = event.get(
            "published"
        )


        if not published:

            continue


        try:

            dt = datetime.fromisoformat(
                published
            )


            if dt >= cutoff:

                result.append(
                    event
                )


        except Exception:

            pass


    return result


# ============================================================
# SAVE DATABASE
# ============================================================

def save_database(
    events
):

    output = {

        "project":
            "INTERPOL CT Intelligence Map",

        "database_type":
            "Rolling CT situational awareness",

        "retention_days":
            RETENTION_DAYS,

        "default_map_period":
            30,

        "language":
            "English",

        "collector":
            "Google News RSS",

        "last_updated":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "number_of_events":
            len(events),

        "events":
            events

    }


    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if (

        len(
            sys.argv
        ) > 1

        and

        sys.argv[
            1
        ].lower()
        ==
        "backfill"

    ):


        print(
            "90-DAY BACKFILL MODE"
        )


        days = RETENTION_DAYS


        existing = []


    else:


        print(
            "DAILY UPDATE MODE"
        )


        days = DAILY_LOOKBACK_DAYS


        existing = load_existing()


    fresh = collect_all(
        days
    )


    combined = (
        existing
        +
        fresh
    )


    events = deduplicate_events(
        combined
    )


    events = prune_old(
        events
    )


    events.sort(

        key=lambda event:
            event.get(
                "published",
                ""
            ),

        reverse=True

    )


    save_database(
        events
    )


    print()

    print(
        "=" * 70
    )

    print(
        "COLLECTION COMPLETE"
    )

    print(
        "=" * 70
    )

    print(
        f"Database events: "
        f"{len(events)}"
    )

    print(
        f"Retention: "
        f"{RETENTION_DAYS} days"
    )

    print(
        f"Saved to: "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 70
    )


if __name__ == "__main__":

    main()