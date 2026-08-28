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
RETENTION_DAYS = 180
DAILY_LOOKBACK_DAYS = 3

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"
GOOGLE_LANGUAGE = "en-US"
GOOGLE_COUNTRY = "US"
GOOGLE_EDITION = "US:en"


CATEGORIES = {
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
        '"extremist financing" terrorism',
    ],

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
        '"terrorist 3D-printed weapon"',
    ],

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
        '"extremist biological weapon"',
    ],

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
        '"extremist recruitment online"',
    ],

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
        '"extremist terrorist attack"',
    ],

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
        '"terror suspect captured"',
        '"terrorist captured"',
        '"terrorism investigation arrest"',
        '"jihadist arrested"',
        '"extremist arrested" terrorism',
        '"ISIS suspect arrested"',
        '"ISIL suspect arrested"',
        '"al Qaeda suspect arrested"',
    ],

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
        '"jihadist sentenced"',
    ],

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
        '"extremist artificial intelligence"',
    ],
}


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
    "Euronews": 60,
}


STOPWORDS = {
    "the","a","an","and","or","of","to","in","on","at","for","from",
    "with","after","over","into","as","by","is","are","was","were","be",
    "this","that","these","those","says","say","said","new","latest",
    "report","reports","update","updates",
}


CT_ANCHORS = {
    "terror","terrorism","terrorist","terrorists",
    "extremist","extremists","extremism",
    "jihadist","jihadists","jihadism",
    "isis","isil","daesh",
    "al-qaeda","al qaeda","alqaeda",
    "al-shabaab","al shabaab",
    "boko haram","islamic state",
    "hezbollah","hizballah","hizbollah",
    "hamas","taliban",
}


CATEGORY_RELEVANCE = {
    "Terrorist Financing": {
        "finance","financing","funding","fundraising","money","bank","account",
        "asset","assets","sanction","sanctions","crypto","cryptocurrency",
        "bitcoin","hawala","donation","donations","crowdfunding","laundering",
        "financial",
    },

    "Weapons": {
        "weapon","weapons","arms","firearm","firearms","gun","rifle",
        "ammunition","explosive","explosives","bomb","ied","drone","drones",
        "rocket","missile","smuggling","trafficking","cache",
    },

    "CBRN": {
        "chemical","biological","radiological","radioactive","nuclear","cbrn",
        "toxic","poison","ricin","sarin","chlorine","dirty bomb","pathogen",
    },

    "Online Radicalization / Cyberterrorism": {
        "online","internet","social media","telegram","platform","messaging",
        "encrypted","propaganda","recruitment","radicalization","radicalisation",
        "cyber","cyberattack","cyber attack","hacking","hacker","livestream",
        "forum",
    },

    "Attacks": {
        "attack","attacks","attacked","bomb","bombing","blast","explosion",
        "shooting","stabbing","ramming","assassination","ambush","kidnapping",
        "hostage","ied","suicide bomber","suicide bombing","rocket","drone",
        "killed","wounded",
    },

    "Arrests": {
        "arrest","arrested","arrests","detained","detention","captured",
        "raid","raided","suspect","suspects","cell","investigation",
    },

    "Legal / Judicial": {
        "trial","court","charged","charges","convicted","conviction","sentenced",
        "sentence","prosecution","prosecutor","indicted","indictment","guilty",
        "prison","appeal",
    },

    "Disinformation / Emerging Technologies / AI": {
        "artificial intelligence","generative ai","deepfake","deepfakes",
        "chatbot","machine learning","synthetic media","voice cloning",
        "disinformation","misinformation","emerging technology","autonomous",
        "facial recognition","3d printing","virtual reality","metaverse",
    },
}


# Articles that mention terrorism historically/politically but are not
# current CT events should be rejected unless stronger event evidence exists.
NON_EVENT_PATTERNS = [
    r"\banniversary\b",
    r"\bcommemorat(?:e|es|ed|ing|ion)\b",
    r"\bmark(?:s|ed|ing)?\s+\d+(?:st|nd|rd|th)?\s+anniversary\b",
    r"\b9/11 memorial\b",
    r"\b9/11 anniversary\b",
    r"\bremember(?:s|ed|ing)?\s+9/11\b",
    r"\btribute\b",
    r"\bretrospective\b",
    r"\bhistory of\b",
    r"\bdocumentary\b",
    r"\bbook review\b",
    r"\bopinion\b",
    r"\bcommentary\b",
]


ACTION_TERMS = {
    "Terrorist Financing": {
        "arrested","charged","convicted","sentenced","sanctioned","frozen",
        "seized","blocked","funded","financed","raised","transferred",
        "laundered","investigation","prosecution",
    },
    "Weapons": {
        "seized","found","recovered","smuggled","trafficked","arrested",
        "charged","used","attack","plot","cache",
    },
    "CBRN": {
        "seized","found","plot","attack","arrested","charged","used",
        "attempted","threatened","investigation",
    },
    "Online Radicalization / Cyberterrorism": {
        "arrested","charged","convicted","recruited","radicalized","radicalised",
        "propaganda","attack","campaign","network","disrupted","removed",
    },
    "Attacks": {
        "attack","attacked","bombing","blast","explosion","shooting","stabbing",
        "ramming","ambush","kidnapping","killed","wounded","hostage",
    },
    "Arrests": {
        "arrest","arrested","detained","captured","raid","raided","seized",
    },
    "Legal / Judicial": {
        "trial","charged","convicted","sentenced","indicted","guilty",
        "prosecution","appeal","court",
    },
    "Disinformation / Emerging Technologies / AI": {
        "used","using","generated","created","deployed","propaganda",
        "recruitment","deepfake","campaign","investigation","arrested",
    },
}


session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 CT-Intelligence-Map/3.0"
})


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)

    words = [
        word
        for word in title.split()
        if word not in STOPWORDS
    ]

    return " ".join(words)


def normalize_relevance_text(text):
    return " " + clean_text(text).lower() + " "


def contains_term(text, term):
    term = term.lower().strip()

    if " " in term:
        return term in text

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(term)
        + r"(?![a-z0-9])"
    )

    return bool(
        re.search(pattern, text)
    )


def has_non_event_pattern(text):
    return any(
        re.search(pattern, text)
        for pattern in NON_EVENT_PATTERNS
    )


def is_relevant_article(
    category,
    title,
    summary,
):
    combined = normalize_relevance_text(
        title + " " + summary
    )

    title_text = normalize_relevance_text(
        title
    )

    has_anchor = any(
        contains_term(combined, anchor)
        for anchor in CT_ANCHORS
    )

    if not has_anchor:
        return False

    category_terms = CATEGORY_RELEVANCE.get(
        category,
        set(),
    )

    category_hits = [
        term
        for term in category_terms
        if contains_term(combined, term)
    ]

    if not category_hits:
        return False

    action_terms = ACTION_TERMS.get(
        category,
        set(),
    )

    action_hits = [
        term
        for term in action_terms
        if contains_term(combined, term)
    ]

    title_anchor = any(
        contains_term(title_text, anchor)
        for anchor in CT_ANCHORS
    )

    title_category = any(
        contains_term(title_text, term)
        for term in category_terms
    )

    title_action = any(
        contains_term(title_text, term)
        for term in action_terms
    )

    # Reject obvious memorial/history/commentary pieces unless they
    # contain strong current action evidence in the title.
    if has_non_event_pattern(combined):
        if not (
            title_anchor
            and
            title_action
        ):
            return False

    # Best signal: CT anchor + category + event/action in headline.
    if (
        title_anchor
        and
        title_category
        and
        title_action
    ):
        return True

    # Headline has CT anchor, and article body has action evidence.
    if (
        title_anchor
        and
        len(category_hits) >= 1
        and
        len(action_hits) >= 1
    ):
        return True

    # Headline has category/action, CT anchor may only appear in summary.
    if (
        title_category
        and
        title_action
        and
        len(category_hits) >= 2
    ):
        return True

    # Require stronger body evidence when headline is vague.
    if (
        len(category_hits) >= 2
        and
        len(action_hits) >= 2
    ):
        return True

    return False


def get_source(entry):
    try:
        return clean_text(
            entry.source.get(
                "title",
                "",
            )
        )
    except Exception:
        return ""


def remove_source_suffix(
    title,
    source,
):
    title = clean_text(title)
    source = clean_text(source)

    if source:
        suffix = " - " + source

        if title.endswith(suffix):
            title = title[:-len(suffix)]

    return title.strip()


def parse_date(value):
    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:
        return None


def create_event_id(
    title,
    published,
):
    key = (
        normalize_title(title)
        + "|"
        + str(published)[:10]
    )

    return hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()[:16]


def source_rank(source):
    if not source:
        return 0

    source_lower = source.lower()

    for name, score in SOURCE_PRIORITY.items():
        if name.lower() in source_lower:
            return score

    return 10


def build_google_url(
    term,
    days,
):
    query = (
        term
        + f" when:{days}d"
    )

    encoded = quote_plus(query)

    return (
        f"{GOOGLE_NEWS_BASE}"
        f"?q={encoded}"
        f"&hl={GOOGLE_LANGUAGE}"
        f"&gl={GOOGLE_COUNTRY}"
        f"&ceid={GOOGLE_EDITION}"
    )


def collect_query(
    category,
    term,
    days,
):
    url = build_google_url(
        term,
        days,
    )

    for attempt in range(1, 4):
        try:
            response = session.get(
                url,
                timeout=30,
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

                source = get_source(entry)

                title = remove_source_suffix(
                    entry.get(
                        "title",
                        "",
                    ),
                    source,
                )

                if not title:
                    continue

                summary = clean_text(
                    entry.get(
                        "summary",
                        "",
                    )
                )

                if not is_relevant_article(
                    category,
                    title,
                    summary,
                ):
                    rejected += 1
                    continue

                published_dt = parse_date(
                    entry.get(
                        "published",
                        "",
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
                            published,
                        ),
                    "category":
                        category,
                    "categories":
                        [category],
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
                    "region":
                        None,
                    "latitude":
                        None,
                    "longitude":
                        None,
                    "location_precision":
                        "unknown",
                    "location_confidence":
                        "low",
                })

            if rejected:
                print(
                    f"      rejected → "
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


def collect_all(days):
    print()
    print("=" * 70)
    print("INTERPOL CT Intelligence Map")
    print("OSINT Collector V3")
    print("=" * 70)
    print(f"Window: {days} days")
    print("Language: English")
    print("Relevance filter: strict event mode")

    records = []

    for category_number, (
        category,
        terms,
    ) in enumerate(
        CATEGORIES.items(),
        start=1,
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
            start=1,
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
                days,
            )

            records.extend(results)
            subtotal += len(results)

            print(
                f"      accepted → "
                f"{len(results)}"
            )

            time.sleep(0.35)

        print(
            f"   CATEGORY TOTAL: "
            f"{subtotal}"
        )

    return records


def title_similarity(
    title1,
    title2,
):
    a = normalize_title(title1)
    b = normalize_title(title2)

    if not a or not b:
        return 0.0

    sequence = SequenceMatcher(
        None,
        a,
        b,
    ).ratio()

    tokens_a = set(a.split())
    tokens_b = set(b.split())

    if not tokens_a or not tokens_b:
        overlap = 0.0
    else:
        overlap = (
            len(tokens_a & tokens_b)
            /
            len(tokens_a | tokens_b)
        )

    return max(
        sequence,
        overlap,
    )


def same_event(
    event1,
    event2,
):
    if (
        event1.get("url")
        and
        event1.get("url")
        ==
        event2.get("url")
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
                (dt1 - dt2).days
            ) > 3:
                return False

        except Exception:
            pass

    score = title_similarity(
        event1.get("title", ""),
        event2.get("title", ""),
    )

    tokens1 = set(
        normalize_title(
            event1.get(
                "title",
                "",
            )
        ).split()
    )

    tokens2 = set(
        normalize_title(
            event2.get(
                "title",
                "",
            )
        ).split()
    )

    shared = tokens1 & tokens2

    if score >= 0.82:
        return True

    if (
        score >= 0.60
        and
        len(shared) >= 5
    ):
        return True

    return False


def merge_event(
    existing,
    new,
):
    existing["source_count"] = (
        existing.get(
            "source_count",
            1,
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
        ],
    )

    new_categories = new.get(
        "categories",
        [
            new.get(
                "category"
            )
        ],
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

    existing["categories"] = (
        existing_categories
    )

    if (
        source_rank(
            new.get(
                "source",
                "",
            )
        )
        >
        source_rank(
            existing.get(
                "source",
                "",
            )
        )
    ):
        existing["source"] = new.get(
            "source"
        )

        existing["url"] = new.get(
            "url"
        )

        existing["title"] = new.get(
            "title"
        )

        existing["summary"] = new.get(
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
            existing["published"] = (
                new_date
            )


def deduplicate_events(records):
    print()
    print("Deduplicating events...")

    events = []

    for number, record in enumerate(
        records,
        start=1,
    ):
        duplicate = None

        for existing in events:
            if same_event(
                record,
                existing,
            ):
                duplicate = existing
                break

        if duplicate is None:
            events.append(record)
        else:
            merge_event(
                duplicate,
                record,
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


def load_existing():
    try:
        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

            return data.get(
                "events",
                [],
            )
    except Exception:
        return []


def prune_old(events):
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
                result.append(event)

        except Exception:
            pass

    return result


def save_database(events):
    output = {
        "project":
            "INTERPOL CT Intelligence Map",
        "database_type":
            "Rolling CT situational awareness",
        "retention_days":
            RETENTION_DAYS,
        "default_map_period":
            180,
        "daily_lookback_days":
            DAILY_LOOKBACK_DAYS,
        "language":
            "English",
        "collector":
            "Google News RSS",
        "relevance_filter":
            "CT event relevance filter V3",
        "search_query_count":
            sum(
                len(terms)
                for terms
                in CATEGORIES.values()
            ),
        "last_updated":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "number_of_events":
            len(events),
        "events":
            events,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )


def main():
    if (
        len(sys.argv) > 1
        and
        sys.argv[1].lower()
        ==
        "backfill"
    ):
        print(
            "180-DAY BACKFILL MODE"
        )
        days = RETENTION_DAYS
        existing = []
    else:
        print(
            "DAILY UPDATE MODE"
        )
        days = DAILY_LOOKBACK_DAYS
        existing = load_existing()

    fresh = collect_all(days)

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
                "",
            ),
        reverse=True,
    )

    save_database(events)

    print()
    print("=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
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
        "CT event relevance filter: ON"
    )
    print(
        f"Saved to: "
        f"{OUTPUT_FILE}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
