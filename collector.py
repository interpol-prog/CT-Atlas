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
# OSINT COLLECTOR V2
#
# - Google News RSS
# - English-language reporting
# - 8 CT categories
# - Expanded targeted search coverage
# - CT relevance filtering
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
#
# Search coverage has deliberately been increased, but each
# query remains explicitly connected to terrorism/extremism.
# ============================================================

CATEGORIES = {

    # ========================================================
    # 1. TERRORIST FINANCING
    # ========================================================

    "Terrorist Financing": [

        '"terrorist financing"',

        '"terror financing"',

        '"financing terrorism"',

        '"terrorist funding"',

        '"terror finance network"',

        '"terrorist fundraising"',

        '"terrorist crowdfunding"',

        '"terrorist donations"',

        '"terrorist cryptocurrency"',

        '"terrorism cryptocurrency"',

        '"terrorist crypto financing"',

        '"terrorist crypto fundraising"',

        '"terrorist bitcoin"',

        '"terrorist money laundering"',

        '"terror financing money laundering"',

        '"terrorist financial network"',

        '"terrorist financial facilitator"',

        '"terrorist assets frozen"',

        '"terrorist assets seized"',

        '"terror financing sanctions"',

        '"terrorism financing sanctions"',

        '"terrorist bank accounts"',

        '"terrorist hawala"',

        '"extremist financing" terrorism'
    ],


    # ========================================================
    # 2. WEAPONS
    # ========================================================

    "Weapons": [

        '"terrorist weapons"',

        '"terrorist arms"',

        '"terrorist firearms"',

        '"weapons smuggling" terrorism',

        '"arms trafficking" terrorism',

        '"weapons trafficking" terrorism',

        '"terrorist explosives"',

        '"terrorist bomb making"',

        '"terrorist bomb-making"',

        '"terrorist explosive device"',

        '"terrorist IED"',

        '"terrorist drone"',

        '"terrorist drones"',

        '"terrorist weaponized drone"',

        '"terrorist weaponised drone"',

        '"terrorist drone attack"',

        '"terrorist rocket"',

        '"terrorist missiles"',

        '"terrorist ammunition"',

        '"terrorist weapons cache"',

        '"terrorist arms cache"',

        '"terrorist 3D printed weapon"',

        '"terrorist 3D-printed weapon"'
    ],


    # ========================================================
    # 3. CBRN
    # ========================================================

    "CBRN": [

        '"chemical terrorism"',

        '"biological terrorism"',

        '"radiological terrorism"',

        '"nuclear terrorism"',

        '"CBRN terrorism"',

        '"CBRN terrorist"',

        '"chemical terrorist attack"',

        '"biological terrorist attack"',

        '"radiological terrorist attack"',

        '"nuclear terrorist attack"',

        '"terrorist chemical weapon"',

        '"terrorist biological weapon"',

        '"terrorist radiological weapon"',

        '"terrorist nuclear material"',

        '"terrorist radioactive material"',

        '"terrorist poison"',

        '"terrorist toxic chemical"',

        '"terrorist ricin"',

        '"terrorist sarin"',

        '"terrorist chlorine attack"',

        '"terrorist dirty bomb"',

        '"extremist chemical weapon"',

        '"extremist biological weapon"'
    ],


    # ========================================================
    # 4. ONLINE RADICALIZATION / CYBERTERRORISM
    # ========================================================

    "Online Radicalization / Cyberterrorism": [

        '"online radicalization" terrorism',

        '"online radicalisation" terrorism',

        '"online extremist radicalization"',

        '"online extremist radicalisation"',

        '"terrorist propaganda" online',

        '"terrorist propaganda" social media',

        '"terrorist recruitment" online',

        '"terrorist recruitment" social media',

        '"terrorist social media"',

        '"terrorist messaging app"',

        '"terrorist encrypted messaging"',

        '"terrorist online network"',

        '"terrorist online forum"',

        '"terrorist online community"',

        '"terrorist livestream"',

        '"terrorist live stream"',

        '"terrorist video platform"',

        '"cyberterrorism"',

        '"cyber terrorism"',

        '"terrorist cyber attack"',

        '"terrorist cyberattack"',

        '"terrorist hacking"',

        '"terrorist hacker"',

        '"extremist propaganda online"',

        '"extremist recruitment online"'
    ],


    # ========================================================
    # 5. ATTACKS
    # ========================================================

    "Attacks": [

        '"terrorist attack"',

        '"terror attacks"',

        '"terror attack"',

        '"terrorist bombing"',

        '"terrorist bomb attack"',

        '"suicide bombing" terrorism',

        '"suicide bomber" terrorism',

        '"IED attack" terrorism',

        '"improvised explosive device" terrorism',

        '"car bomb" terrorism',

        '"vehicle bomb" terrorism',

        '"truck bomb" terrorism',

        '"terrorist shooting"',

        '"terrorist gun attack"',

        '"terrorist stabbing"',

        '"terrorist knife attack"',

        '"terrorist vehicle attack"',

        '"terrorist ramming attack"',

        '"terrorist assassination"',

        '"terrorist ambush"',

        '"terrorist kidnapping"',

        '"terrorist hostage attack"',

        '"terrorist rocket attack"',

        '"terrorist drone attack"',

        '"jihadist attack"',

        '"jihadist bombing"',

        '"extremist terrorist attack"'
    ],


    # ========================================================
    # 6. ARRESTS / DISRUPTIONS
    # ========================================================

    "Arrests": [

        '"terrorist arrested"',

        '"terrorists arrested"',

        '"terror suspect arrested"',

        '"terror suspects arrested"',

        '"terrorism arrest"',

        '"terrorism arrests"',

        '"terror suspect detained"',

        '"terrorism suspect detained"',

        '"terror suspects detained"',

        '"terrorist detained"',

        '"terror cell arrested"',

        '"terrorist cell arrested"',

        '"terror plot arrests"',

        '"terrorism raid arrests"',

        '"terrorist raid police"',

        '"terror suspect captured"',

        '"terrorist captured"',

        '"terrorism investigation arrest"',

        '"jihadist arrested"',

        '"extremist arrested" terrorism',

        '"ISIS suspect arrested"',

        '"ISIL suspect arrested"',

        '"al Qaeda suspect arrested"'
    ],


    # ========================================================
    # 7. LEGAL / JUDICIAL
    # ========================================================

    "Legal / Judicial": [

        '"terrorism trial"',

        '"terrorist trial"',

        '"terrorist sentenced"',

        '"terrorist sentencing"',

        '"terrorist convicted"',

        '"terrorism conviction"',

        '"terrorism convictions"',

        '"terror suspect charged"',

        '"terrorism suspect charged"',

        '"terrorism charges"',

        '"terrorist charged"',

        '"terrorism prosecution"',

        '"terrorist prosecution"',

        '"terrorism court"',

        '"terrorist court case"',

        '"terrorism guilty"',

        '"terrorist guilty"',

        '"terrorism prison sentence"',

        '"terrorist prison sentence"',

        '"terrorism appeal"',

        '"terrorist appeal"',

        '"terrorism indictment"',

        '"terrorist indictment"',

        '"jihadist sentenced"'
    ],


    # ========================================================
    # 8. DISINFORMATION / AI / EMERGING TECHNOLOGIES
    # ========================================================

    "Disinformation / Emerging Technologies / AI": [

        '"terrorist artificial intelligence"',

        '"terrorism artificial intelligence"',

        '"terrorist use of AI"',

        '"terrorists using AI"',

        '"terrorist generative AI"',

        '"extremist generative AI"',

        '"terrorist AI propaganda"',

        '"terrorist AI recruitment"',

        '"terrorist AI content"',

        '"terrorist chatbot"',

        '"terrorist deepfake"',

        '"terrorist deepfakes"',

        '"extremist deepfake"',

        '"terrorist disinformation"',

        '"terrorist misinformation"',

        '"terrorist emerging technology"',

        '"terrorism emerging technology"',

        '"terrorist autonomous weapon"',

        '"terrorist autonomous drone"',

        '"terrorist facial recognition"',

        '"terrorist 3D printing"',

        '"terrorist virtual reality"',

        '"terrorist metaverse"',

        '"terrorist synthetic media"',

        '"terrorist voice cloning"',

        '"terrorist cryptocurrency technology"',

        '"extremist artificial intelligence"'
    ]
}


# ============================================================
# SOURCE PRIORITY
#
# Google News aggregates many publishers.
# When duplicates are merged, the better-known source is
# preferred for the representative link/title.
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

    "The Guardian": 70,

    "Sky News": 68,

    "ABC News": 66,

    "NBC News": 65,

    "CBS News": 65,

    "The Independent": 62,

    "Euronews": 60
}


# ============================================================
# STOPWORDS FOR EVENT DEDUPLICATION
# ============================================================

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
    "reports",
    "update",
    "updates"
}


# ============================================================
# CT RELEVANCE FILTER
#
# Search queries are expanded considerably, so a second
# relevance layer prevents ordinary crime, finance, AI,
# weapons, legal cases etc. from entering events.json merely
# because Google News matched a loose term.
# ============================================================

CT_ANCHORS = {

    "terror",
    "terrorism",
    "terrorist",
    "terrorists",

    "extremist",
    "extremists",
    "extremism",

    "jihadist",
    "jihadists",
    "jihadism",

    "militant",
    "militants",

    "isis",
    "isil",
    "daesh",

    "al-qaeda",
    "al qaeda",
    "alqaeda",

    "al-shabaab",
    "al shabaab",

    "boko haram",

    "islamic state",

    "hezbollah",

    "hamas"
}


# ============================================================
# CATEGORY-SPECIFIC RELEVANCE TERMS
# ============================================================

CATEGORY_RELEVANCE = {

    "Terrorist Financing": {

        "finance",
        "financing",
        "funding",
        "fundraising",
        "fundraiser",
        "money",
        "bank",
        "banking",
        "account",
        "accounts",
        "asset",
        "assets",
        "sanction",
        "sanctions",
        "crypto",
        "cryptocurrency",
        "bitcoin",
        "hawala",
        "donation",
        "donations",
        "crowdfunding",
        "laundering",
        "financial"
    },


    "Weapons": {

        "weapon",
        "weapons",
        "arms",
        "firearm",
        "firearms",
        "gun",
        "guns",
        "rifle",
        "rifles",
        "ammunition",
        "explosive",
        "explosives",
        "bomb",
        "bombs",
        "ied",
        "drone",
        "drones",
        "rocket",
        "rockets",
        "missile",
        "missiles",
        "smuggling",
        "trafficking",
        "cache"
    },


    "CBRN": {

        "chemical",
        "biological",
        "radiological",
        "radioactive",
        "nuclear",
        "cbrn",
        "toxic",
        "poison",
        "ricin",
        "sarin",
        "chlorine",
        "dirty bomb",
        "pathogen",
        "biohazard"
    },


    "Online Radicalization / Cyberterrorism": {

        "online",
        "internet",
        "social media",
        "telegram",
        "platform",
        "messaging",
        "encrypted",
        "propaganda",
        "recruitment",
        "radicalization",
        "radicalisation",
        "cyber",
        "cyberattack",
        "cyber attack",
        "hacking",
        "hacker",
        "livestream",
        "live stream",
        "forum"
    },


    "Attacks": {

        "attack",
        "attacks",
        "attacked",
        "bomb",
        "bombing",
        "blast",
        "explosion",
        "shooting",
        "shot",
        "stabbing",
        "knife",
        "ramming",
        "assassination",
        "ambush",
        "kidnapping",
        "hostage",
        "ied",
        "suicide bomber",
        "suicide bombing",
        "rocket",
        "drone",
        "killed",
        "dead",
        "wounded"
    },


    "Arrests": {

        "arrest",
        "arrested",
        "arrests",
        "detained",
        "detention",
        "captured",
        "capture",
        "raid",
        "raided",
        "suspect",
        "suspects",
        "cell",
        "investigation",
        "police"
    },


    "Legal / Judicial": {

        "trial",
        "court",
        "charged",
        "charges",
        "convicted",
        "conviction",
        "sentenced",
        "sentence",
        "prosecution",
        "prosecutor",
        "indicted",
        "indictment",
        "guilty",
        "prison",
        "appeal"
    },


    "Disinformation / Emerging Technologies / AI": {

        "artificial intelligence",
        " ai ",
        "generative ai",
        "deepfake",
        "deepfakes",
        "chatbot",
        "machine learning",
        "synthetic media",
        "voice cloning",
        "disinformation",
        "misinformation",
        "emerging technology",
        "autonomous",
        "facial recognition",
        "3d printing",
        "virtual reality",
        "metaverse"
    }
}


# ============================================================
# STRONG CT PHRASES
#
# These are sufficiently terrorism-specific that they can
# support relevance even when the word "terrorism" is not
# explicitly repeated in every headline.
# ============================================================

STRONG_CT_PHRASES = {

    "suicide bomber",
    "suicide bombing",

    "jihadist attack",
    "jihadist plot",

    "isis attack",
    "isis suspect",
    "isis cell",

    "isil attack",
    "isil suspect",

    "daesh attack",

    "al qaeda attack",
    "al-qaeda attack",

    "al shabaab attack",
    "al-shabaab attack",

    "boko haram attack",

    "islamic state attack",

    "terror plot",
    "terror cell",

    "terror financing",

    "terrorist financing"
}


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 CT-Intelligence-Map/2.0"

})


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(
    text
):

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

def normalize_title(
    title
):

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
# NORMALIZE FOR RELEVANCE TEST
# ============================================================

def normalize_relevance_text(
    text
):

    text = clean_text(
        text
    ).lower()


    text = (
        " "
        +
        text
        +
        " "
    )


    return text


# ============================================================
# WORD / PHRASE MATCH
# ============================================================

def contains_term(
    text,
    term
):

    term = term.lower()


    # Multi-word phrase

    if (
        " "
        in
        term.strip()
    ):

        return (
            term
            in
            text
        )


    pattern = (

        r"(?<![a-z0-9])"

        +

        re.escape(
            term
        )

        +

        r"(?![a-z0-9])"

    )


    return bool(

        re.search(
            pattern,
            text
        )

    )


# ============================================================
# ARTICLE RELEVANCE
# ============================================================

def is_relevant_article(
    category,
    title,
    summary
):

    combined = normalize_relevance_text(

        title

        +

        " "

        +

        summary

    )


    title_text = normalize_relevance_text(
        title
    )


    # ========================================================
    # CT ANCHOR
    # ========================================================

    has_ct_anchor = any(

        contains_term(
            combined,
            anchor
        )

        for anchor in CT_ANCHORS

    )


    # ========================================================
    # STRONG CT PHRASE
    # ========================================================

    has_strong_phrase = any(

        contains_term(
            combined,
            phrase
        )

        for phrase in STRONG_CT_PHRASES

    )


    # ========================================================
    # CATEGORY RELEVANCE
    # ========================================================

    category_terms = CATEGORY_RELEVANCE.get(
        category,
        set()
    )


    category_matches = [

        term

        for term in category_terms

        if contains_term(
            combined,
            term
        )

    ]


    # ========================================================
    # BASIC REQUIREMENT
    # ========================================================

    if not (
        has_ct_anchor
        or
        has_strong_phrase
    ):

        return False


    if not category_matches:

        return False


    # ========================================================
    # TITLE BONUS
    #
    # A CT anchor or category term in title is a strong signal.
    # ========================================================

    title_has_anchor = any(

        contains_term(
            title_text,
            anchor
        )

        for anchor in CT_ANCHORS

    )


    title_category_matches = sum(

        1

        for term in category_terms

        if contains_term(
            title_text,
            term
        )

    )


    # Most normal CT reporting passes immediately.

    if (
        title_has_anchor
        and
        title_category_matches >= 1
    ):

        return True


    # Strong CT phrase + category terminology is sufficient.

    if (
        has_strong_phrase
        and
        len(
            category_matches
        ) >= 1
    ):

        return True


    # If title is less explicit, require stronger evidence
    # across title + summary.

    if (
        has_ct_anchor
        and
        len(
            category_matches
        ) >= 2
    ):

        return True


    return False


# ============================================================
# SOURCE NAME
# ============================================================

def get_source(
    entry
):

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
                :-len(
                    suffix
                )
            ]


    return title.strip()


# ============================================================
# PARSE DATE
# ============================================================

def parse_date(
    value
):

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

def source_rank(
    source
):

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


            rejected = 0


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


                # ====================================================
                # CT RELEVANCE FILTER
                # ====================================================

                if not is_relevant_article(

                    category,
                    title,
                    summary

                ):

                    rejected += 1

                    continue


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
                        "unknown",

                    "location_confidence":
                        "low"

                })


            if rejected > 0:

                print(

                    f"      relevance filter rejected: "
                    f"{rejected}"

                )


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
        "OSINT Collector V2"
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


    print(
        "Source: Google News RSS aggregation"
    )


    print(
        "Relevance filter: enabled"
    )


    print(
        f"Total search queries: "
        f"{sum(len(v) for v in CATEGORIES.values())}"
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

                f"      accepted → "
                f"{len(results)}"

            )


            # Small delay to remain polite to Google News

            time.sleep(
                0.35
            )


        print(

            f"   CATEGORY TOTAL: "
            f"{subtotal}"

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

    # ========================================================
    # EXACT URL
    # ========================================================

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


    # ========================================================
    # DATE WINDOW
    #
    # Different reporting about the same CT incident normally
    # clusters within a small number of days.
    # ========================================================

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


    # ========================================================
    # TITLE SIMILARITY
    # ========================================================

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


    # Very similar headline

    if score >= 0.82:

        return True


    # Moderately similar headline with substantial word overlap

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

            category
            not in
            existing_categories

        ):

            existing_categories.append(
                category
            )


    existing[
        "categories"
    ] = existing_categories


    # ========================================================
    # REPRESENTATIVE SOURCE
    # ========================================================

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


    # ========================================================
    # KEEP EARLIEST REPORT DATE
    # ========================================================

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

        f"Raw accepted records: "
        f"{len(records)}"

    )


    print(

        f"Unique events: "
        f"{len(events)}"

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

        "daily_lookback_days":
            DAILY_LOOKBACK_DAYS,

        "language":
            "English",

        "collector":
            "Google News RSS",

        "relevance_filter":
            "CT relevance filter V2",

        "search_query_count":
            sum(
                len(
                    terms
                )
                for terms in CATEGORIES.values()
            ),

        "last_updated":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "number_of_events":
            len(
                events
            ),

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

    # ========================================================
    # BACKFILL
    #
    # python collector.py backfill
    #
    # Searches full 90-day window and rebuilds database.
    # ========================================================

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


    # ========================================================
    # DAILY
    #
    # Normal GitHub automation uses a 3-day overlap.
    # ========================================================

    else:

        print(
            "DAILY UPDATE MODE"
        )


        days = DAILY_LOOKBACK_DAYS


        existing = load_existing()


    # ========================================================
    # COLLECTION
    # ========================================================

    fresh = collect_all(
        days
    )


    combined = (

        existing

        +

        fresh

    )


    # ========================================================
    # DEDUPLICATION
    # ========================================================

    events = deduplicate_events(
        combined
    )


    # ========================================================
    # RETENTION
    # ========================================================

    events = prune_old(
        events
    )


    # ========================================================
    # SORT NEWEST FIRST
    # ========================================================

    events.sort(

        key=lambda event:

            event.get(
                "published",
                ""
            ),

        reverse=True

    )


    # ========================================================
    # SAVE
    # ========================================================

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

        f"Search queries: "
        f"{sum(len(v) for v in CATEGORIES.values())}"

    )


    print(
        "CT relevance filter: ON"
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
