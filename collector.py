import feedparser
import hashlib
import html
import json
import re
import sys
import time
import unicodedata
import random

import requests

from collections import Counter
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit, urlunsplit


# ============================================================
# INTERPOL CT INTELLIGENCE MAP
# OSINT COLLECTOR V7 — THROTTLE-SAFE MULTI-SOURCE CT COVERAGE
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
    'OR "al-Qaeda")'
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
    One broad source query can yield articles for any of the 8 CT categories.
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


def collect_all(days):
    print()
    print("=" * 70)
    print("INTERPOL CT Intelligence Map")
    print("OSINT Collector V7 — throttle-safe multi-source CT coverage")
    print("=" * 70)
    print(f"Window: {days} days")
    print("Language: English")
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


def event_datetime(event):
    published = event.get(
        "published"
    )

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


def build_profile(event):
    title = clean_text(
        event.get(
            "title",
            "",
        )
    )

    summary = clean_text(
        event.get(
            "summary",
            "",
        )
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

    title_tokens = meaningful_tokens(
        title
    )

    summary_tokens = meaningful_tokens(
        summary
    )

    return {
        "normalized_title":
            normalized_title,
        "title_tokens":
            title_tokens,
        "summary_tokens":
            summary_tokens,
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
                event.get(
                    "url",
                    "",
                )
            ),
    }


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

    existing_categories = list(
        dict.fromkeys(
            [
                category
                for category in (
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
                if category
            ]
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

        if number % 250 == 0:
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
            "Google News RSS V7 throttle-safe compact discovery + local classification",
        "relevance_filter":
            "CT event relevance filter V3",
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
        f"{sum(len(v) for v in CORE_SEARCH_QUERIES.values()) + len(OFFICIAL_BROAD_QUERIES) + sum(len(targeted_source_queries(source)) for source in TARGETED_SOURCE_SITES)}"
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
