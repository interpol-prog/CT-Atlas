import feedparser
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import random

import requests

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


# ============================================================
# LIVE GITHUB ACTIONS LOGGING
# ============================================================

try:
    sys.stdout.reconfigure(
        line_buffering=True,
        write_through=True,
    )
    sys.stderr.reconfigure(
        line_buffering=True,
        write_through=True,
    )
except Exception:
    pass


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# OSINT COLLECTOR V10 — MULTILINGUAL GEMINI + FAST DEDUP + 24H TREND
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

# Google News RSS is intentionally queried conservatively.
# The previous version issued 351 searches during a backfill and could
# trigger long 503 retry storms. V7 keeps all source families but uses
# broader searches + local classification.
REQUEST_ATTEMPTS = 2
REQUEST_PAUSE_SECONDS = 0.85
SERVER_ERROR_COOLDOWN_SECONDS = 45
SERVER_ERROR_STREAK_LIMIT = 4

QUERY_STATS = Counter()
SERVER_ERROR_STREAK = 0


# ============================================================
# GEMINI AI ARTICLE SELECTION
#
# The deterministic relevance filter remains a cheap first-pass candidate
# filter. After event-level deduplication, Gemini reviews every candidate
# event semantically and assigns a relevance score from 0 to 100.
#
# User preference: keep score >= 50 to avoid over-filtering.
# ============================================================

AI_SELECTION_ENABLED = True

GEMINI_INTERACTIONS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)

AI_SELECTION_MODEL = os.getenv(
    "AI_SELECTION_MODEL",
    "gemini-3.5-flash-lite",
)

AI_SELECTION_THRESHOLD = int(
    os.getenv(
        "AI_SELECTION_THRESHOLD",
        "50",
    )
)

AI_SELECTION_BATCH_SIZE = max(
    1,
    min(
        40,
        int(
            os.getenv(
                "AI_SELECTION_BATCH_SIZE",
                "20",
            )
        ),
    ),
)

AI_SELECTION_VERSION = "gemini-ct-selection-v2-multilingual"
AI_SELECTION_CACHE_FILE = "ai_article_selection_cache.json"

AI_SELECTION_ATTEMPTS = 5
AI_SELECTION_TIMEOUT = 240
AI_SELECTION_PAUSE_SECONDS = 8.0


# ============================================================
# GEMINI 24H SENSITIVE TREND SUMMARY
#
# One lightweight synthesis per completed collection run. It never blocks
# database publication: if Gemini is unavailable, a deterministic fallback
# is stored instead.
# ============================================================

AI_TREND_MODEL = os.getenv(
    "AI_TREND_MODEL",
    AI_SELECTION_MODEL,
)

AI_TREND_ATTEMPTS = 3
AI_TREND_TIMEOUT = 180
AI_TREND_MAX_CANDIDATES = 80


# ============================================================
# WEEKLY CT CRIMINAL ANALYSIS
#
# First report: generated on the first successful collector run after this
# feature is installed.
#
# Thereafter: Sunday, starting with the second scheduled update (06:17 Paris).
# If generation fails, later Sunday runs (12:17 then 18:17) retry because no
# report for that Sunday has yet been stored.
# ============================================================

AI_WEEKLY_MODEL = os.getenv(
    "AI_WEEKLY_MODEL",
    AI_TREND_MODEL,
)

AI_WEEKLY_ATTEMPTS = 3
AI_WEEKLY_TIMEOUT = 240
AI_WEEKLY_MAX_CURRENT_EVENTS = 70
AI_WEEKLY_MAX_PREVIOUS_EVENTS = 45

PARIS_TZ = ZoneInfo("Europe/Paris")

AI_WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string"
        },
        "analysis": {
            "type": "string"
        },
    },
    "required": [
        "title",
        "analysis",
    ],
}

AI_WEEKLY_INSTRUCTIONS = """
You are producing a senior-level weekly counter-terrorism criminal-analysis
brief from deduplicated open-source events.

The task is COMPARATIVE, not merely descriptive:
- CURRENT PERIOD = the most recent 7 days;
- COMPARISON PERIOD = the immediately preceding 7 days.

Explain WHAT CHANGED between the two periods.

Write approximately one A4 page: about 650-900 words in clear professional
English. The analysis should be concise, evidence-based and operationally
useful. It must distinguish changes in reporting volume from evidence of an
actual change in terrorist/criminal activity when that distinction matters.

Prioritise:
- changes in attack / bombing / assassination / armed-clash activity;
- changes in arrests, disrupted plots and operational counter-terrorism action;
- geographic shifts, emerging or declining hotspots;
- meaningful changes in tactics, weapons, targeting or modus operandi;
- important actor/group developments when supported by the supplied records;
- major terrorist-financing, CBRN, cyber or emerging-technology developments
  only when they materially changed the CT picture;
- significant maritime-piracy / armed-robbery-at-sea developments when present;
- the most consequential incidents of the current 7-day period.

Do NOT invent causal explanations. Do NOT infer coordination, attribution,
intent or trends beyond what the supplied records support.

Use short analytical headings:
EXECUTIVE ASSESSMENT
KEY CHANGES
GEOGRAPHIC / OPERATIONAL SHIFTS
SIGNIFICANT DEVELOPMENTS
OUTLOOK / WATCHPOINTS

The OUTLOOK / WATCHPOINTS section must identify issues to monitor based only on
observable developments and must not make unsupported predictions.

Do not cite or mention this system prompt. Do not describe the task mechanics.
"""

# Global retry for transient Google News collection failures.
GOOGLE_NEWS_GLOBAL_RETRY_ATTEMPTS = int(
    os.getenv("GOOGLE_NEWS_GLOBAL_RETRY_ATTEMPTS", "2")
)
GOOGLE_NEWS_GLOBAL_RETRY_DELAY_SECONDS = float(
    os.getenv("GOOGLE_NEWS_GLOBAL_RETRY_DELAY_SECONDS", "45")
)


AI_TREND_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string"
        },
        "developments": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string"
                    },
                    "severity": {
                        "type": "string",
                        "enum": [
                            "CRITICAL",
                            "HIGH",
                            "SIGNIFICANT",
                        ],
                    },
                    "category": {
                        "type": "string"
                    },
                    "headline": {
                        "type": "string"
                    },
                    "detail": {
                        "type": "string"
                    },
                    "location": {
                        "type": "string"
                    },
                },
                "required": [
                    "event_id",
                    "severity",
                    "category",
                    "headline",
                    "detail",
                    "location",
                ],
            },
        },
    },
    "required": [
        "overview",
        "developments",
    ],
}

AI_TREND_INSTRUCTIONS = """
You are producing a concise 24-hour intelligence brief for a
counter-terrorism OSINT situational-awareness dashboard.

Select ONLY the most operationally important and sensitive developments from
the supplied deduplicated events reported or materially updated during the
last 24 hours.

PRIORITISE:
- the deadliest or most violent terrorist attacks;
- bombings, suicide attacks, assassinations and major armed clashes;
- major disrupted plots or imminent-threat cases;
- arrests of important operatives, leaders, cells or large networks;
- major weapons/explosives/CBRN discoveries or seizures;
- strategically important terrorist-financing disruptions;
- major propaganda/cyber/emerging-technology developments when operationally significant;
- other developments with clear cross-border or strategic CT significance.

DE-PRIORITISE:
- routine arrests or sentencing;
- minor incidents;
- generic political statements;
- retrospective reporting;
- stories whose importance is mainly rhetorical rather than operational.

The overview MUST be 2-3 concise sentences in professional English and MUST
be concrete, place-based and case-based. Name the COUNTRY and, where supported,
the REGION or CITY. Identify the THREE most serious, deadly or sensitive cases
from the reporting period whenever at least three qualifying cases exist.
For example: a suicide bombing in a named province, a major arrest in a named
country, or a significant weapons discovery in a named city. Do NOT write a
generic thematic paragraph such as "activity was characterized by heightened
violence". The reader should immediately learn WHAT happened, WHERE it happened,
and WHY these specific cases matter. If fewer than three genuinely significant
cases exist, mention only those.

Return between 0 and 6 developments. It is better to return 2 genuinely
important items than 6 weak ones. For every selected development, copy the
event_id EXACTLY from the corresponding supplied event. Never invent or alter
an event_id. Each development must use the most specific supported location
available. Do not invent facts, casualty figures, locations, identities,
responsibility claims or significance. Preserve uncertainty and attribution.

Severity meanings:
- CRITICAL: exceptional immediate/high-impact CT development;
- HIGH: major operationally significant CT development;
- SIGNIFICANT: notable enough to belong in a short senior-level 24h brief.

The supplied timestamps indicate reporting/update recency. Do not state that
an incident itself occurred within the last 24 hours unless the event text
supports that conclusion.
"""


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

    "Maritime Piracy": [
        '"maritime piracy"',
        '"pirate attack" ship',
        '"pirate attacks" vessel',
        '"armed robbery at sea"',
        'pirates hijacked vessel',
        'pirates hijacked ship',
        'pirates boarded vessel',
        'pirates kidnapped crew',
        'piracy merchant vessel',
        'piracy tanker',
        'piracy cargo ship',
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


# ============================================================
# COMPACT CORE SEARCH BANK
#
# These are discovery queries, not the taxonomy itself.
# Articles are still locally tested against the full category relevance
# rules. Six strong searches per category provide broad recall without
# issuing hundreds of near-duplicate Google News requests.
# ============================================================

CORE_SEARCH_QUERIES = {

    "Terrorist Financing": [
        '"terrorist financing"',
        '"terrorist funding"',
        '"terrorist cryptocurrency"',
        '"terrorist sanctions"',
        '"terrorist money laundering"',
        '"terrorist fundraising"',
    ],

    "Weapons": [
        '"terrorist weapons"',
        '"terrorist explosives"',
        '"terrorist drone"',
        '"weapons trafficking" terrorism',
        '"terrorist IED"',
        '"terrorist weapons cache"',
    ],

    "CBRN": [
        '"chemical terrorism"',
        '"biological terrorism"',
        '"radiological terrorism"',
        '"nuclear terrorism"',
        '"dirty bomb" terrorism',
        '"CBRN" terrorism',
    ],

    "Online Radicalization / Cyberterrorism": [
        '"online radicalization" terrorism',
        '"terrorist propaganda" online',
        '"terrorist recruitment" online',
        '"terrorist encrypted messaging"',
        '"cyberterrorism"',
        '"terrorist hacking"',
    ],

    "Maritime Piracy": [
        '"maritime piracy"',
        '"armed robbery at sea"',
        '"pirate attack" ship',
        'pirates hijacked vessel',
        'pirates boarded vessel',
        'pirates kidnapped crew',
    ],

    "Attacks": [
        '"terrorist attack"',
        '"terrorist bombing"',
        '"suicide bombing" terrorism',
        '"jihadist attack"',
        '"ISIS attack"',
        '"terrorist shooting"',
    ],

    "Arrests": [
        '"terror suspect arrested"',
        '"terrorism arrests"',
        '"ISIS suspect arrested"',
        '"terrorist cell arrested"',
        '"jihadist arrested"',
        '"terrorism raid" arrests',
    ],

    "Legal / Judicial": [
        '"terrorism trial"',
        '"terrorist sentenced"',
        '"terrorist convicted"',
        '"terror suspect charged"',
        '"terrorism indictment"',
        '"terrorism prosecution"',
    ],

    "Disinformation / Emerging Technologies / AI": [
        '"terrorist artificial intelligence"',
        '"terrorist deepfake"',
        '"terrorist disinformation"',
        '"terrorism emerging technology"',
        '"terrorist autonomous drone"',
        '"terrorist synthetic media"',
    ],
}


# ============================================================
# OFFICIAL / PRIMARY CT SOURCES
#
# These are deliberately queried through the SAME Google News
# RSS mechanism as the rest of the collector.  No API keys or
# credentials are required.
#
# The site: restriction gives us a second acquisition channel
# focused on authoritative primary reporting:
#   - U.S. Department of Justice
#   - U.S. Treasury / OFAC
#   - Europol
#   - UK Government / Counter-Terrorism
#   - INTERPOL English News
#
# Results still pass through the normal CT relevance filter and
# the intelligent event deduplication layer, so the same incident
# is not duplicated simply because an official source and media
# outlets both reported it.
# ============================================================

OFFICIAL_SOURCE_QUERIES = {

    "Terrorist Financing": [

        'site:home.treasury.gov/news/press-releases '
        '(terrorist OR terrorism OR ISIS OR ISIL OR Hamas OR Hizballah OR Hezbollah OR al-Qaeda) '
        '(sanctions OR designation OR designated OR financing OR financial OR facilitator OR network)',

        'site:justice.gov '
        '(terrorist OR terrorism OR ISIS OR ISIL OR Hamas OR Hizballah OR Hezbollah OR al-Qaeda) '
        '("material support" OR financing OR funding OR money laundering OR cryptocurrency)',

        'site:interpol.int/en/News-and-Events/News '
        '("terrorism financing" OR "terrorist financing")',

    ],


    "Weapons": [

        'site:europol.europa.eu/media-press/newsroom '
        '(terrorism OR terrorist OR extremist) '
        '(weapons OR firearms OR explosives OR bomb OR drone)',

        'site:justice.gov '
        '(terrorist OR terrorism OR ISIS OR extremist) '
        '(weapon OR weapons OR firearms OR explosives OR bomb OR drone)',

        'site:interpol.int/en/News-and-Events/News '
        '(terrorism OR terrorist) '
        '(weapons OR firearms OR explosives)',

    ],


    "CBRN": [

        'site:gov.uk/government/news '
        '(terrorism OR terrorist OR extremism) '
        '(chemical OR biological OR radiological OR nuclear OR CBRN)',

        'site:counterterrorism.police.uk/news '
        '(terrorism OR terrorist OR extremist) '
        '(chemical OR biological OR radiological OR nuclear OR CBRN)',

        'site:justice.gov '
        '(terrorism OR terrorist OR extremist) '
        '(chemical OR biological OR radiological OR nuclear OR CBRN)',

    ],


    "Online Radicalization / Cyberterrorism": [

        'site:europol.europa.eu/media-press/newsroom '
        '(terrorism OR terrorist OR extremist OR Terrorgram) '
        '(online OR propaganda OR radicalisation OR radicalization OR platform OR cyber)',

        'site:gov.uk/government/news '
        '(terrorism OR terrorist OR extremism OR extremist) '
        '(online OR radicalisation OR radicalization OR propaganda OR AI)',

        'site:counterterrorism.police.uk/news '
        '(terrorism OR terrorist OR extremist) '
        '(online OR radicalised OR radicalized OR propaganda OR social-media)',

        'site:interpol.int/en/News-and-Events/News '
        '(terrorism OR terrorist) '
        '(online OR social-media OR cyber OR technology)',

    ],


    "Attacks": [

        'site:justice.gov '
        '(terrorist OR terrorism OR ISIS OR ISIL OR al-Qaeda) '
        '(attack OR attacks OR plot OR bombing OR shooting OR stabbing)',

        'site:gov.uk/government/news '
        '(terrorism OR terrorist) '
        '(attack OR plot OR bombing OR shooting OR stabbing)',

        'site:counterterrorism.police.uk/news '
        '(terrorism OR terrorist) '
        '(attack OR plot OR bombing OR shooting OR stabbing)',

        'site:interpol.int/en/News-and-Events/News '
        '(terrorism OR terrorist) '
        '(attack OR attacks OR operation)',

    ],


    "Arrests": [

        'site:justice.gov '
        '(terrorist OR terrorism OR ISIS OR ISIL OR Hamas OR al-Qaeda) '
        '(arrested OR arrests OR detained OR captured)',

        'site:europol.europa.eu/media-press/newsroom '
        '(terrorism OR terrorist OR extremist) '
        '(arrested OR arrests OR detained OR operation)',

        'site:gov.uk/government/news '
        '(terrorism OR terrorist) '
        '(arrested OR arrest OR detained OR charged)',

        'site:counterterrorism.police.uk/news '
        '(terrorism OR terrorist OR extremist) '
        '(arrested OR arrest OR detained OR charged)',

        'site:interpol.int/en/News-and-Events/News '
        '(terrorism OR terrorist) '
        '(arrest OR arrests OR apprehended)',

    ],


    "Legal / Judicial": [

        'site:justice.gov '
        '(terrorist OR terrorism OR ISIS OR ISIL OR Hamas OR al-Qaeda) '
        '(charged OR convicted OR sentenced OR indicted OR indictment OR trial)',

        'site:europol.europa.eu/media-press/newsroom '
        '(terrorism OR terrorist OR extremist) '
        '(convicted OR sentenced OR court OR prosecution OR trial)',

        'site:gov.uk/government/news '
        '(terrorism OR terrorist) '
        '(charged OR convicted OR sentenced OR prosecution OR trial)',

        'site:counterterrorism.police.uk/news '
        '(terrorism OR terrorist OR extremist) '
        '(charged OR convicted OR sentenced OR jailed OR trial)',

    ],


    "Disinformation / Emerging Technologies / AI": [

        'site:europol.europa.eu/media-press/newsroom '
        '(terrorism OR terrorist OR extremist) '
        '("artificial intelligence" OR AI OR deepfake OR cyber OR technology)',

        'site:gov.uk/government/news '
        '(terrorism OR terrorist OR extremism OR extremist) '
        '("artificial intelligence" OR AI OR online OR technology)',

        'site:interpol.int/en/News-and-Events/News '
        '(terrorism OR terrorist) '
        '("artificial intelligence" OR AI OR technology OR emerging)',

    ],

}


# ============================================================
# TARGETED INTERNATIONAL / SPECIALIST SOURCES
#
# Each source is queried through Google News RSS using site:
# restrictions, so the workflow needs no additional API keys.
#
# ACLED NOTE:
# This collector targets ACLED's publicly indexed analysis/news
# pages only.  The full ACLED event dataset/API requires a myACLED
# account and authentication and is therefore not pulled directly
# here.
#
# Source targeting improves recall.  Every returned article still
# has to pass the same CT relevance filter and the same intelligent
# event-level deduplication used for all other records.
# ============================================================

TARGETED_SOURCE_SITES = [

    # Structured conflict / event-analysis source
    {
        "name": "ACLED",
        "site": "acleddata.com",
        "priority": 118,
        "kind": "conflict_data_analysis",
    },

    # International wire / mainstream
    {
        "name": "Reuters",
        "site": "reuters.com",
        "priority": 105,
        "kind": "international_media",
    },
    {
        "name": "Associated Press",
        "site": "apnews.com",
        "priority": 100,
        "kind": "international_media",
    },
    {
        "name": "BBC News",
        "site": "bbc.com",
        "priority": 96,
        "kind": "international_media",
    },
    {
        "name": "CNN",
        "site": "cnn.com",
        "priority": 86,
        "kind": "international_media",
    },
    {
        "name": "France 24 English",
        "site": "france24.com/en",
        "priority": 90,
        "kind": "international_media",
    },
    {
        "name": "Deutsche Welle English",
        "site": "dw.com",
        "priority": 90,
        "kind": "international_media",
    },
    {
        "name": "Al Jazeera English",
        "site": "aljazeera.com",
        "priority": 90,
        "kind": "international_media",
    },
    {
        "name": "i24NEWS",
        "site": "i24news.tv/en",
        "priority": 80,
        "kind": "regional_international_media",
    },
    {
        "name": "RT",
        "site": "rt.com/news",
        "priority": 55,
        "kind": "state_affiliated_media",
    },

    # Additional useful English-language coverage
    {
        "name": "RFI English",
        "site": "rfi.fr/en",
        "priority": 86,
        "kind": "international_media",
    },
    {
        "name": "Voice of America",
        "site": "voanews.com",
        "priority": 80,
        "kind": "international_media",
    },
    {
        "name": "Radio Free Europe / Radio Liberty",
        "site": "rferl.org",
        "priority": 82,
        "kind": "regional_international_media",
    },
    {
        "name": "Sky News",
        "site": "news.sky.com",
        "priority": 80,
        "kind": "international_media",
    },
    {
        "name": "Euronews English",
        "site": "euronews.com",
        "priority": 76,
        "kind": "international_media",
    },
    {
        "name": "The Guardian",
        "site": "theguardian.com",
        "priority": 78,
        "kind": "international_media",
    },

]


# Compact category-specific query components used with each site.
# Keeping these narrower than the broad query bank limits noise and
# makes the targeted-source pass operationally manageable.
TARGETED_MEDIA_CATEGORY_TERMS = {

    "Terrorist Financing":
        '(terrorist OR terrorism OR ISIS OR ISIL OR Daesh OR "Islamic State" '
        'OR "al-Qaeda" OR Hamas OR Hezbollah OR extremist) '
        '(financing OR funding OR sanctions OR assets OR cryptocurrency '
        'OR money-laundering OR fundraising OR donations)',

    "Weapons":
        '(terrorist OR terrorism OR ISIS OR ISIL OR Daesh OR "Islamic State" '
        'OR "al-Qaeda" OR extremist) '
        '(weapons OR firearms OR explosives OR bomb OR IED OR drone '
        'OR arms-trafficking OR weapons-cache)',

    "CBRN":
        '(terrorist OR terrorism OR extremist OR ISIS OR ISIL) '
        '(CBRN OR chemical OR biological OR radiological OR nuclear '
        'OR radioactive OR ricin OR sarin OR chlorine OR "dirty bomb")',

    "Online Radicalization / Cyberterrorism":
        '(terrorist OR terrorism OR extremist OR extremism OR ISIS OR ISIL '
        'OR "Islamic State" OR "al-Qaeda") '
        '(online OR propaganda OR recruitment OR radicalization '
        'OR radicalisation OR cyber OR hacking OR Telegram OR encrypted '
        'OR social-media)',

    "Maritime Piracy":
        '("maritime piracy" OR piracy OR pirates OR "armed robbery at sea") '
        '(ship OR vessel OR tanker OR crew OR maritime OR hijacked OR boarded)',

    "Attacks":
        '(terrorist OR terrorism OR ISIS OR ISIL OR Daesh OR "Islamic State" '
        'OR jihadist OR extremist OR "al-Qaeda" OR "al-Shabaab" '
        'OR "Boko Haram") '
        '(attack OR bombing OR blast OR shooting OR stabbing OR ambush '
        'OR kidnapping OR hostage OR IED OR "suicide bomber" OR drone)',

    "Arrests":
        '(terrorist OR terrorism OR ISIS OR ISIL OR Daesh OR "Islamic State" '
        'OR jihadist OR extremist OR "al-Qaeda") '
        '(arrest OR arrested OR arrests OR detained OR captured OR raid '
        'OR suspects OR cell)',

    "Legal / Judicial":
        '(terrorist OR terrorism OR ISIS OR ISIL OR Daesh OR "Islamic State" '
        'OR jihadist OR extremist OR "al-Qaeda") '
        '(charged OR convicted OR sentenced OR trial OR court OR indicted '
        'OR indictment OR prosecution OR jailed)',

    "Disinformation / Emerging Technologies / AI":
        '(terrorist OR terrorism OR extremist OR extremism OR ISIS OR ISIL '
        'OR "Islamic State" OR "al-Qaeda") '
        '("artificial intelligence" OR AI OR deepfake OR disinformation '
        'OR misinformation OR autonomous OR technology OR "synthetic media" '
        'OR "voice cloning")',

}


def targeted_source_query(
    source,
    category
):
    terms = TARGETED_MEDIA_CATEGORY_TERMS[
        category
    ]

    return (
        "site:"
        +
        source[
            "site"
        ]
        +
        " "
        +
        terms
    )



# ============================================================
# THROTTLE-SAFE SOURCE DISCOVERY
#
# Official sources: one broad CT query per domain.
# Targeted media: one query per source, with a second theme only for
# high-volume sources. Results are classified locally into the 8 categories.
# ============================================================

OFFICIAL_BROAD_QUERIES = [
    {
        "name": "U.S. Department of Justice",
        "query": 'site:justice.gov (terrorism OR terrorist OR ISIS OR ISIL OR "material support")',
    },
    {
        "name": "U.S. Treasury / OFAC",
        "query": 'site:home.treasury.gov (terrorism OR terrorist OR ISIS OR Hamas OR Hezbollah OR "al-Qaeda")',
    },
    {
        "name": "Europol",
        "query": 'site:europol.europa.eu (terrorism OR terrorist OR extremist)',
    },
    {
        "name": "Counter Terrorism Policing UK",
        "query": 'site:counterterrorism.police.uk (terrorism OR terrorist OR extremist)',
    },
    {
        "name": "GOV.UK",
        "query": 'site:gov.uk/government/news (terrorism OR terrorist OR extremism)',
    },
    {
        "name": "INTERPOL",
        "query": 'site:interpol.int/en/News-and-Events/News (terrorism OR terrorist OR "foreign terrorist fighters")',
    },
]

SOURCE_QUERY_THEME_PRIMARY = (
    '(terrorism OR terrorist OR ISIS OR ISIL OR Daesh OR "Islamic State" '
    'OR "al-Qaeda" OR "maritime piracy" OR "armed robbery at sea" OR pirates)'
)

SOURCE_QUERY_THEME_SECONDARY = (
    '(extremist OR jihadist OR "al-Shabaab" OR "Boko Haram" OR Taliban '
    'OR Hamas OR Hezbollah)'
)

DEEP_SCAN_SOURCES = {
    "ACLED",
    "Reuters",
    "Associated Press",
    "BBC News",
    "CNN",
    "France 24 English",
    "Deutsche Welle English",
    "Al Jazeera English",
    "i24NEWS",
}


def targeted_source_queries(source):
    queries = [
        (
            "site:"
            +
            source["site"]
            +
            " "
            +
            SOURCE_QUERY_THEME_PRIMARY
        )
    ]

    if source["name"] in DEEP_SCAN_SOURCES:
        queries.append(
            "site:"
            +
            source["site"]
            +
            " "
            +
            SOURCE_QUERY_THEME_SECONDARY
        )

    return queries


# ============================================================
# MULTILINGUAL CT DISCOVERY
#
# Google News is queried in local-language editions. These records are NOT
# rejected by the English keyword filter: Gemini is the semantic final judge.
# Every retained record is normalized to English before final deduplication.
# ============================================================

MULTILINGUAL_PROFILES = [
    {
        "code": "fr", "name": "French", "hl": "fr", "gl": "FR", "ceid": "FR:fr",
        "queries": [
            {"term": '(terrorisme OR terroriste OR djihadiste OR attentat OR Daech)', "category": "Attacks"},
            {"term": '(\"financement du terrorisme\" OR radicalisation OR propagande djihadiste OR cyberterrorisme OR arrestation terroriste)', "category": "Terrorist Financing"},
        ],
        "sites": ["lemonde.fr", "france24.com/fr"],
        "site_terms": '(terrorisme OR terroriste OR djihadiste OR Daech OR attentat)',
    },
    {
        "code": "ar", "name": "Arabic", "hl": "ar", "gl": "SA", "ceid": "SA:ar",
        "queries": [
            {"term": '(إرهاب OR إرهابي OR داعش OR القاعدة OR جهادي OR هجوم إرهابي)', "category": "Attacks"},
            {"term": '(تمويل الإرهاب OR اعتقال إرهابي OR تطرف OR تجنيد إرهابي OR دعاية إرهابية)', "category": "Terrorist Financing"},
        ],
        "sites": ["aljazeera.net", "alarabiya.net"],
        "site_terms": '(إرهاب OR إرهابي OR داعش OR القاعدة OR جهادي)',
    },
    {
        "code": "de", "name": "German", "hl": "de", "gl": "DE", "ceid": "DE:de",
        "queries": [
            {"term": '(Terrorismus OR Terrorist OR Dschihadist OR Anschlag OR IS-Terror)', "category": "Attacks"},
            {"term": '(Terrorfinanzierung OR Terrorverdächtiger OR Radikalisierung OR Cyberterrorismus OR Festnahme)', "category": "Arrests"},
        ],
        "sites": ["tagesschau.de", "spiegel.de"],
        "site_terms": '(Terrorismus OR Terrorist OR Dschihadist OR Anschlag)',
    },
    {
        "code": "es", "name": "Spanish", "hl": "es", "gl": "ES", "ceid": "ES:es",
        "queries": [
            {"term": '(terrorismo OR terrorista OR yihadista OR atentado OR Estado Islámico)', "category": "Attacks"},
            {"term": '(financiación del terrorismo OR radicalización OR detenido terrorismo OR propaganda yihadista)', "category": "Terrorist Financing"},
        ],
        "sites": ["elpais.com", "elmundo.es"],
        "site_terms": '(terrorismo OR terrorista OR yihadista OR atentado)',
    },
    {
        "code": "it", "name": "Italian", "hl": "it", "gl": "IT", "ceid": "IT:it",
        "queries": [
            {"term": '(terrorismo OR terrorista OR jihadista OR attentato OR Stato Islamico)', "category": "Attacks"},
            {"term": '(finanziamento terrorismo OR radicalizzazione OR arrestato terrorismo OR propaganda jihadista)', "category": "Arrests"},
        ],
        "sites": ["ansa.it", "repubblica.it"],
        "site_terms": '(terrorismo OR terrorista OR jihadista OR attentato)',
    },
    {
        "code": "tr", "name": "Turkish", "hl": "tr", "gl": "TR", "ceid": "TR:tr",
        "queries": [
            {"term": '(terör OR terörist OR DEAŞ OR IŞİD OR terör saldırısı)', "category": "Attacks"},
            {"term": '(terör finansmanı OR terör operasyonu OR terör şüphelisi OR radikalleşme OR terör propagandası)', "category": "Arrests"},
        ],
        "sites": ["aa.com.tr/tr", "trthaber.com"],
        "site_terms": '(terör OR terörist OR DEAŞ OR IŞİD)',
    },
    {
        "code": "ru", "name": "Russian", "hl": "ru", "gl": "RU", "ceid": "RU:ru",
        "queries": [
            {"term": '(терроризм OR террорист OR теракт OR ИГИЛ OR джихадист)', "category": "Attacks"},
            {"term": '(финансирование терроризма OR задержан террорист OR радикализация OR террористическая пропаганда)', "category": "Arrests"},
        ],
        "sites": ["interfax.ru", "kommersant.ru"],
        "site_terms": '(терроризм OR террорист OR теракт OR ИГИЛ)',
    },
    {
        "code": "ur", "name": "Urdu", "hl": "ur", "gl": "PK", "ceid": "PK:ur",
        "queries": [
            {"term": '(دہشت گردی OR دہشت گرد OR داعش OR القاعدہ OR دہشت گرد حملہ)', "category": "Attacks"},
            {"term": '(دہشت گردی کی مالی معاونت OR دہشت گرد گرفتار OR شدت پسندی OR دہشت گرد پروپیگنڈا)', "category": "Terrorist Financing"},
        ],
        "sites": ["jang.com.pk", "express.pk"],
        "site_terms": '(دہشت گردی OR دہشت گرد OR داعش OR القاعدہ)',
    },
    {
        "code": "fa", "name": "Persian", "hl": "fa", "gl": "IR", "ceid": "IR:fa",
        "queries": [
            {"term": '(تروریسم OR تروریست OR داعش OR القاعده OR حمله تروریستی)', "category": "Attacks"},
            {"term": '(تامین مالی تروریسم OR بازداشت تروریست OR افراط گرایی OR تبلیغات تروریستی)', "category": "Terrorist Financing"},
        ],
        "sites": ["iranintl.com", "bbc.com/persian"],
        "site_terms": '(تروریسم OR تروریست OR داعش OR القاعده)',
    },
    {
        "code": "he", "name": "Hebrew", "hl": "he", "gl": "IL", "ceid": "IL:he",
        "queries": [
            {"term": '(טרור OR מחבל OR פיגוע OR דאעש OR אל-קאעדה)', "category": "Attacks"},
            {"term": '(מימון טרור OR נעצר חשוד בטרור OR הקצנה OR תעמולת טרור)', "category": "Terrorist Financing"},
        ],
        "sites": ["ynet.co.il", "haaretz.co.il"],
        "site_terms": '(טרור OR מחבל OR פיגוע OR דאעש)',
    },
]


def multilingual_query_count():
    return sum(
        len(profile.get("queries", []))
        + len(profile.get("sites", []))
        for profile in MULTILINGUAL_PROFILES
    )


SOURCE_PRIORITY = {
    "U.S. Department of Justice": 130,
    "US Department of Justice": 130,
    "Department of Justice": 130,
    "Justice Department": 130,
    "U.S. Department of the Treasury": 128,
    "US Department of the Treasury": 128,
    "Department of the Treasury": 128,
    "U.S. Treasury": 128,
    "Counter Terrorism Policing": 127,
    "Europol": 126,
    "GOV.UK": 124,
    "UK Government": 124,
    "Home Office": 124,
    "INTERPOL": 122,
    "ACLED": 118,
    "Reuters": 105,
    "Associated Press": 100,
    "AP News": 100,
    "BBC": 96,
    "BBC News": 96,
    "France 24": 90,
    "France24": 90,
    "Deutsche Welle": 90,
    "DW": 90,
    "Al Jazeera": 90,
    "Al Jazeera English": 90,
    "CNN": 86,
    "RFI": 86,
    "Radio France Internationale": 86,
    "Radio Free Europe": 82,
    "Radio Free Europe/Radio Liberty": 82,
    "RFE/RL": 82,
    "Voice of America": 80,
    "VOA": 80,
    "i24NEWS": 80,
    "i24 News": 80,
    "Sky News": 80,
    "The Guardian": 78,
    "Euronews": 76,
    "RT": 55,
    "Russia Today": 55,
    "ABC News": 66,
    "NBC News": 65,
    "CBS News": 65,
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

    "Maritime Piracy": {
        "maritime piracy","piracy","pirate","pirates","armed robbery at sea",
        "ship","ships","vessel","vessels","tanker","crew","seafarer",
        "maritime","hijack","hijacked","boarded",
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
    "Maritime Piracy": {
        "attack","attacked","hijack","hijacked","boarded","seized",
        "kidnapped","abducted","robbed","hostage","rescued","intercepted",
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


# ============================================================
# MERGED DIGITAL TAXONOMY
# ============================================================

DIGITAL_CATEGORY = "Online / Cyber / AI"
LEGACY_DIGITAL_CATEGORIES = (
    "Online Radicalization / Cyberterrorism",
    "Disinformation / Emerging Technologies / AI",
)


def _merge_taxonomy_values(first, second):
    if isinstance(first, list) and isinstance(second, list):
        return list(dict.fromkeys(first + second))

    if isinstance(first, set) and isinstance(second, set):
        return set(first) | set(second)

    if isinstance(first, str) and isinstance(second, str):
        return f"{first} {second}"

    if isinstance(first, dict) and isinstance(second, dict):
        merged = dict(first)
        merged.update(second)
        return merged

    return second if second is not None else first


def _merge_digital_taxonomy(mapping):
    first = mapping.get(LEGACY_DIGITAL_CATEGORIES[0])
    second = mapping.get(LEGACY_DIGITAL_CATEGORIES[1])

    if first is None and second is None:
        return

    if first is None:
        merged = second
    elif second is None:
        merged = first
    else:
        merged = _merge_taxonomy_values(first, second)

    mapping[DIGITAL_CATEGORY] = merged

    for legacy in LEGACY_DIGITAL_CATEGORIES:
        mapping.pop(legacy, None)


for _taxonomy_mapping in (
    CATEGORIES,
    CORE_SEARCH_QUERIES,
    OFFICIAL_SOURCE_QUERIES,
    TARGETED_MEDIA_CATEGORY_TERMS,
    CATEGORY_RELEVANCE,
    ACTION_TERMS,
):
    _merge_digital_taxonomy(_taxonomy_mapping)


def normalize_category_name(category):
    value = clean_text(category)

    if value in LEGACY_DIGITAL_CATEGORIES:
        return DIGITAL_CATEGORY

    return value


def normalize_categories(categories):
    normalized = []

    for category in categories or []:
        category = normalize_category_name(category)

        if (
            category
            and
            category not in normalized
        ):
            normalized.append(category)

    return normalized


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

    # Maritime piracy is explicitly in scope even when no terrorism nexus is
    # reported. Require strong maritime-piracy + action evidence instead.
    if category == "Maritime Piracy":
        category_terms = CATEGORY_RELEVANCE.get(category, set())
        action_terms = ACTION_TERMS.get(category, set())
        category_hits = [
            term for term in category_terms if contains_term(combined, term)
        ]
        action_hits = [
            term for term in action_terms if contains_term(combined, term)
        ]
        piracy_anchor = any(
            contains_term(combined, term)
            for term in (
                "maritime piracy", "piracy", "pirate", "pirates",
                "armed robbery at sea"
            )
        )
        maritime_anchor = any(
            contains_term(combined, term)
            for term in (
                "ship", "ships", "vessel", "vessels", "tanker",
                "crew", "seafarer", "maritime", "at sea"
            )
        )
        if not (piracy_anchor and maritime_anchor and action_hits):
            return False
        if has_non_event_pattern(combined):
            return False
        return True

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



def classify_article_categories(
    title,
    summary,
):
    """
    Classify one broad-source result locally instead of asking Google News
    once per source x category.

    The full existing relevance rules remain authoritative.
    """
    categories = []

    for category in CATEGORIES.keys():
        if is_relevant_article(
            category,
            title,
            summary,
        ):
            categories.append(
                category
            )

    return categories


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
    language=None,
    country=None,
    edition=None,
):
    query = (
        term
        + f" when:{days}d"
    )

    encoded = quote_plus(query)

    language = language or GOOGLE_LANGUAGE
    country = country or GOOGLE_COUNTRY
    edition = edition or GOOGLE_EDITION

    return (
        f"{GOOGLE_NEWS_BASE}"
        f"?q={encoded}"
        f"&hl={language}"
        f"&gl={country}"
        f"&ceid={edition}"
    )


def request_google_news(
    url,
    label="query",
):
    """
    Execute one Google News request with a short retry policy and a global
    circuit breaker for repeated 429/503 responses.

    This prevents hundreds of pointless retry loops when Google is throttling
    the GitHub Actions runner.
    """
    global SERVER_ERROR_STREAK

    for attempt in range(
        1,
        REQUEST_ATTEMPTS + 1,
    ):
        try:
            response = session.get(
                url,
                timeout=30,
            )

            if response.status_code in {
                429,
                503,
            }:
                QUERY_STATS["throttled"] += 1
                SERVER_ERROR_STREAK += 1

                retry_after = response.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        delay = min(
                            120,
                            max(
                                5,
                                int(
                                    retry_after
                                )
                            )
                        )
                    except Exception:
                        delay = 10
                else:
                    delay = (
                        8
                        +
                        attempt * 5
                        +
                        random.uniform(
                            0,
                            3
                        )
                    )

                print(
                    f"      Google News returned "
                    f"{response.status_code} "
                    f"({label}) — cooldown "
                    f"{delay:.0f}s"
                )

                if (
                    SERVER_ERROR_STREAK
                    >=
                    SERVER_ERROR_STREAK_LIMIT
                ):
                    print(
                        "      Repeated throttling detected — "
                        f"global cooldown "
                        f"{SERVER_ERROR_COOLDOWN_SECONDS}s"
                    )

                    time.sleep(
                        SERVER_ERROR_COOLDOWN_SECONDS
                    )

                    SERVER_ERROR_STREAK = 0

                else:
                    time.sleep(
                        delay
                    )

                continue

            response.raise_for_status()

            SERVER_ERROR_STREAK = 0
            QUERY_STATS["successful"] += 1

            time.sleep(
                REQUEST_PAUSE_SECONDS
                +
                random.uniform(
                    0,
                    0.25
                )
            )

            return response

        except requests.RequestException as error:
            QUERY_STATS["request_errors"] += 1

            print(
                f"      Request attempt "
                f"{attempt}/"
                f"{REQUEST_ATTEMPTS} failed "
                f"({label}): "
                f"{error}"
            )

            if attempt < REQUEST_ATTEMPTS:
                time.sleep(
                    5
                    +
                    random.uniform(
                        0,
                        2
                    )
                )

    QUERY_STATS["failed"] += 1

    return None


def entry_to_event(
    entry,
    categories,
    acquisition_channel=None,
    targeted_source=None,
    targeted_source_kind=None,
    original_language_hint="en",
    collection_language_name="English",
    collection_locale=None,
):
    article_url = entry.get(
        "link"
    )

    if not article_url:
        return None

    source = get_source(
        entry
    )

    title = remove_source_suffix(
        entry.get(
            "title",
            "",
        ),
        source,
    )

    if not title:
        return None

    summary = clean_text(
        entry.get(
            "summary",
            "",
        )
    )

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

    primary_category = (
        categories[0]
        if categories
        else None
    )

    if not primary_category:
        return None

    event = {
        "id":
            create_event_id(
                title,
                published,
            ),
        "category":
            primary_category,
        "categories":
            categories,
        "title":
            title,
        "summary":
            summary,
        "original_title":
            title,
        "original_summary":
            summary,
        "original_language":
            original_language_hint or "en",
        "collection_language":
            original_language_hint or "en",
        "collection_language_name":
            collection_language_name or "English",
        "collection_locale":
            collection_locale,
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
    }

    if acquisition_channel:
        event[
            "acquisition_channel"
        ] = acquisition_channel

    if targeted_source:
        event[
            "targeted_source"
        ] = targeted_source

    if targeted_source_kind:
        event[
            "targeted_source_kind"
        ] = targeted_source_kind

    return event


def collect_query(
    category,
    term,
    days,
):
    url = build_google_url(
        term,
        days,
    )

    response = request_google_news(
        url,
        label=category,
    )

    if response is None:
        return []

    feed = feedparser.parse(
        response.content
    )

    results = []
    rejected = 0

    for entry in feed.entries:
        source = get_source(
            entry
        )

        title = remove_source_suffix(
            entry.get(
                "title",
                "",
            ),
            source,
        )

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

        event = entry_to_event(
            entry,
            [category],
        )

        if event:
            results.append(
                event
            )

    if rejected:
        print(
            f"      rejected → "
            f"{rejected}"
        )

    return results


def collect_broad_query(
    term,
    days,
    label,
    acquisition_channel,
    targeted_source=None,
    targeted_source_kind=None,
):
    """
    One broad source query can yield articles for any of the merged CT categories.
    Classification is performed locally, which is the key reduction in
    Google News request volume.
    """
    url = build_google_url(
        term,
        days,
    )

    response = request_google_news(
        url,
        label=label,
    )

    if response is None:
        return []

    feed = feedparser.parse(
        response.content
    )

    results = []
    rejected = 0

    for entry in feed.entries:
        source = get_source(
            entry
        )

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

        categories = classify_article_categories(
            title,
            summary,
        )

        if not categories:
            rejected += 1
            continue

        event = entry_to_event(
            entry,
            categories,
            acquisition_channel=
                acquisition_channel,
            targeted_source=
                targeted_source,
            targeted_source_kind=
                targeted_source_kind,
        )

        if event:
            results.append(
                event
            )

    if rejected:
        print(
            f"      locally rejected → "
            f"{rejected}"
        )

    return results



def collect_multilingual_query(
    term,
    days,
    profile,
    category_hint,
    targeted_source=None,
):
    """
    Collect a local-language Google News query without the English lexical
    relevance filter. Query specificity gives us candidates; Gemini later
    decides semantic CT relevance and translates retained events to English.
    """

    url = build_google_url(
        term,
        days,
        language=profile["hl"],
        country=profile["gl"],
        edition=profile["ceid"],
    )

    label = (
        f"{profile['name']}"
        + (
            f" / {targeted_source}"
            if targeted_source
            else ""
        )
    )

    response = request_google_news(
        url,
        label=label,
    )

    if response is None:
        return []

    feed = feedparser.parse(
        response.content
    )

    results = []

    for entry in feed.entries:
        event = entry_to_event(
            entry,
            [category_hint],
            acquisition_channel=(
                "multilingual_targeted_source"
                if targeted_source
                else "multilingual_discovery"
            ),
            targeted_source=targeted_source,
            targeted_source_kind=(
                "local_language_media"
                if targeted_source
                else None
            ),
            original_language_hint=profile["code"],
            collection_language_name=profile["name"],
            collection_locale=profile["ceid"],
        )

        if event:
            results.append(event)

    return results


def collect_multilingual(days):
    records = []
    language_counts = Counter()

    print()
    print("=" * 70)
    print("MULTILINGUAL CT DISCOVERY")
    print("=" * 70)

    for number, profile in enumerate(
        MULTILINGUAL_PROFILES,
        start=1,
    ):
        print()
        print(
            f"[LANGUAGE {number}/{len(MULTILINGUAL_PROFILES)}] "
            f"{profile['name']} ({profile['code']})"
        )

        subtotal = 0

        for query_number, query in enumerate(
            profile.get("queries", []),
            start=1,
        ):
            print(
                f"   Discovery query {query_number}/"
                f"{len(profile.get('queries', []))}"
            )

            results = collect_multilingual_query(
                query["term"],
                days,
                profile,
                query["category"],
            )

            records.extend(results)
            subtotal += len(results)

            print(
                f"      candidates → {len(results)}"
            )

        for site in profile.get("sites", []):
            query = (
                "site:"
                + site
                + " "
                + profile["site_terms"]
            )

            print(
                f"   Targeted local source: {site}"
            )

            results = collect_multilingual_query(
                query,
                days,
                profile,
                "Attacks",
                targeted_source=site,
            )

            records.extend(results)
            subtotal += len(results)

            print(
                f"      candidates → {len(results)}"
            )

        language_counts[profile["code"]] += subtotal

        print(
            f"   LANGUAGE TOTAL: {subtotal}"
        )

    print()
    print(
        "Multilingual candidate records: "
        f"{len(records)}"
    )

    if language_counts:
        print(
            "By collection language: "
            + ", ".join(
                f"{code}={count}"
                for code, count
                in sorted(language_counts.items())
            )
        )

    return records


def _collect_all_once(days):
    print()
    print("=" * 70)
    print("INTERPOL CT Intelligence Map")
    print("OSINT Collector V9 — multilingual Gemini intelligence")
    print("=" * 70)
    print(f"Window: {days} days")
    print("Collection languages: English + French + Arabic + German + Spanish + Italian + Turkish + Russian + Urdu + Persian + Hebrew")
    print("Relevance filter: strict event mode")
    print(
        "Acquisition strategy: compact discovery + local source classification"
    )

    records = []

    # ========================================================
    # 1. COMPACT GENERAL DISCOVERY
    # ========================================================

    print()
    print("=" * 70)
    print("CORE CT DISCOVERY")
    print("=" * 70)

    for category_number, (
        category,
        terms,
    ) in enumerate(
        CORE_SEARCH_QUERIES.items(),
        start=1,
    ):
        print()
        print(
            f"[{category_number}/"
            f"{len(CORE_SEARCH_QUERIES)}] "
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
                f"{len(terms)}"
            )

            results = collect_query(
                category,
                term,
                days,
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

        print(
            f"   CATEGORY TOTAL: "
            f"{subtotal}"
        )

    # ========================================================
    # 2. OFFICIAL / PRIMARY SOURCES
    #    6 broad queries instead of 29 category-specific ones.
    # ========================================================

    print()
    print("=" * 70)
    print("OFFICIAL / PRIMARY CT SOURCES")
    print("=" * 70)

    official_total = 0

    for source in OFFICIAL_BROAD_QUERIES:
        print()
        print(
            f"[OFFICIAL] "
            f"{source['name']}"
        )

        results = collect_broad_query(
            source[
                "query"
            ],
            days,
            label=
                source[
                    "name"
                ],
            acquisition_channel=
                "official_primary_source_query",
            targeted_source=
                source[
                    "name"
                ],
            targeted_source_kind=
                "official_primary_source",
        )

        records.extend(
            results
        )

        official_total += len(
            results
        )

        print(
            f"      accepted → "
            f"{len(results)}"
        )

    # ========================================================
    # 3. TARGETED INTERNATIONAL / SPECIALIST SOURCES
    #    One query per source; selected high-volume sources get
    #    a second complementary query.
    # ========================================================

    print()
    print("=" * 70)
    print("TARGETED INTERNATIONAL / SPECIALIST SOURCES")
    print("=" * 70)

    targeted_total = 0

    for source_number, source in enumerate(
        TARGETED_SOURCE_SITES,
        start=1,
    ):
        print()
        print(
            f"[SOURCE "
            f"{source_number}/"
            f"{len(TARGETED_SOURCE_SITES)}] "
            f"{source['name']}"
        )

        source_total = 0
        source_queries = targeted_source_queries(
            source
        )

        for query_number, query in enumerate(
            source_queries,
            start=1,
        ):
            print(
                f"   Source query "
                f"{query_number}/"
                f"{len(source_queries)}"
            )

            results = collect_broad_query(
                query,
                days,
                label=
                    source[
                        "name"
                    ],
                acquisition_channel=
                    "targeted_source_query",
                targeted_source=
                    source[
                        "name"
                    ],
                targeted_source_kind=
                    source[
                        "kind"
                    ],
            )

            records.extend(
                results
            )

            source_total += len(
                results
            )

            targeted_total += len(
                results
            )

            print(
                f"      accepted → "
                f"{len(results)}"
            )

        print(
            f"   SOURCE TOTAL: "
            f"{source_total}"
        )

    # ========================================================
    # 4. MULTILINGUAL DISCOVERY
    # ========================================================

    multilingual_records = collect_multilingual(
        days
    )

    records.extend(
        multilingual_records
    )

    multilingual_total = len(
        multilingual_records
    )

    print()
    print("=" * 70)
    print("ACQUISITION SUMMARY")
    print("=" * 70)
    print(
        f"Raw accepted records: "
        f"{len(records)}"
    )
    print(
        f"Official-source records: "
        f"{official_total}"
    )
    print(
        f"Targeted-source records: "
        f"{targeted_total}"
    )
    print(
        f"Multilingual records: "
        f"{multilingual_total}"
    )
    print(
        f"Successful Google News requests: "
        f"{QUERY_STATS['successful']}"
    )
    print(
        f"Failed Google News requests: "
        f"{QUERY_STATS['failed']}"
    )
    print(
        f"Throttle responses (429/503): "
        f"{QUERY_STATS['throttled']}"
    )

    total_requests = (
        QUERY_STATS[
            "successful"
        ]
        +
        QUERY_STATS[
            "failed"
        ]
    )

    # Never silently build a backfill from a severely throttled sample.
    # A failed workflow leaves the previous events.json untouched.
    if (
        total_requests >= 10
        and
        QUERY_STATS[
            "failed"
        ]
        /
        total_requests
        >
        0.20
    ):
        raise RuntimeError(
            "Too many Google News queries failed "
            f"({QUERY_STATS['failed']}/{total_requests}). "
            "Database not replaced to avoid an incomplete backfill."
        )

    return records



# ============================================================
# GEMINI AI EVENT SELECTION ENGINE
# ============================================================

AI_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string"
                    },
                    "relevance_score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "is_current_ct_event": {
                        "type": "boolean"
                    },
                    "categories": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "Terrorist Financing",
                                "Weapons",
                                "Maritime Piracy",
                                "CBRN",
                                "Online / Cyber / AI",
                                "Attacks",
                                "Arrests",
                                "Legal / Judicial",
                            ],
                        },
                    },
                    "original_language": {
                        "type": "string"
                    },
                    "english_title": {
                        "type": "string"
                    },
                    "english_summary": {
                        "type": "string"
                    },
                    "canonical_event": {
                        "type": "string"
                    },
                    "reason": {
                        "type": "string"
                    },
                },
                "required": [
                    "event_id",
                    "relevance_score",
                    "is_current_ct_event",
                    "categories",
                    "original_language",
                    "english_title",
                    "english_summary",
                    "canonical_event",
                    "reason",
                ],
            },
        },
    },
    "required": [
        "results"
    ],
}


AI_SELECTION_INSTRUCTIONS = """
You are the final editorial relevance filter for an operational
counter-terrorism situational-awareness map.

For EVERY candidate event, judge whether it is genuinely useful as a CURRENT
counter-terrorism intelligence event, OR a current maritime-piracy / armed-robbery-at-sea event.

Maritime Piracy is explicitly in scope even when no terrorist nexus is stated.
Exclude ordinary maritime accidents, smuggling, fishing disputes and digital/media
piracy unless the event is actual piracy, pirate attack, vessel hijacking/boarding,
crew kidnapping or armed robbery at sea.

Score relevance from 0 to 100.

KEEPING POLICY:
- The software keeps every event with score >= 50.
- Therefore do NOT be excessively strict.
- A plausible, operationally useful CT event should normally score at least 50.
- Strong, specific current CT events should score 75-100.

HIGH-SCORING EXAMPLES:
- terrorist attack, attempted attack, disrupted plot;
- arrest, raid, wanted terrorist, terrorist cell;
- prosecution, charge, conviction, sentencing or extradition for terrorism;
- terrorist financing, sanctions, asset seizure, crypto/hawala financing;
- weapons, explosives, drones or CBRN connected to terrorists;
- terrorist propaganda, recruitment, radicalization, cyberterrorism;
- concrete terrorist use of AI, deepfakes or emerging technology;
- operational developments involving named terrorist organisations.

LOW-SCORING / REJECT EXAMPLES:
- generic political commentary mentioning terrorism only incidentally;
- ordinary crime with no meaningful terrorism nexus;
- historical retrospectives, anniversaries or commemorations;
- generic opinion pieces, book reviews or cultural references;
- broad foreign-policy stories where terrorism is not the event;
- an article that merely mentions 9/11, ISIS, Hamas, Taliban, etc. without a
  current CT event;
- unrelated cybercrime, cryptocurrency, sanctions, weapons or AI stories.

IMPORTANT:
- Do not judge relevance based only on keywords.
- Understand the event semantically.
- A named terrorist group can establish CT relevance even if the literal word
  "terrorism" is absent.
- Conversely, the word "terrorism" alone does not make an article relevant.
- Source reputation does not determine relevance.
- Evaluate the EVENT, not the publisher.
- If an event is genuinely relevant but only moderately informative, prefer a
  score just above 50 rather than rejecting it.

The input can be in English, French, Arabic, German, Spanish, Italian, Turkish,
Russian, Urdu, Persian, Hebrew, or another language. Understand the ORIGINAL
LANGUAGE directly; do not penalize an event because it is not written in English.

For every candidate also return:
- original_language: best ISO 639-1 language code when possible;
- english_title: a faithful, concise English headline describing the event;
- english_summary: a faithful English summary in at most two sentences;
- canonical_event: a short language-neutral-in-meaning English description of
  action + main actor/group + place if stated + essential object/target. This is
  used for cross-language deduplication.

Do not add facts that are absent from the source material. Translation must preserve
uncertainty, allegations and attribution.

Also return the most appropriate category or categories from the supplied
taxonomy. Multiple categories are allowed. Use "Online / Cyber / AI" for online
radicalization/recruitment/propaganda, cyberterrorism or terrorist cyber activity,
AI/deepfakes/disinformation, and other relevant emerging digital technologies.
Use "Maritime Piracy" for actual piracy, pirate attacks, vessel hijacking/boarding,
crew kidnapping or armed robbery at sea.

Keep the reason concise and specific.
"""


class AISelectionIncompleteError(RuntimeError):
    pass


class AISelectionQuotaError(RuntimeError):
    pass


class AISelectionTransientError(RuntimeError):
    pass



def collect_all(*args, **kwargs):
    """Retry the entire collection once if Google News broadly fails."""
    attempts = max(1, GOOGLE_NEWS_GLOBAL_RETRY_ATTEMPTS)
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                print(
                    f"[google-news] Global collection retry "
                    f"{attempt}/{attempts} starting..."
                )
            return _collect_all_once(*args, **kwargs)

        except RuntimeError as exc:
            message = str(exc)
            last_error = exc

            # Retry ONLY the existing broad Google News failure condition.
            if "Too many Google News queries failed" not in message:
                raise

            if attempt >= attempts:
                print(
                    "[google-news] Global retry exhausted. "
                    "Aborting safely; existing database will not be replaced."
                )
                raise

            delay = GOOGLE_NEWS_GLOBAL_RETRY_DELAY_SECONDS
            print(
                f"[google-news] Abnormal Google News failure detected: {message}"
            )
            print(
                f"[google-news] Waiting {delay:.0f}s before retrying "
                "the entire collection wave..."
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error


def selection_compact_text(
    value,
    limit,
):
    value = clean_text(
        value
    )

    if len(
        value
    ) <= limit:
        return value

    return (
        value[
            :limit
        ].rstrip()
        +
        "…"
    )


def selection_payload(
    event,
    index,
):
    event_id = str(
        event.get(
            "id"
        )
        or
        f"candidate-{index}"
    )

    related = []

    for article in (
        event.get(
            "related_articles"
        )
        or
        []
    )[:4]:
        if not isinstance(
            article,
            dict
        ):
            continue

        title = selection_compact_text(
            article.get(
                "title"
            ),
            280,
        )

        source = selection_compact_text(
            article.get(
                "source"
            ),
            100,
        )

        if title:
            related.append(
                {
                    "title":
                        title,
                    "source":
                        source,
                }
            )

    return {
        "event_id":
            event_id,

        "title":
            selection_compact_text(
                event.get(
                    "title"
                ),
                650,
            ),

        "summary":
            selection_compact_text(
                event.get(
                    "summary"
                ),
                1100,
            ),

        "source":
            selection_compact_text(
                event.get(
                    "source"
                ),
                140,
            ),

        "collection_language_hint":
            str(
                event.get(
                    "original_language"
                )
                or
                event.get(
                    "collection_language"
                )
                or
                ""
            ),

        "published":
            str(
                event.get(
                    "published"
                )
                or
                ""
            ),

        "current_categories":
            list(
                event.get(
                    "categories"
                )
                or
                (
                    [
                        event.get(
                            "category"
                        )
                    ]
                    if event.get(
                        "category"
                    )
                    else []
                )
            ),

        "related_articles":
            related,
    }


def selection_fingerprint(
    event
):
    material = {
        "url":
            str(
                event.get(
                    "url"
                )
                or
                ""
            ),

        "title":
            normalize_title(
                event.get(
                    "title"
                )
                or
                ""
            ),

        "summary":
            selection_compact_text(
                event.get(
                    "summary"
                ),
                1000,
            ),
    }

    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def load_selection_cache():
    try:
        with open(
            AI_SELECTION_CACHE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            cache = json.load(
                file
            )

        if (
            cache.get(
                "version"
            )
            !=
            AI_SELECTION_VERSION
        ):
            return {
                "version":
                    AI_SELECTION_VERSION,
                "model":
                    AI_SELECTION_MODEL,
                "threshold":
                    AI_SELECTION_THRESHOLD,
                "items":
                    {},
            }

        if not isinstance(
            cache.get(
                "items"
            ),
            dict
        ):
            cache[
                "items"
            ] = {}

        return cache

    except Exception:
        return {
            "version":
                AI_SELECTION_VERSION,
            "model":
                AI_SELECTION_MODEL,
            "threshold":
                AI_SELECTION_THRESHOLD,
            "items":
                {},
        }


def save_selection_cache(
    cache
):
    cache[
        "version"
    ] = AI_SELECTION_VERSION

    cache[
        "model"
    ] = AI_SELECTION_MODEL

    cache[
        "threshold"
    ] = AI_SELECTION_THRESHOLD

    cache[
        "last_updated"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    with open(
        AI_SELECTION_CACHE_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            cache,
            file,
            ensure_ascii=False,
            indent=2,
        )


def extract_interaction_text(
    payload
):
    status = str(
        payload.get(
            "status",
            ""
        )
        or
        ""
    ).lower()

    if status in {
        "incomplete",
        "budget_exceeded",
    }:
        raise AISelectionIncompleteError(
            f"Gemini interaction status={status}"
        )

    if status in {
        "failed",
        "cancelled",
    }:
        raise RuntimeError(
            "Gemini article-selection interaction "
            f"ended with status {status}: "
            f"{payload.get('error')}"
        )

    texts = []

    for step in payload.get(
        "steps",
        []
    ):
        if not isinstance(
            step,
            dict
        ):
            continue

        if step.get(
            "type"
        ) != "model_output":
            continue

        content = step.get(
            "content",
            []
        )

        if isinstance(
            content,
            dict
        ):
            content = [
                content
            ]

        for part in content:
            if (
                isinstance(
                    part,
                    dict
                )
                and
                part.get(
                    "type"
                )
                ==
                "text"
                and
                part.get(
                    "text"
                )
            ):
                texts.append(
                    part[
                        "text"
                    ]
                )

    output = "".join(
        texts
    ).strip()

    if not output:
        raise AISelectionIncompleteError(
            "Gemini returned no article-selection text."
        )

    return output


def call_ai_selection_batch(
    batch
):
    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. "
            "AI article selection cannot run."
        )

    body = {
        "model":
            AI_SELECTION_MODEL,

        "input":
            (
                "Review every candidate CT event below. "
                "Return exactly one result for every event_id.\n\n"
                +
                json.dumps(
                    {
                        "events":
                            batch
                    },
                    ensure_ascii=False,
                )
            ),

        "system_instruction":
            AI_SELECTION_INSTRUCTIONS,

        "store":
            False,

        "response_format": {
            "type":
                "text",

            "mime_type":
                "application/json",

            "schema":
                AI_SELECTION_SCHEMA,
        },

        "generation_config": {
            "max_output_tokens":
                24000,

            "thinking_level":
                "minimal",
        },
    }

    headers = {
        "x-goog-api-key":
            api_key,

        "Content-Type":
            "application/json",
    }

    for attempt in range(
        1,
        AI_SELECTION_ATTEMPTS + 1,
    ):
        try:
            response = requests.post(
                GEMINI_INTERACTIONS_URL,
                headers=headers,
                json=body,
                timeout=AI_SELECTION_TIMEOUT,
            )

            if response.status_code == 429:
                delay = min(
                    120,
                    15 * attempt,
                )

                print(
                    f"   AI selection quota 429; "
                    f"attempt {attempt}/"
                    f"{AI_SELECTION_ATTEMPTS}; "
                    f"retrying in {delay}s"
                )

                if attempt >= AI_SELECTION_ATTEMPTS:
                    raise AISelectionQuotaError(
                        "Gemini article-selection quota reached."
                    )

                time.sleep(
                    delay
                )

                continue

            if response.status_code in {
                408,
                409,
                500,
                502,
                503,
                504,
            }:
                delay = min(
                    90,
                    12 * attempt,
                )

                print(
                    f"   AI selection temporary HTTP "
                    f"{response.status_code}; "
                    f"retrying in {delay}s"
                )

                if attempt >= AI_SELECTION_ATTEMPTS:
                    raise AISelectionTransientError(
                        "Gemini article-selection service unavailable."
                    )

                time.sleep(
                    delay
                )

                continue

            if response.status_code >= 400:
                raise RuntimeError(
                    "Gemini article-selection API error "
                    f"{response.status_code}: "
                    f"{response.text[:1800]}"
                )

            payload = response.json()

            output_text = extract_interaction_text(
                payload
            )

            try:
                parsed = json.loads(
                    output_text
                )

            except json.JSONDecodeError as error:
                raise AISelectionIncompleteError(
                    "Invalid Gemini article-selection JSON."
                ) from error

            results = parsed.get(
                "results"
            )

            if not isinstance(
                results,
                list
            ):
                raise AISelectionIncompleteError(
                    "Gemini selection result has no results array."
                )

            time.sleep(
                AI_SELECTION_PAUSE_SECONDS
            )

            return results

        except AISelectionIncompleteError:
            raise

        except requests.RequestException as error:
            if attempt >= AI_SELECTION_ATTEMPTS:
                raise AISelectionTransientError(
                    "Gemini article-selection network failure."
                ) from error

            delay = min(
                90,
                10 * attempt,
            )

            print(
                f"   AI selection network error: "
                f"{error}; retrying in {delay}s"
            )

            time.sleep(
                delay
            )

    raise AISelectionTransientError(
        "Gemini article-selection request failed."
    )


def process_ai_selection_batch(
    batch
):
    try:
        results = call_ai_selection_batch(
            batch
        )

        returned = {
            str(
                result.get(
                    "event_id"
                )
            )
            for result
            in results
            if result.get(
                "event_id"
            )
        }

        expected = {
            str(
                item.get(
                    "event_id"
                )
            )
            for item
            in batch
        }

        if returned != expected:
            raise AISelectionIncompleteError(
                "Gemini omitted one or more candidate events."
            )

        return results

    except AISelectionIncompleteError:
        if len(
            batch
        ) <= 1:
            raise

        midpoint = max(
            1,
            len(
                batch
            )
            //
            2
        )

        left = batch[
            :midpoint
        ]

        right = batch[
            midpoint:
        ]

        print(
            f"   AI selection incomplete for "
            f"{len(batch)} events; splitting into "
            f"{len(left)} + {len(right)}."
        )

        return (
            process_ai_selection_batch(
                left
            )
            +
            process_ai_selection_batch(
                right
            )
        )


def apply_ai_selection(
    event,
    result,
):
    try:
        score = int(
            result.get(
                "relevance_score",
                0,
            )
        )
    except Exception:
        score = 0

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    categories = normalize_categories(
        result.get(
            "categories"
        )
        or
        []
    )

    categories = [
        category
        for category
        in categories
        if category
        in CATEGORIES
    ]

    if (
        score
        >=
        AI_SELECTION_THRESHOLD

        and

        not categories
    ):
        categories = normalize_categories(
            event.get(
                "categories"
            )
            or
            (
                [
                    event.get(
                        "category"
                    )
                ]
                if event.get(
                    "category"
                )
                else []
            )
        )

    event[
        "ai_selection_complete"
    ] = True

    event[
        "ai_selection_version"
    ] = AI_SELECTION_VERSION

    event[
        "ai_selection_model"
    ] = AI_SELECTION_MODEL

    event[
        "ai_relevance_score"
    ] = score

    event[
        "ai_relevance_reason"
    ] = clean_text(
        result.get(
            "reason"
        )
        or
        ""
    )

    event[
        "ai_current_ct_event"
    ] = bool(
        result.get(
            "is_current_ct_event"
        )
    )

    event[
        "ai_selected"
    ] = (
        score
        >=
        AI_SELECTION_THRESHOLD
    )

    if categories:
        event[
            "categories"
        ] = categories

        event[
            "category"
        ] = categories[
            0
        ]

    # Preserve original-language material before normalizing the map fields.
    if not event.get(
        "original_title"
    ):
        event[
            "original_title"
        ] = event.get(
            "title",
            "",
        )

    if not event.get(
        "original_summary"
    ):
        event[
            "original_summary"
        ] = event.get(
            "summary",
            "",
        )

    detected_language = clean_text(
        result.get(
            "original_language"
        )
        or
        event.get(
            "original_language"
        )
        or
        "en"
    ).lower()

    event[
        "original_language"
    ] = detected_language

    english_title = clean_text(
        result.get(
            "english_title"
        )
        or
        ""
    )

    english_summary = clean_text(
        result.get(
            "english_summary"
        )
        or
        ""
    )

    canonical_event = clean_text(
        result.get(
            "canonical_event"
        )
        or
        ""
    )

    event[
        "translated_to_english"
    ] = (
        detected_language
        not in {
            "en",
            "eng",
            "english",
        }
    )

    if english_title:
        event[
            "title"
        ] = english_title

    if english_summary:
        event[
            "summary"
        ] = english_summary

    event[
        "ai_canonical_event"
    ] = canonical_event

    # Give the existing smart deduplicator an additional normalized English
    # semantic variant without replacing the visible English headline.
    if canonical_event:
        variants = event.get(
            "title_variants"
        )

        if not isinstance(
            variants,
            list,
        ):
            variants = []

        if canonical_event not in variants:
            variants.append(
                canonical_event
            )

        event[
            "title_variants"
        ] = variants

    return (
        score
        >=
        AI_SELECTION_THRESHOLD
    )


def ai_select_events(
    events
):
    if not AI_SELECTION_ENABLED:
        return events

    print()
    print("=" * 70)
    print("GEMINI AI ARTICLE SELECTION")
    print("=" * 70)
    print(
        f"Candidate event clusters: "
        f"{len(events)}"
    )
    print(
        f"Model: {AI_SELECTION_MODEL}"
    )
    print(
        f"Keep threshold: "
        f"{AI_SELECTION_THRESHOLD}/100"
    )

    cache = load_selection_cache()

    event_by_id = {}
    fingerprint_by_id = {}
    pending = []
    decisions = {}

    cached_count = 0

    for index, event in enumerate(
        events
    ):
        payload = selection_payload(
            event,
            index,
        )

        event_id = payload[
            "event_id"
        ]

        if event_id in event_by_id:
            event_id = (
                event_id
                +
                "-"
                +
                str(
                    index
                )
            )

            payload[
                "event_id"
            ] = event_id

        fingerprint = selection_fingerprint(
            event
        )

        event_by_id[
            event_id
        ] = event

        fingerprint_by_id[
            event_id
        ] = fingerprint

        cached = (
            cache.get(
                "items",
                {}
            ).get(
                fingerprint
            )
        )

        if (
            isinstance(
                cached,
                dict
            )
            and
            cached.get(
                "version"
            )
            ==
            AI_SELECTION_VERSION
        ):
            decisions[
                event_id
            ] = cached[
                "result"
            ]

            cached_count += 1

        else:
            pending.append(
                payload
            )

    print(
        f"Cached AI decisions: "
        f"{cached_count}"
    )
    print(
        f"Need AI review: "
        f"{len(pending)}"
    )

    total_batches = (
        (
            len(
                pending
            )
            +
            AI_SELECTION_BATCH_SIZE
            -
            1
        )
        //
        AI_SELECTION_BATCH_SIZE
    )

    for start in range(
        0,
        len(
            pending
        ),
        AI_SELECTION_BATCH_SIZE,
    ):
        batch_number = (
            start
            //
            AI_SELECTION_BATCH_SIZE
            +
            1
        )

        batch = pending[
            start:
            start + AI_SELECTION_BATCH_SIZE
        ]

        print(
            f"AI selection batch "
            f"{batch_number}/{total_batches} "
            f"— {len(batch)} events"
        )

        try:
            results = process_ai_selection_batch(
                batch
            )

        except (
            AISelectionQuotaError,
            AISelectionTransientError,
            AISelectionIncompleteError,
        ) as error:
            save_selection_cache(
                cache
            )

            print()
            print(
                "AI article selection could not finish safely."
            )
            print(
                f"Reason: {error}"
            )
            print(
                "The current events.json will NOT be replaced."
            )
            print(
                "The AI selection cache has been saved so the next "
                "workflow run can resume."
            )

            return None

        for result in results:
            event_id = str(
                result.get(
                    "event_id"
                )
                or
                ""
            )

            if event_id not in event_by_id:
                continue

            decisions[
                event_id
            ] = result

            fingerprint = fingerprint_by_id[
                event_id
            ]

            cache[
                "items"
            ][
                fingerprint
            ] = {
                "version":
                    AI_SELECTION_VERSION,

                "reviewed_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "result":
                    result,
            }

        save_selection_cache(
            cache
        )

        print(
            f"   AI selection checkpoint saved."
        )

    selected = []
    rejected = []

    for event_id, event in event_by_id.items():
        result = decisions.get(
            event_id
        )

        if result is None:
            print(
                f"Missing AI selection decision for "
                f"{event_id}; aborting safely."
            )

            save_selection_cache(
                cache
            )

            return None

        keep = apply_ai_selection(
            event,
            result,
        )

        if keep:
            selected.append(
                event
            )
        else:
            rejected.append(
                event
            )

    score_bands = Counter()

    for event in events:
        score = event.get(
            "ai_relevance_score",
            0,
        )

        if score >= 80:
            score_bands[
                "80-100"
            ] += 1
        elif score >= 60:
            score_bands[
                "60-79"
            ] += 1
        elif score >= 50:
            score_bands[
                "50-59"
            ] += 1
        else:
            score_bands[
                "0-49"
            ] += 1

    print()
    print(
        f"AI KEPT:     "
        f"{len(selected)}"
    )
    print(
        f"AI REJECTED: "
        f"{len(rejected)}"
    )
    print(
        "Score bands: "
        +
        ", ".join(
            f"{band}={count}"
            for band, count
            in score_bands.items()
        )
    )

    if rejected:
        print()
        print(
            "Rejected examples:"
        )

        for event in sorted(
            rejected,
            key=lambda item:
                item.get(
                    "ai_relevance_score",
                    0,
                )
        )[:10]:
            print(
                f"   "
                f"{event.get('ai_relevance_score', 0):>3}/100 "
                f"— "
                f"{selection_compact_text(event.get('title'), 110)}"
            )

    save_selection_cache(
        cache
    )

    return selected


# ============================================================
# INTELLIGENT EVENT-LEVEL DEDUPLICATION V7
#
# The collector receives many different headlines about the same
# real-world event.  Deduplication therefore uses more than title
# similarity:
#
# - canonical URL
# - normalized title similarity
# - meaningful token overlap
# - title containment
# - named entities / personalities
# - terrorist organisation aliases
# - CT action families
# - explicit country clues
# - numbers / casualty counts / amounts
# - summary overlap
# - publication-time proximity
# - previously merged headline variants
#
# It deliberately avoids merging two events merely because they
# involve the same group or the same country.
# ============================================================

MAX_DEDUP_WINDOW_DAYS = 7
MAX_RELATED_ARTICLES = 24


DEDUP_GENERIC_WORDS = {
    "terror",
    "terrorism",
    "terrorist",
    "terrorists",
    "extremist",
    "extremists",
    "extremism",
    "militant",
    "militants",
    "jihadist",
    "jihadists",
    "security",
    "official",
    "officials",
    "authorities",
    "government",
    "police",
    "report",
    "reports",
    "reported",
    "news",
    "latest",
    "breaking",
    "update",
    "updates",
    "case",
    "cases",
    "suspect",
    "suspects",
}


ACTION_FAMILIES = {
    "attack": {
        "attack", "attacks", "attacked", "assault", "ambush",
        "bomb", "bombing", "blast", "explosion", "shooting",
        "shot", "stabbing", "stabbed", "ramming", "rocket",
        "drone attack", "suicide bomber", "suicide bombing",
        "killed", "wounded",
    },
    "arrest": {
        "arrest", "arrests", "arrested", "detained", "detention",
        "captured", "raid", "raided", "custody",
    },
    "legal": {
        "charged", "charges", "trial", "court", "convicted",
        "conviction", "sentenced", "sentence", "indicted",
        "indictment", "guilty", "prosecution", "appeal",
    },
    "finance": {
        "financing", "funding", "fundraising", "donation",
        "donations", "assets frozen", "assets seized",
        "sanctioned", "sanctions", "money laundering",
        "cryptocurrency", "crypto", "hawala",
    },
    "weapons": {
        "weapons", "weapon", "arms", "firearms", "ammunition",
        "explosives", "explosive", "ied", "missile", "rocket",
        "weapons cache", "arms cache", "smuggling", "trafficking",
    },
    "online": {
        "propaganda", "recruitment", "radicalization",
        "radicalisation", "cyberattack", "cyber attack",
        "hacking", "deepfake", "artificial intelligence",
        "generative ai", "social media", "encrypted messaging",
    },
    "cbrn": {
        "chemical", "biological", "radiological", "nuclear",
        "radioactive", "cbrn", "ricin", "sarin", "chlorine",
        "dirty bomb",
    },
}


ACTOR_ALIASES = {
    "islamic_state": {
        "isis", "isil", "daesh", "islamic state",
    },
    "al_qaeda": {
        "al-qaeda", "al qaeda", "alqaeda",
    },
    "al_shabaab": {
        "al-shabaab", "al shabaab",
    },
    "boko_haram": {
        "boko haram",
    },
    "iswap": {
        "iswap", "islamic state west africa province",
    },
    "taliban": {
        "taliban",
    },
    "ttp": {
        "ttp", "tehrik-i-taliban pakistan",
        "tehreek-e-taliban pakistan",
    },
    "hamas": {
        "hamas",
    },
    "hezbollah": {
        "hezbollah", "hizballah", "hizbollah",
    },
    "pij": {
        "palestinian islamic jihad", "islamic jihad",
    },
    "houthis": {
        "houthis", "houthi", "ansar allah",
    },
    "lashkar_e_taiba": {
        "lashkar-e-taiba", "lashkar e taiba", "let",
    },
    "jaish_e_mohammed": {
        "jaish-e-mohammed", "jaish e mohammed", "jem",
    },
}


COUNTRY_CANONICAL = {
    "united states": {
        "united states", "u.s.", "u.s", "usa", "america", "american",
    },
    "united kingdom": {
        "united kingdom", "u.k.", "u.k", "uk", "britain", "british",
    },
    "afghanistan": {
        "afghanistan", "afghan",
    },
    "pakistan": {
        "pakistan", "pakistani",
    },
    "india": {
        "india", "indian",
    },
    "israel": {
        "israel", "israeli",
    },
    "palestinian territory": {
        "palestine", "palestinian", "gaza", "west bank",
    },
    "lebanon": {
        "lebanon", "lebanese",
    },
    "iraq": {
        "iraq", "iraqi",
    },
    "syria": {
        "syria", "syrian",
    },
    "iran": {
        "iran", "iranian",
    },
    "turkiye": {
        "turkey", "turkiye", "türkiye", "turkish",
    },
    "russia": {
        "russia", "russian",
    },
    "ukraine": {
        "ukraine", "ukrainian",
    },
    "somalia": {
        "somalia", "somali",
    },
    "kenya": {
        "kenya", "kenyan",
    },
    "nigeria": {
        "nigeria", "nigerian",
    },
    "niger": {
        "niger", "nigerien",
    },
    "mali": {
        "mali", "malian",
    },
    "burkina faso": {
        "burkina faso", "burkinabe", "burkinabè",
    },
    "mozambique": {
        "mozambique", "mozambican",
    },
    "egypt": {
        "egypt", "egyptian",
    },
    "france": {
        "france", "french",
    },
    "germany": {
        "germany", "german",
    },
    "belgium": {
        "belgium", "belgian",
    },
    "canada": {
        "canada", "canadian",
    },
    "australia": {
        "australia", "australian",
    },
    "philippines": {
        "philippines", "philippine", "filipino",
    },
    "malaysia": {
        "malaysia", "malaysian",
    },
    "indonesia": {
        "indonesia", "indonesian",
    },
    "tunisia": {
        "tunisia", "tunisian",
    },
    "morocco": {
        "morocco", "moroccan",
    },
    "algeria": {
        "algeria", "algerian",
    },
    "libya": {
        "libya", "libyan",
    },
    "yemen": {
        "yemen", "yemeni",
    },
    "saudi arabia": {
        "saudi arabia", "saudi",
    },
    "united arab emirates": {
        "united arab emirates", "uae", "emirati",
    },
}


def ascii_text(text):
    value = clean_text(text)

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(
            character
        )
    )

    return value


def normalize_event_text(text):
    value = ascii_text(
        text
    ).lower()

    value = re.sub(
        r"https?://\S+",
        " ",
        value,
    )

    value = re.sub(
        r"[^a-z0-9$€£%'\-\s]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def canonical_url(url):
    if not url:
        return ""

    try:
        parts = urlsplit(
            url
        )

        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                "",
                "",
            )
        )

    except Exception:
        return str(url).strip()


def meaningful_tokens(text):
    normalized = normalize_event_text(
        text
    )

    tokens = []

    for token in normalized.split():
        if token in STOPWORDS:
            continue

        if token in DEDUP_GENERIC_WORDS:
            continue

        if len(token) <= 2:
            continue

        tokens.append(
            token
        )

    return set(
        tokens
    )


def jaccard(
    values1,
    values2,
):
    set1 = set(
        values1
    )

    set2 = set(
        values2
    )

    if not set1 or not set2:
        return 0.0

    return (
        len(
            set1 & set2
        )
        /
        len(
            set1 | set2
        )
    )


def containment_similarity(
    values1,
    values2,
):
    set1 = set(
        values1
    )

    set2 = set(
        values2
    )

    if not set1 or not set2:
        return 0.0

    shared = len(
        set1 & set2
    )

    return shared / min(
        len(set1),
        len(set2),
    )


def extract_named_entities(text):
    """
    Lightweight named-entity extraction for headlines.
    Multi-word capitalized names and acronyms are strong dedup clues.
    """

    original = clean_text(
        text
    )

    candidates = re.findall(
        r"\b(?:[A-Z][A-Za-zÀ-ÿ'\-]{2,}|[A-Z]{2,})"
        r"(?:\s+(?:[A-Z][A-Za-zÀ-ÿ'\-]{2,}|[A-Z]{2,})){0,4}\b",
        original,
    )

    entities = set()

    for candidate in candidates:
        normalized = normalize_event_text(
            candidate
        )

        words = normalized.split()

        if not words:
            continue

        if all(
            word in STOPWORDS
            or
            word in DEDUP_GENERIC_WORDS
            for word in words
        ):
            continue

        if (
            len(words) == 1
            and
            len(words[0]) < 4
            and
            not candidate.isupper()
        ):
            continue

        entities.add(
            normalized
        )

    return entities


def extract_actor_families(text):
    normalized = (
        " "
        +
        normalize_event_text(
            text
        )
        +
        " "
    )

    actors = set()

    for canonical, aliases in ACTOR_ALIASES.items():
        for alias in aliases:
            pattern = (
                r"(?<![a-z0-9])"
                +
                re.escape(
                    normalize_event_text(
                        alias
                    )
                )
                +
                r"(?![a-z0-9])"
            )

            if re.search(
                pattern,
                normalized,
            ):
                actors.add(
                    canonical
                )
                break

    return actors


def extract_action_families(text):
    normalized = (
        " "
        +
        normalize_event_text(
            text
        )
        +
        " "
    )

    actions = set()

    for family, terms in ACTION_FAMILIES.items():
        for term in terms:
            normalized_term = normalize_event_text(
                term
            )

            if (
                " "
                +
                normalized_term
                +
                " "
            ) in normalized:
                actions.add(
                    family
                )
                break

            pattern = (
                r"(?<![a-z0-9])"
                +
                re.escape(
                    normalized_term
                )
                +
                r"(?![a-z0-9])"
            )

            if re.search(
                pattern,
                normalized,
            ):
                actions.add(
                    family
                )
                break

    return actions


def extract_country_families(text):
    normalized = (
        " "
        +
        normalize_event_text(
            text
        )
        +
        " "
    )

    found = set()

    for canonical, aliases in COUNTRY_CANONICAL.items():
        for alias in aliases:
            normalized_alias = normalize_event_text(
                alias
            )

            pattern = (
                r"(?<![a-z0-9])"
                +
                re.escape(
                    normalized_alias
                )
                +
                r"(?![a-z0-9])"
            )

            if re.search(
                pattern,
                normalized,
            ):
                found.add(
                    canonical
                )
                break

    return found


def extract_numbers(text):
    normalized = normalize_event_text(
        text
    )

    numbers = set(
        re.findall(
            r"(?:[$€£]\s*)?\b\d+(?:[.,]\d+)?(?:\s*(?:million|billion|thousand|m|bn))?\b",
            normalized,
        )
    )

    # Years are weak evidence and can make unrelated stories look alike.
    return {
        number
        for number in numbers
        if not re.fullmatch(
            r"(?:19|20)\d{2}",
            number.strip(),
        )
    }


@lru_cache(
    maxsize=50000
)
def _event_datetime_cached(
    published
):
    if not published:
        return None

    try:
        dt = datetime.fromisoformat(
            published
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


def event_datetime(event):
    return _event_datetime_cached(
        str(
            event.get(
                "published"
            )
            or
            ""
        )
    )


def event_variants(event):
    variants = [
        {
            "title":
                event.get(
                    "title",
                    "",
                ),
            "summary":
                event.get(
                    "summary",
                    "",
                ),
            "source":
                event.get(
                    "source",
                    "",
                ),
            "url":
                event.get(
                    "url",
                    "",
                ),
            "published":
                event.get(
                    "published",
                ),
        }
    ]

    for title_variant in event.get(
        "title_variants",
        [],
    ):
        if not title_variant:
            continue

        variants.append(
            {
                "title":
                    title_variant,
                "summary":
                    event.get(
                        "summary",
                        "",
                    ),
                "source":
                    event.get(
                        "source",
                        "",
                    ),
                "url":
                    event.get(
                        "url",
                        "",
                    ),
                "published":
                    event.get(
                        "published",
                    ),
            }
        )

    for article in event.get(
        "related_articles",
        [],
    ):
        if not isinstance(
            article,
            dict,
        ):
            continue

        variants.append(
            {
                "title":
                    article.get(
                        "title",
                        "",
                    ),
                "summary":
                    article.get(
                        "summary",
                        "",
                    ),
                "source":
                    article.get(
                        "source",
                        "",
                    ),
                "url":
                    article.get(
                        "url",
                        "",
                    ),
                "published":
                    article.get(
                        "published",
                    ),
            }
        )

    return variants[
        :MAX_RELATED_ARTICLES
    ]


@lru_cache(
    maxsize=100000
)
def _build_profile_cached(
    title,
    summary,
    url,
):
    title = clean_text(
        title
    )

    summary = clean_text(
        summary
    )

    combined = (
        title
        +
        " "
        +
        summary
    )

    normalized_title = normalize_event_text(
        title
    )

    return {
        "normalized_title":
            normalized_title,

        "title_tokens":
            meaningful_tokens(
                title
            ),

        "summary_tokens":
            meaningful_tokens(
                summary
            ),

        "entities":
            extract_named_entities(
                title
            ),

        "actors":
            extract_actor_families(
                combined
            ),

        "actions":
            extract_action_families(
                combined
            ),

        "countries":
            extract_country_families(
                combined
            ),

        "numbers":
            extract_numbers(
                combined
            ),

        "url":
            canonical_url(
                url
            ),
    }


def build_profile(event):
    """
    Profile construction is one of the most expensive parts of event matching.
    The same title/summary variants are compared repeatedly during dedup, so
    cache immutable profiles by their text and URL.
    """

    return _build_profile_cached(
        str(
            event.get(
                "title",
                "",
            )
            or
            ""
        ),
        str(
            event.get(
                "summary",
                "",
            )
            or
            ""
        ),
        str(
            event.get(
                "url",
                "",
            )
            or
            ""
        ),
    )


def profile_pair_score(
    event1,
    event2,
):
    profile1 = build_profile(
        event1
    )

    profile2 = build_profile(
        event2
    )

    if (
        profile1[
            "url"
        ]
        and
        profile1[
            "url"
        ]
        ==
        profile2[
            "url"
        ]
    ):
        return (
            True,
            1.0,
            "same_url",
        )

    title1 = profile1[
        "normalized_title"
    ]

    title2 = profile2[
        "normalized_title"
    ]

    if not title1 or not title2:
        return (
            False,
            0.0,
            "missing_title",
        )

    if title1 == title2:
        return (
            True,
            0.99,
            "same_normalized_title",
        )

    dt1 = event_datetime(
        event1
    )

    dt2 = event_datetime(
        event2
    )

    day_gap = None

    if dt1 and dt2:
        day_gap = abs(
            (
                dt1
                -
                dt2
            ).total_seconds()
        ) / 86400.0

        if day_gap > MAX_DEDUP_WINDOW_DAYS:
            return (
                False,
                0.0,
                "outside_time_window",
            )

    sequence = SequenceMatcher(
        None,
        title1,
        title2,
    ).ratio()

    title_jaccard = jaccard(
        profile1[
            "title_tokens"
        ],
        profile2[
            "title_tokens"
        ],
    )

    title_containment = containment_similarity(
        profile1[
            "title_tokens"
        ],
        profile2[
            "title_tokens"
        ],
    )

    lexical = max(
        sequence,
        title_jaccard,
        title_containment,
    )

    summary_overlap = jaccard(
        profile1[
            "summary_tokens"
        ],
        profile2[
            "summary_tokens"
        ],
    )

    entity_overlap = containment_similarity(
        profile1[
            "entities"
        ],
        profile2[
            "entities"
        ],
    )

    actor_overlap = containment_similarity(
        profile1[
            "actors"
        ],
        profile2[
            "actors"
        ],
    )

    action_overlap = containment_similarity(
        profile1[
            "actions"
        ],
        profile2[
            "actions"
        ],
    )

    country_overlap = containment_similarity(
        profile1[
            "countries"
        ],
        profile2[
            "countries"
        ],
    )

    number_overlap = containment_similarity(
        profile1[
            "numbers"
        ],
        profile2[
            "numbers"
        ],
    )

    shared_title_tokens = len(
        profile1[
            "title_tokens"
        ]
        &
        profile2[
            "title_tokens"
        ]
    )

    # Two articles that clearly concern different countries should
    # not be merged merely because the same organisation is involved.
    country_conflict = (
        bool(
            profile1[
                "countries"
            ]
        )
        and
        bool(
            profile2[
                "countries"
            ]
        )
        and
        not (
            profile1[
                "countries"
            ]
            &
            profile2[
                "countries"
            ]
        )
    )

    if country_conflict:
        return (
            False,
            lexical,
            "country_conflict",
        )

    weighted = (
        lexical
        *
        0.42
        +
        summary_overlap
        *
        0.12
        +
        entity_overlap
        *
        0.16
        +
        actor_overlap
        *
        0.10
        +
        action_overlap
        *
        0.08
        +
        country_overlap
        *
        0.07
        +
        number_overlap
        *
        0.05
    )

    if day_gap is not None:
        if day_gap <= 1.0:
            weighted += 0.06

        elif day_gap <= 2.0:
            weighted += 0.03

        elif day_gap >= 5.0:
            weighted -= 0.04

    strong_anchor = (
        entity_overlap >= 0.50
        or
        actor_overlap >= 1.0
        or
        country_overlap >= 1.0
    )

    same_action_context = (
        action_overlap >= 1.0
        or
        not profile1[
            "actions"
        ]
        or
        not profile2[
            "actions"
        ]
    )

    # Very similar headline: usually the same wire story or rewrite.
    if lexical >= 0.86:
        return (
            True,
            max(
                weighted,
                lexical,
            ),
            "very_high_title_similarity",
        )

    # Strong lexical match + meaningful shared words + contextual anchor.
    if (
        lexical >= 0.70
        and
        shared_title_tokens >= 4
        and
        strong_anchor
    ):
        return (
            True,
            max(
                weighted,
                lexical,
            ),
            "title_plus_anchor",
        )

    # Strong CT signature even when editors radically rewrite the title.
    # Same actor + same country + same action, with at least two shared
    # meaningful headline tokens, is a strong indication of one event.
    if (
        actor_overlap >= 1.0
        and
        country_overlap >= 1.0
        and
        action_overlap >= 1.0
        and
        shared_title_tokens >= 2
        and
        lexical >= 0.35
        and
        (
            day_gap is None
            or
            day_gap <= 3.0
        )
        and
        weighted >= 0.45
    ):
        return (
            True,
            weighted,
            "actor_country_action_signature",
        )

    # Paraphrased headline: same entities/actor, same CT action and
    # compatible geography within a short time window.
    if (
        lexical >= 0.44
        and
        strong_anchor
        and
        same_action_context
        and
        (
            actor_overlap >= 1.0
            or
            country_overlap >= 1.0
            or
            (
                entity_overlap >= 0.50
                and
                shared_title_tokens >= 4
            )
        )
        and
        (
            day_gap is None
            or
            day_gap <= 3.0
        )
        and
        weighted >= 0.56
    ):
        return (
            True,
            weighted,
            "paraphrase_entity_context",
        )

    # Titles may be radically rewritten while summaries preserve the
    # same facts.
    if (
        summary_overlap >= 0.58
        and
        strong_anchor
        and
        same_action_context
        and
        (
            day_gap is None
            or
            day_gap <= 3.0
        )
    ):
        return (
            True,
            max(
                weighted,
                summary_overlap,
            ),
            "summary_fact_overlap",
        )

    # Very strong combination of entity + actor + place/action.
    if (
        entity_overlap >= 0.70
        and
        (
            actor_overlap >= 1.0
            or
            country_overlap >= 1.0
        )
        and
        same_action_context
        and
        weighted >= 0.50
        and
        (
            day_gap is None
            or
            day_gap <= 2.0
        )
    ):
        return (
            True,
            weighted,
            "entity_actor_event_signature",
        )

    return (
        False,
        weighted,
        "different_event",
    )


def event_match(
    incoming,
    existing,
):
    best_match = (
        False,
        0.0,
        "different_event",
    )

    incoming_variants = event_variants(
        incoming
    )

    existing_variants = event_variants(
        existing
    )

    for incoming_variant in incoming_variants:
        for existing_variant in existing_variants:
            match = profile_pair_score(
                incoming_variant,
                existing_variant,
            )

            if match[1] > best_match[1]:
                best_match = match

            if (
                match[0]
                and
                match[1] >= 0.90
            ):
                return match

    return best_match


def same_event(
    event1,
    event2,
):
    return event_match(
        event1,
        event2,
    )[0]


def article_identity(article):
    url = canonical_url(
        article.get(
            "url",
            "",
        )
    )

    if url:
        return (
            "url:"
            +
            url
        )

    return (
        "title:"
        +
        normalize_event_text(
            article.get(
                "title",
                "",
            )
        )
        +
        "|"
        +
        str(
            article.get(
                "published",
                "",
            )
        )[:10]
    )


def ensure_event_metadata(event):
    sources = event.get(
        "sources"
    )

    if not isinstance(
        sources,
        list,
    ):
        sources = []

    source = clean_text(
        event.get(
            "source",
            "",
        )
    )

    if (
        source
        and
        source not in sources
    ):
        sources.append(
            source
        )

    event[
        "sources"
    ] = sources

    related = event.get(
        "related_articles"
    )

    if not isinstance(
        related,
        list,
    ):
        related = []

    event[
        "related_articles"
    ] = related[
        :MAX_RELATED_ARTICLES
    ]

    event[
        "source_count"
    ] = len(
        set(
            sources
        )
    )

    event[
        "article_count"
    ] = max(
        int(
            event.get(
                "article_count",
                1,
            )
            or
            1
        ),
        1,
    )

    if not event.get(
        "first_reported"
    ):
        event[
            "first_reported"
        ] = event.get(
            "published"
        )

    if not event.get(
        "last_reported"
    ):
        event[
            "last_reported"
        ] = event.get(
            "published"
        )


def merge_event(
    existing,
    new,
    match_score=None,
    match_method=None,
):
    ensure_event_metadata(
        existing
    )

    ensure_event_metadata(
        new
    )

    existing_categories = normalize_categories(
        (
            existing.get(
                "categories",
                [
                    existing.get(
                        "category"
                    )
                ],
            )
            +
            new.get(
                "categories",
                [
                    new.get(
                        "category"
                    )
                ],
            )
        )
    )

    existing[
        "categories"
    ] = existing_categories

    # Keep a history of genuinely different articles/headlines.
    known_article_ids = {
        article_identity(
            {
                "title":
                    existing.get(
                        "title",
                        "",
                    ),
                "url":
                    existing.get(
                        "url",
                        "",
                    ),
                "published":
                    existing.get(
                        "published",
                    ),
            }
        )
    }

    for article in existing.get(
        "related_articles",
        [],
    ):
        known_article_ids.add(
            article_identity(
                article
            )
        )

    candidate_article = {
        "title":
            new.get(
                "title",
                "",
            ),
        "original_title":
            new.get(
                "original_title",
                "",
            ),
        "original_language":
            new.get(
                "original_language",
                "",
            ),
        "summary":
            new.get(
                "summary",
                "",
            ),
        "published":
            new.get(
                "published"
            ),
        "source":
            new.get(
                "source",
                "",
            ),
        "url":
            new.get(
                "url",
                "",
            ),
    }

    candidate_id = article_identity(
        candidate_article
    )

    new_unique_article = (
        candidate_id
        not in known_article_ids
    )

    if new_unique_article:
        existing[
            "related_articles"
        ].append(
            candidate_article
        )

        existing[
            "related_articles"
        ] = existing[
            "related_articles"
        ][
            :MAX_RELATED_ARTICLES
        ]

        existing[
            "article_count"
        ] = (
            existing.get(
                "article_count",
                1,
            )
            +
            1
        )

    for source in new.get(
        "sources",
        [],
    ):
        if (
            source
            and
            source not in existing[
                "sources"
            ]
        ):
            existing[
                "sources"
            ].append(
                source
            )

    existing[
        "source_count"
    ] = len(
        set(
            existing[
                "sources"
            ]
        )
    )

    # Keep the best editorial representative as the cluster headline.
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
        old_representative = {
            "title":
                existing.get(
                    "title",
                    "",
                ),
            "original_title":
                existing.get(
                    "original_title",
                    "",
                ),
            "original_language":
                existing.get(
                    "original_language",
                    "",
                ),
            "summary":
                existing.get(
                    "summary",
                    "",
                ),
            "published":
                existing.get(
                    "published"
                ),
            "source":
                existing.get(
                    "source",
                    "",
                ),
            "url":
                existing.get(
                    "url",
                    "",
                ),
        }

        old_id = article_identity(
            old_representative
        )

        related_ids = {
            article_identity(
                article
            )
            for article in existing.get(
                "related_articles",
                [],
            )
        }

        if (
            old_id
            not in related_ids
            and
            old_id
            !=
            candidate_id
        ):
            existing[
                "related_articles"
            ].append(
                old_representative
            )

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

        for field in (
            "original_title",
            "original_summary",
            "original_language",
            "collection_language",
            "collection_language_name",
            "collection_locale",
            "translated_to_english",
            "ai_canonical_event",
        ):
            if field in new:
                existing[
                    field
                ] = new.get(
                    field
                )

    dates = [
        value
        for value in (
            existing.get(
                "first_reported"
            ),
            existing.get(
                "published"
            ),
            new.get(
                "published"
            ),
        )
        if value
    ]

    if dates:
        existing[
            "first_reported"
        ] = min(
            dates
        )

        existing[
            "published"
        ] = existing[
            "first_reported"
        ]

        existing[
            "last_reported"
        ] = max(
            dates
            +
            [
                existing.get(
                    "last_reported"
                )
            ]
            if existing.get(
                "last_reported"
            )
            else dates
        )

    if match_score is not None:
        existing[
            "dedup_confidence"
        ] = round(
            max(
                float(
                    existing.get(
                        "dedup_confidence",
                        0.0,
                    )
                    or
                    0.0
                ),
                float(
                    match_score
                ),
            ),
            3,
        )

    if match_method:
        methods = existing.get(
            "dedup_methods",
            [],
        )

        if not isinstance(
            methods,
            list,
        ):
            methods = []

        if match_method not in methods:
            methods.append(
                match_method
            )

        existing[
            "dedup_methods"
        ] = methods


def deduplicate_events(records):
    print()
    print(
        "Deduplicating events with multi-signal event clustering..."
    )

    print(
        f"   Preparing {len(records)} accepted records..."
    )

    prepared = []

    for record in records:
        ensure_event_metadata(
            record
        )

        prepared.append(
            record
        )

    # Chronological ordering makes candidate comparison much cheaper:
    # once an existing cluster is more than MAX_DEDUP_WINDOW_DAYS away,
    # older clusters do not need to be checked.
    prepared.sort(
        key=lambda event:
            (
                event_datetime(
                    event
                )
                or
                datetime.min.replace(
                    tzinfo=timezone.utc
                )
            )
    )

    events = []

    method_counts = Counter()

    for number, record in enumerate(
        prepared,
        start=1,
    ):
        record_dt = event_datetime(
            record
        )

        best_existing = None
        best_score = 0.0
        best_method = None

        for existing in reversed(
            events
        ):
            existing_dt = event_datetime(
                existing
            )

            if (
                record_dt
                and
                existing_dt
            ):
                gap_days = (
                    record_dt
                    -
                    existing_dt
                ).total_seconds() / 86400.0

                if gap_days > MAX_DEDUP_WINDOW_DAYS:
                    break

            matched, score, method = event_match(
                record,
                existing,
            )

            if (
                matched
                and
                score > best_score
            ):
                best_existing = existing
                best_score = score
                best_method = method

                if score >= 0.98:
                    break

        if best_existing is None:
            events.append(
                record
            )

        else:
            merge_event(
                best_existing,
                record,
                best_score,
                best_method,
            )

            method_counts[
                best_method
            ] += 1

        if number % 50 == 0:
            print(
                f"   Processed "
                f"{number}/"
                f"{len(prepared)}"
            )

    for event in events:
        ensure_event_metadata(
            event
        )

    print(
        f"Raw accepted records: "
        f"{len(records)}"
    )

    print(
        f"Unique event clusters: "
        f"{len(events)}"
    )

    print(
        f"Articles merged: "
        f"{len(records) - len(events)}"
    )

    if method_counts:
        print(
            "Merge methods:"
        )

        for method, count in method_counts.most_common():
            print(
                f"   {method}: "
                f"{count}"
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

            events = data.get(
                "events",
                [],
            )

            for event in events:
                categories = normalize_categories(
                    event.get("categories")
                    or
                    ([event.get("category")] if event.get("category") else [])
                )

                if categories:
                    event["categories"] = categories
                    event["category"] = categories[0]

            return events
    except Exception:
        return []


def _dedup_day_key(
    event
):
    dt = event_datetime(
        event
    )

    if not dt:
        return None

    return dt.date()


def _quick_signature(
    event
):
    """
    Cheap event signature used only to choose plausible candidates for the
    expensive event_match() function.

    It never decides that two events are duplicates by itself.
    """

    profile = build_profile(
        event
    )

    canonical = normalize_event_text(
        event.get(
            "ai_canonical_event",
            ""
        )
        or
        ""
    )

    title = profile[
        "normalized_title"
    ]

    return {
        "title":
            title,

        "canonical":
            canonical,

        "tokens":
            set(
                profile[
                    "title_tokens"
                ]
            ),

        "actors":
            set(
                profile[
                    "actors"
                ]
            ),

        "actions":
            set(
                profile[
                    "actions"
                ]
            ),

        "countries":
            set(
                profile[
                    "countries"
                ]
            ),

        "entities":
            set(
                profile[
                    "entities"
                ]
            ),

        "url":
            profile[
                "url"
            ],
    }


def _quick_candidate_compatible(
    incoming_signature,
    existing_signature,
):
    """
    Conservative pre-filter.

    Returning False means the pair is clearly implausible.
    Returning True only means it deserves the full event_match() analysis.
    """

    incoming_url = incoming_signature[
        "url"
    ]

    existing_url = existing_signature[
        "url"
    ]

    if (
        incoming_url
        and
        existing_url
        and
        incoming_url
        ==
        existing_url
    ):
        return True

    incoming_title = incoming_signature[
        "title"
    ]

    existing_title = existing_signature[
        "title"
    ]

    if (
        incoming_title
        and
        incoming_title
        ==
        existing_title
    ):
        return True

    incoming_canonical = incoming_signature[
        "canonical"
    ]

    existing_canonical = existing_signature[
        "canonical"
    ]

    if (
        incoming_canonical
        and
        existing_canonical
        and
        incoming_canonical
        ==
        existing_canonical
    ):
        return True

    incoming_countries = incoming_signature[
        "countries"
    ]

    existing_countries = existing_signature[
        "countries"
    ]

    # Explicitly incompatible geography is never worth the expensive match.
    if (
        incoming_countries
        and
        existing_countries
        and
        not (
            incoming_countries
            &
            existing_countries
        )
    ):
        return False

    shared_actors = (
        incoming_signature[
            "actors"
        ]
        &
        existing_signature[
            "actors"
        ]
    )

    shared_actions = (
        incoming_signature[
            "actions"
        ]
        &
        existing_signature[
            "actions"
        ]
    )

    shared_countries = (
        incoming_countries
        &
        existing_countries
    )

    shared_entities = (
        incoming_signature[
            "entities"
        ]
        &
        existing_signature[
            "entities"
        ]
    )

    shared_tokens = (
        incoming_signature[
            "tokens"
        ]
        &
        existing_signature[
            "tokens"
        ]
    )

    # Strong semantic anchors.
    if (
        shared_actors
        and
        (
            shared_actions
            or
            shared_countries
        )
    ):
        return True

    if (
        shared_countries
        and
        shared_actions
        and
        len(
            shared_tokens
        )
        >=
        2
    ):
        return True

    if (
        shared_entities
        and
        len(
            shared_tokens
        )
        >=
        2
    ):
        return True

    # English-normalized/canonical titles allow a cheap lexical rescue for
    # rewritten multilingual coverage of the same event.
    if (
        incoming_title
        and
        existing_title
    ):
        lexical = SequenceMatcher(
            None,
            incoming_title,
            existing_title,
        ).ratio()

        if lexical >= 0.52:
            return True

    if (
        incoming_canonical
        and
        existing_canonical
    ):
        canonical_similarity = SequenceMatcher(
            None,
            incoming_canonical,
            existing_canonical,
        ).ratio()

        if canonical_similarity >= 0.55:
            return True

    return False


def deduplicate_incremental(
    existing_events,
    fresh_records,
):
    """
    Fast indexed daily update.

    Previous implementation scanned every eligible existing event and ran the
    full multi-variant event_match() against it. With multilingual clusters,
    one event can contain many title/article variants, making that approach
    extremely expensive.

    V9.1:
      1. indexes existing events by day, exact URL and normalized title;
      2. restricts candidates to the +/- MAX_DEDUP_WINDOW_DAYS window;
      3. applies a cheap semantic compatibility test;
      4. calls the original full event_match() only on that shortlist.

    The final duplicate decision is STILL made by the same intelligent
    event_match() logic, so matching quality is preserved.
    """

    print()
    print(
        "FAST indexed incremental deduplication..."
    )
    print(
        f"   Existing event clusters: "
        f"{len(existing_events)}"
    )
    print(
        f"   Fresh accepted records:  "
        f"{len(fresh_records)}"
    )

    events = []

    day_index = defaultdict(
        set
    )

    url_index = defaultdict(
        set
    )

    title_index = defaultdict(
        set
    )

    signatures = {}

    def index_event(
        index,
        event
    ):
        ensure_event_metadata(
            event
        )

        signature = _quick_signature(
            event
        )

        signatures[
            index
        ] = signature

        day = _dedup_day_key(
            event
        )

        if day is not None:
            day_index[
                day
            ].add(
                index
            )

        url = signature[
            "url"
        ]

        if url:
            url_index[
                url
            ].add(
                index
            )

        title = signature[
            "title"
        ]

        if title:
            title_index[
                title
            ].add(
                index
            )

        # Exact title variants are cheap and valuable.
        for variant in event.get(
            "title_variants",
            []
        )[:MAX_RELATED_ARTICLES]:
            normalized = normalize_event_text(
                variant
            )

            if normalized:
                title_index[
                    normalized
                ].add(
                    index
                )

    for event in existing_events:
        index = len(
            events
        )

        events.append(
            event
        )

        index_event(
            index,
            event
        )

    method_counts = Counter()
    merged_count = 0

    total_full_comparisons = 0
    total_shortlisted = 0

    for number, record in enumerate(
        fresh_records,
        start=1,
    ):
        ensure_event_metadata(
            record
        )

        incoming_signature = _quick_signature(
            record
        )

        candidates = set()

        # ----------------------------------------------------
        # Exact anchors first.
        # ----------------------------------------------------

        incoming_url = incoming_signature[
            "url"
        ]

        if incoming_url:
            candidates.update(
                url_index.get(
                    incoming_url,
                    set()
                )
            )

        incoming_title = incoming_signature[
            "title"
        ]

        if incoming_title:
            candidates.update(
                title_index.get(
                    incoming_title,
                    set()
                )
            )

        # ----------------------------------------------------
        # Time-window candidates.
        # ----------------------------------------------------

        record_day = _dedup_day_key(
            record
        )

        time_candidates = set()

        if record_day is not None:
            for offset in range(
                -MAX_DEDUP_WINDOW_DAYS,
                MAX_DEDUP_WINDOW_DAYS + 1,
            ):
                day = (
                    record_day
                    +
                    timedelta(
                        days=offset
                    )
                )

                time_candidates.update(
                    day_index.get(
                        day,
                        set()
                    )
                )

        else:
            # Rare legacy/no-date case: preserve recall.
            time_candidates.update(
                range(
                    len(
                        events
                    )
                )
            )

        # ----------------------------------------------------
        # Cheap semantic shortlist.
        # ----------------------------------------------------

        for candidate_index in time_candidates:
            if candidate_index in candidates:
                continue

            existing_signature = signatures.get(
                candidate_index
            )

            if existing_signature is None:
                continue

            if _quick_candidate_compatible(
                incoming_signature,
                existing_signature,
            ):
                candidates.add(
                    candidate_index
                )

        total_shortlisted += len(
            candidates
        )

        best_existing = None
        best_existing_index = None
        best_score = 0.0
        best_method = None

        # Exact matches are usually at the beginning after sorting.
        candidate_list = list(
            candidates
        )

        candidate_list.sort(
            key=lambda candidate_index:
                (
                    0
                    if (
                        incoming_url
                        and
                        signatures[
                            candidate_index
                        ][
                            "url"
                        ]
                        ==
                        incoming_url
                    )
                    else
                    1,

                    0
                    if (
                        incoming_title
                        and
                        signatures[
                            candidate_index
                        ][
                            "title"
                        ]
                        ==
                        incoming_title
                    )
                    else
                    1,
                )
        )

        for candidate_index in candidate_list:
            existing = events[
                candidate_index
            ]

            total_full_comparisons += 1

            matched, score, method = event_match(
                record,
                existing,
            )

            if (
                matched
                and
                score
                >
                best_score
            ):
                best_existing = existing
                best_existing_index = (
                    candidate_index
                )
                best_score = score
                best_method = method

                if score >= 0.98:
                    break

        if best_existing is None:
            new_index = len(
                events
            )

            events.append(
                record
            )

            index_event(
                new_index,
                record
            )

        else:
            merge_event(
                best_existing,
                record,
                best_score,
                best_method,
            )

            merged_count += 1

            method_counts[
                best_method
            ] += 1

            # Refresh the quick signature/index so subsequent fresh events can
            # benefit from the newly merged title/source variants.
            index_event(
                best_existing_index,
                best_existing,
            )

        if (
            number % 20 == 0
            or
            number
            ==
            len(
                fresh_records
            )
        ):
            average_candidates = (
                total_shortlisted
                /
                number
                if number
                else
                0
            )

            print(
                f"   Processed fresh records: "
                f"{number}/"
                f"{len(fresh_records)} "
                f"| avg shortlist "
                f"{average_candidates:.1f} "
                f"| full matches "
                f"{total_full_comparisons}"
            )

    print(
        f"   New standalone clusters: "
        f"{len(events) - len(existing_events)}"
    )
    print(
        f"   Fresh records merged:     "
        f"{merged_count}"
    )
    print(
        f"   Full expensive comparisons: "
        f"{total_full_comparisons}"
    )

    if method_counts:
        print(
            "   Merge methods:"
        )

        for method, count in method_counts.most_common():
            print(
                f"      {method}: "
                f"{count}"
            )

    return events


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



def _parse_iso_utc(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
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


def _trend_recency(event):
    return (
        _parse_iso_utc(
            event.get(
                "last_reported"
            )
        )
        or
        _parse_iso_utc(
            event.get(
                "published"
            )
        )
    )


def _trend_priority(event):
    score = float(
        event.get(
            "ai_relevance_score",
            50,
        )
        or
        50
    )

    categories = set(
        event.get(
            "categories"
        )
        or
        ([event.get("category")] if event.get("category") else [])
    )

    if "Attacks" in categories:
        score += 18
    if "Weapons" in categories:
        score += 7
    if "CBRN" in categories:
        score += 10
    if "Arrests" in categories:
        score += 5
    if "Terrorist Financing" in categories:
        score += 5

    score += min(
        15,
        max(
            0,
            int(
                event.get(
                    "source_count",
                    1,
                )
                or
                1
            )
            -
            1
        )
        *
        3,
    )

    return score


def _trend_payload(event, index):
    return {
        "event_id":
            str(
                event.get("id")
                or
                f"trend-{index}"
            ),
        "title":
            selection_compact_text(
                event.get("title"),
                450,
            ),
        "summary":
            selection_compact_text(
                event.get("summary"),
                850,
            ),
        "categories":
            list(
                event.get("categories")
                or
                ([event.get("category")] if event.get("category") else [])
            ),
        "country":
            clean_text(
                event.get("country", "")
            ),
        "region":
            clean_text(
                event.get("region", "")
            ),
        "city":
            clean_text(
                event.get("city", "")
            ),
        "first_reported":
            str(
                event.get("first_reported")
                or
                event.get("published")
                or
                ""
            ),
        "last_reported":
            str(
                event.get("last_reported")
                or
                event.get("published")
                or
                ""
            ),
        "ai_relevance_score":
            int(
                event.get("ai_relevance_score", 0)
                or
                0
            ),
        "source_count":
            int(
                event.get("source_count", 1)
                or
                1
            ),
        "article_count":
            int(
                event.get("article_count", 1)
                or
                1
            ),
        "primary_source":
            clean_text(
                event.get("source", "")
            ),
    }


def _trend_fallback(candidates, generated_at, reason=""):
    developments = []

    for event in candidates[:5]:
        relevance = int(
            event.get(
                "ai_relevance_score",
                0,
            )
            or
            0
        )

        if relevance >= 90:
            severity = "HIGH"
        else:
            severity = "SIGNIFICANT"

        categories = list(
            event.get("categories")
            or
            ([event.get("category")] if event.get("category") else [])
        )

        location = ", ".join(
            value
            for value in [
                clean_text(event.get("city", "")),
                clean_text(event.get("region", "")),
                clean_text(event.get("country", "")),
            ]
            if value
        )

        developments.append(
            {
                "event_id": str(
                    event.get("id")
                    or
                    event.get("_mapKey")
                    or
                    ""
                ),
                "severity": severity,
                "category": (
                    categories[0]
                    if categories
                    else
                    "CT Development"
                ),
                "headline": selection_compact_text(
                    event.get("title"),
                    220,
                ),
                "detail": selection_compact_text(
                    event.get("summary"),
                    420,
                ),
                "location": location,
            }
        )

    return {
        "status": "fallback",
        "model": AI_TREND_MODEL,
        "window_hours": 24,
        "generated_at": generated_at,
        "candidate_events": len(candidates),
        "overview": (
            "AI trend synthesis was unavailable for this update. "
            "The highest-relevance CT events reported or updated in the last "
            "24 hours are shown below without additional analytical synthesis."
        ),
        "developments": developments,
        "warning": reason,
    }


def generate_24h_trend_summary(events):
    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    cutoff = datetime.now(
        timezone.utc
    ) - timedelta(
        hours=24
    )

    recent = []

    for event in events:
        recency = _trend_recency(
            event
        )

        if (
            recency is not None
            and
            recency >= cutoff
        ):
            recent.append(
                event
            )

    recent.sort(
        key=_trend_priority,
        reverse=True,
    )

    recent = recent[
        :AI_TREND_MAX_CANDIDATES
    ]

    print()
    print("=" * 70)
    print("GEMINI 24H SENSITIVE TREND SUMMARY")
    print("=" * 70)
    print(
        f"Recent candidate events: {len(recent)}"
    )
    print(
        f"Trend model: {AI_TREND_MODEL}"
    )

    if not recent:
        print(
            "No CT events reported/updated in the last 24 hours."
        )

        return {
            "status": "ok",
            "model": AI_TREND_MODEL,
            "window_hours": 24,
            "generated_at": generated_at,
            "candidate_events": 0,
            "overview": (
                "No significant CT developments were available for the "
                "24-hour trend brief at the time of this update."
            ),
            "developments": [],
        }

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        print(
            "Trend summary fallback: GEMINI_API_KEY unavailable."
        )
        return _trend_fallback(
            recent,
            generated_at,
            "GEMINI_API_KEY unavailable",
        )

    batch = [
        _trend_payload(
            event,
            index,
        )
        for index, event in enumerate(
            recent
        )
    ]

    body = {
        "model": AI_TREND_MODEL,
        "input": (
            "Produce the 24-hour sensitive CT developments brief from the "
            "deduplicated events below. Use only these records.\n\n"
            +
            json.dumps(
                {"events": batch},
                ensure_ascii=False,
            )
        ),
        "system_instruction": AI_TREND_INSTRUCTIONS,
        "store": False,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": AI_TREND_SCHEMA,
        },
        "generation_config": {
            "max_output_tokens": 8000,
            "thinking_level": "minimal",
        },
    }

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    last_error = None

    for attempt in range(
        1,
        AI_TREND_ATTEMPTS + 1,
    ):
        try:
            response = requests.post(
                GEMINI_INTERACTIONS_URL,
                headers=headers,
                json=body,
                timeout=AI_TREND_TIMEOUT,
            )

            if response.status_code == 429:
                last_error = "Gemini trend quota exceeded (429)"
                print(
                    f"   Trend attempt {attempt}/{AI_TREND_ATTEMPTS}: 429"
                )
                time.sleep(
                    attempt * 5
                )
                continue

            if response.status_code >= 500:
                last_error = (
                    "Gemini trend temporary error "
                    f"{response.status_code}"
                )
                print(
                    f"   Trend attempt {attempt}/{AI_TREND_ATTEMPTS}: "
                    f"HTTP {response.status_code}"
                )
                time.sleep(
                    attempt * 4
                )
                continue

            response.raise_for_status()

            output_text = extract_interaction_text(
                response.json()
            )

            result = json.loads(
                output_text
            )

            developments = result.get(
                "developments",
                []
            )

            if not isinstance(
                developments,
                list,
            ):
                developments = []

            result[
                "developments"
            ] = developments[:6]

            result.update(
                {
                    "status": "ok",
                    "model": AI_TREND_MODEL,
                    "window_hours": 24,
                    "generated_at": generated_at,
                    "candidate_events": len(recent),
                }
            )

            print(
                f"Trend summary generated: {len(result['developments'])} "
                "priority developments."
            )

            return result

        except Exception as error:
            last_error = str(
                error
            )
            print(
                f"   Trend attempt {attempt}/{AI_TREND_ATTEMPTS} failed: "
                f"{error}"
            )
            time.sleep(
                attempt * 3
            )

    print(
        "Trend summary AI unavailable; using safe fallback."
    )

    return _trend_fallback(
        recent,
        generated_at,
        last_error or "Unknown Gemini trend error",
    )




def load_existing_weekly_analysis():
    try:
        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(
                file
            )

        weekly = data.get(
            "weekly_analysis"
        )

        return (
            weekly
            if isinstance(
                weekly,
                dict,
            )
            else
            {}
        )

    except Exception:
        return {}


def _weekly_event_time(event):
    """
    Prefer explicit occurrence/incident dates when available.
    Fall back to the event's report/update recency so the weekly analysis
    remains usable for records that do not yet carry a structured event date.
    """
    for field in (
        "event_date",
        "occurrence_date",
        "occurred_at",
        "incident_date",
        "attack_date",
    ):
        dt = _parse_iso_utc(
            event.get(
                field
            )
        )

        if dt is not None:
            return dt

    return _trend_recency(
        event
    )


def _weekly_top_counter(events, field_name, limit=8):
    counter = Counter()

    for event in events:
        value = clean_text(
            event.get(
                field_name,
                ""
            )
        )

        if value:
            counter[
                value
            ] += 1

    return counter.most_common(
        limit
    )


def _weekly_category_counts(events):
    counter = Counter()

    for event in events:
        categories = (
            event.get(
                "categories"
            )
            or
            (
                [
                    event.get(
                        "category"
                    )
                ]
                if event.get(
                    "category"
                )
                else
                []
            )
        )

        for category in set(
            categories
        ):
            if category:
                counter[
                    category
                ] += 1

    return dict(
        counter
    )


def _weekly_stats(events):
    return {
        "event_count":
            len(
                events
            ),
        "categories":
            _weekly_category_counts(
                events
            ),
        "top_countries":
            _weekly_top_counter(
                events,
                "country",
                10,
            ),
        "top_regions":
            _weekly_top_counter(
                events,
                "region",
                8,
            ),
    }


def _weekly_compact_event(event, index):
    return {
        "event_id":
            str(
                event.get(
                    "id"
                )
                or
                f"weekly-{index}"
            ),
        "title":
            selection_compact_text(
                event.get(
                    "title"
                ),
                320,
            ),
        "summary":
            selection_compact_text(
                event.get(
                    "summary"
                ),
                600,
            ),
        "categories":
            list(
                event.get(
                    "categories"
                )
                or
                (
                    [
                        event.get(
                            "category"
                        )
                    ]
                    if event.get(
                        "category"
                    )
                    else
                    []
                )
            ),
        "country":
            clean_text(
                event.get(
                    "country",
                    ""
                )
            ),
        "region":
            clean_text(
                event.get(
                    "region",
                    ""
                )
            ),
        "city":
            clean_text(
                event.get(
                    "city",
                    ""
                )
            ),
        "event_or_report_time":
            (
                _weekly_event_time(
                    event
                ).isoformat()
                if _weekly_event_time(
                    event
                )
                else
                ""
            ),
        "ai_relevance_score":
            int(
                event.get(
                    "ai_relevance_score",
                    0,
                )
                or
                0
            ),
        "source_count":
            int(
                event.get(
                    "source_count",
                    1,
                )
                or
                1
            ),
        "primary_source":
            clean_text(
                event.get(
                    "source",
                    ""
                )
            ),
    }


def _weekly_windows(events):
    now_utc = datetime.now(
        timezone.utc
    )

    current_start = (
        now_utc
        -
        timedelta(
            days=7
        )
    )

    previous_start = (
        now_utc
        -
        timedelta(
            days=14
        )
    )

    current = []
    previous = []

    for event in events:
        dt = _weekly_event_time(
            event
        )

        if dt is None:
            continue

        if (
            current_start
            <=
            dt
            <=
            now_utc
        ):
            current.append(
                event
            )

        elif (
            previous_start
            <=
            dt
            <
            current_start
        ):
            previous.append(
                event
            )

    current.sort(
        key=_trend_priority,
        reverse=True,
    )

    previous.sort(
        key=_trend_priority,
        reverse=True,
    )

    return {
        "now":
            now_utc,
        "current_start":
            current_start,
        "previous_start":
            previous_start,
        "current":
            current,
        "previous":
            previous,
    }


def _weekly_sunday_key(now_paris):
    return now_paris.date().isoformat()


def should_generate_weekly_analysis(existing_weekly):
    """
    First-ever report: generate immediately on the next collector run.

    Subsequent reports:
      Sunday after 06:00 Europe/Paris.
      If 06:17 generation fails, the report key remains old/missing, so
      the 12:17 and 18:17 Sunday runs automatically retry.
    """
    if not existing_weekly:
        return True, "first_report"

    now_paris = datetime.now(
        PARIS_TZ
    )

    if (
        now_paris.weekday()
        !=
        6
    ):
        return False, "not_sunday"

    if (
        now_paris.hour
        <
        6
    ):
        return False, "before_second_sunday_update"

    expected_key = _weekly_sunday_key(
        now_paris
    )

    if (
        existing_weekly.get(
            "sunday_key"
        )
        ==
        expected_key
    ):
        return False, "already_generated_this_sunday"

    return True, "scheduled_sunday"


def generate_weekly_analysis(events, existing_weekly=None):
    existing_weekly = (
        existing_weekly
        if isinstance(
            existing_weekly,
            dict,
        )
        else
        {}
    )

    should_generate, reason = should_generate_weekly_analysis(
        existing_weekly
    )

    if not should_generate:
        print()
        print("=" * 70)
        print("WEEKLY ANALYSIS")
        print("=" * 70)
        print(
            f"No weekly generation required: {reason}"
        )
        return existing_weekly

    windows = _weekly_windows(
        events
    )

    now_utc = windows[
        "now"
    ]

    current = windows[
        "current"
    ]

    previous = windows[
        "previous"
    ]

    now_paris = datetime.now(
        PARIS_TZ
    )

    print()
    print("=" * 70)
    print("GEMINI WEEKLY CT CRIMINAL ANALYSIS")
    print("=" * 70)
    print(
        f"Trigger: {reason}"
    )
    print(
        f"Current 7-day events: {len(current)}"
    )
    print(
        f"Previous 7-day events: {len(previous)}"
    )

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:
        print(
            "Weekly analysis not generated: GEMINI_API_KEY unavailable."
        )
        return existing_weekly

    current_payload = [
        _weekly_compact_event(
            event,
            index,
        )
        for index, event in enumerate(
            current[
                :AI_WEEKLY_MAX_CURRENT_EVENTS
            ]
        )
    ]

    previous_payload = [
        _weekly_compact_event(
            event,
            index,
        )
        for index, event in enumerate(
            previous[
                :AI_WEEKLY_MAX_PREVIOUS_EVENTS
            ]
        )
    ]

    payload = {
        "reporting_period": {
            "current_start":
                windows[
                    "current_start"
                ].isoformat(),
            "current_end":
                now_utc.isoformat(),
            "comparison_start":
                windows[
                    "previous_start"
                ].isoformat(),
            "comparison_end":
                windows[
                    "current_start"
                ].isoformat(),
        },
        "current_period_stats":
            _weekly_stats(
                current
            ),
        "comparison_period_stats":
            _weekly_stats(
                previous
            ),
        "current_priority_events":
            current_payload,
        "comparison_priority_events":
            previous_payload,
    }

    body = {
        "model":
            AI_WEEKLY_MODEL,
        "input":
            (
                "Produce the weekly comparative CT criminal-analysis brief "
                "using only the supplied data.\n\n"
                +
                json.dumps(
                    payload,
                    ensure_ascii=False,
                )
            ),
        "system_instruction":
            AI_WEEKLY_INSTRUCTIONS,
        "store":
            False,
        "response_format": {
            "type":
                "text",
            "mime_type":
                "application/json",
            "schema":
                AI_WEEKLY_SCHEMA,
        },
        "generation_config": {
            "max_output_tokens":
                9000,
            "thinking_level":
                "minimal",
        },
    }

    headers = {
        "x-goog-api-key":
            api_key,
        "Content-Type":
            "application/json",
    }

    last_error = None

    for attempt in range(
        1,
        AI_WEEKLY_ATTEMPTS + 1,
    ):
        try:
            response = requests.post(
                GEMINI_INTERACTIONS_URL,
                headers=headers,
                json=body,
                timeout=AI_WEEKLY_TIMEOUT,
            )

            if response.status_code == 429:
                last_error = "Gemini weekly quota exceeded (429)"
                print(
                    f"Weekly attempt {attempt}/{AI_WEEKLY_ATTEMPTS}: 429"
                )
                time.sleep(
                    attempt
                    *
                    7
                )
                continue

            if response.status_code >= 500:
                last_error = (
                    "Gemini weekly temporary error "
                    f"{response.status_code}"
                )
                print(
                    f"Weekly attempt {attempt}/{AI_WEEKLY_ATTEMPTS}: "
                    f"HTTP {response.status_code}"
                )
                time.sleep(
                    attempt
                    *
                    5
                )
                continue

            response.raise_for_status()

            result = json.loads(
                extract_interaction_text(
                    response.json()
                )
            )

            title = selection_compact_text(
                result.get(
                    "title"
                ),
                180,
            )

            analysis = clean_text(
                result.get(
                    "analysis"
                )
            )

            if not analysis:
                raise RuntimeError(
                    "Gemini weekly analysis returned no analysis text."
                )

            weekly = {
                "status":
                    "ok",
                "model":
                    AI_WEEKLY_MODEL,
                "generated_at":
                    now_utc.isoformat(),
                "sunday_key":
                    (
                        _weekly_sunday_key(
                            now_paris
                        )
                        if now_paris.weekday() == 6
                        else ""
                    ),
                "trigger":
                    reason,
                "title":
                    (
                        title
                        or
                        "Weekly CT Criminal Analysis"
                    ),
                "analysis":
                    analysis,
                "current_period_start":
                    windows[
                        "current_start"
                    ].isoformat(),
                "current_period_end":
                    now_utc.isoformat(),
                "comparison_period_start":
                    windows[
                        "previous_start"
                    ].isoformat(),
                "comparison_period_end":
                    windows[
                        "current_start"
                    ].isoformat(),
                "current_event_count":
                    len(
                        current
                    ),
                "comparison_event_count":
                    len(
                        previous
                    ),
            }

            print(
                "Weekly analysis generated successfully."
            )

            return weekly

        except Exception as error:
            last_error = str(
                error
            )
            print(
                f"Weekly attempt {attempt}/{AI_WEEKLY_ATTEMPTS} failed: "
                f"{error}"
            )
            time.sleep(
                attempt
                *
                4
            )

    print(
        "Weekly analysis generation failed. "
        "Previous report is preserved; a later eligible Sunday run can retry."
    )

    if last_error:
        print(
            f"Last weekly error: {last_error}"
        )

    return existing_weekly


def save_database(events, trend_summary=None, weekly_analysis=None):
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
            "English display; multilingual source collection",
        "source_languages":
            [
                "en", "fr", "ar", "de", "es", "it",
                "tr", "ru", "ur", "fa", "he"
            ],
        "collector":
            "Google News RSS V9 multilingual + Gemini selection/translation",
        "relevance_filter":
            "Deterministic CT candidate filter + Gemini semantic final selection",

        "trend_summary":
            trend_summary
            or
            {},

        "weekly_analysis":
            weekly_analysis
            or
            {},

        "ai_article_selection": {
            "enabled":
                AI_SELECTION_ENABLED,
            "model":
                AI_SELECTION_MODEL,
            "threshold":
                AI_SELECTION_THRESHOLD,
            "version":
                AI_SELECTION_VERSION,
        },
        "deduplication":
            "Multi-signal event clustering V4",
        "search_query_count":
            (
                sum(
                    len(terms)
                    for terms
                    in CORE_SEARCH_QUERIES.values()
                )
                +
                len(
                    OFFICIAL_BROAD_QUERIES
                )
                +
                sum(
                    len(
                        targeted_source_queries(
                            source
                        )
                    )
                    for source
                    in TARGETED_SOURCE_SITES
                )
                +
                multilingual_query_count()
            ),
        "general_search_query_count":
            sum(
                len(terms)
                for terms
                in CORE_SEARCH_QUERIES.values()
            ),
        "official_source_query_count":
            len(
                OFFICIAL_BROAD_QUERIES
            ),
        "targeted_source_query_count":
            sum(
                len(
                    targeted_source_queries(
                        source
                    )
                )
                for source
                in TARGETED_SOURCE_SITES
            ),
        "multilingual_query_count":
            multilingual_query_count(),
        "multilingual_languages":
            [
                profile[
                    "name"
                ]
                for profile
                in MULTILINGUAL_PROFILES
            ],
        "targeted_sources":
            [
                source[
                    "name"
                ]
                for source
                in TARGETED_SOURCE_SITES
            ],
        "acled_mode":
            "Publicly indexed ACLED analysis/news via Google News; direct ACLED API not enabled",
        "official_sources":
            [
                "U.S. Department of Justice",
                "U.S. Department of the Treasury / OFAC",
                "Counter Terrorism Policing UK",
                "Europol",
                "UK Government / Counter-Terrorism",
                "INTERPOL English News",
            ],
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
    existing_weekly_analysis = load_existing_weekly_analysis()

    is_backfill = (
        len(
            sys.argv
        )
        >
        1

        and

        sys.argv[
            1
        ].lower()
        ==
        "backfill"
    )

    if is_backfill:
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

        print(
            f"Existing database loaded: "
            f"{len(existing)} events"
        )

    fresh = collect_all(
        days
    )

    print()
    print(
        f"Collection returned "
        f"{len(fresh)} deterministic candidate records."
    )

    # --------------------------------------------------------
    # Deduplicate BEFORE AI review.
    #
    # This prevents Gemini from reviewing 30-50 copies of the same
    # underlying story found through different Google News searches.
    # --------------------------------------------------------

    print()
    print(
        "Clustering fresh candidate records before AI selection..."
    )

    fresh_clusters = deduplicate_events(
        fresh
    )

    print(
        f"Fresh candidate event clusters: "
        f"{len(fresh_clusters)}"
    )

    selected_fresh = ai_select_events(
        fresh_clusters
    )

    if selected_fresh is None:
        print()
        print("=" * 70)
        print("COLLECTION PAUSED — AI SELECTION INCOMPLETE")
        print("=" * 70)
        print(
            "events.json has not been replaced."
        )
        print(
            f"Progress is preserved in "
            f"{AI_SELECTION_CACHE_FILE}."
        )

        # Non-zero exit lets the workflow stop before geolocation.
        # A dedicated `if: always()` workflow step commits the cache.
        raise SystemExit(
            75
        )

    print()
    print(
        f"Gemini selected "
        f"{len(selected_fresh)}/"
        f"{len(fresh_clusters)} "
        f"candidate event clusters."
    )

    # Gemini has now normalized every retained candidate into English. Run the
    # smart deduplicator again so French/Arabic/German/etc. reports of the same
    # event can converge into one multilingual event cluster.
    print()
    print(
        "Cross-language deduplication on AI-normalized English events..."
    )

    selected_fresh = deduplicate_events(
        selected_fresh
    )

    print(
        f"Post-translation event clusters: "
        f"{len(selected_fresh)}"
    )

    if is_backfill:
        events = selected_fresh

    else:
        print(
            "Using FAST incremental daily clustering "
            "against the existing database."
        )

        events = deduplicate_incremental(
            existing,
            selected_fresh,
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

    trend_summary = generate_24h_trend_summary(
        events
    )

    weekly_analysis = generate_weekly_analysis(
        events,
        existing_weekly=existing_weekly_analysis,
    )

    save_database(
        events,
        trend_summary=trend_summary,
        weekly_analysis=weekly_analysis,
    )
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
        f"{sum(len(v) for v in CORE_SEARCH_QUERIES.values()) + len(OFFICIAL_BROAD_QUERIES) + sum(len(targeted_source_queries(source)) for source in TARGETED_SOURCE_SITES) + multilingual_query_count()}"
    )
    print(
        f"AI article threshold: "
        f"{AI_SELECTION_THRESHOLD}/100"
    )
    print(
        f"Saved to: "
        f"{OUTPUT_FILE}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
