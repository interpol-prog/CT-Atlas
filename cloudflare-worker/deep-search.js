import {
  GEMINI_URL,
  jsonResponse,
  cleanText,
  normalizeUsername,
  isAllowedUser,
  gateCall,
  extractGeminiText,
  sha256
} from "./shared.js";

const DEEP_SEARCH_ALLOWED_PERIODS = new Set([7, 30, 90, 180, 365]);
const DEEP_SEARCH_MAX_QUERIES = 24;
const DEEP_SEARCH_RESULTS_PER_QUERY = 30;
const DEEP_SEARCH_MAX_EVIDENCE = 48;
const DEEP_SEARCH_CACHE_TTL_MS = 4 * 60 * 60 * 1000;
const DEEP_SEARCH_MODEL = "gemini-3.5-flash-lite";
export const DEEP_SEARCH_VERSION = "deep-search-v5.10-question-analysis-priority-langs";
const SEARCH_FALLBACK_LOCALE = Object.freeze({ hl: "en-US", gl: "US", ceid: "US:en" });
const GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc";
const GDELT_RESULTS_PER_LANGUAGE = 25;
const GDELT_LANGUAGE_FILTERS = Object.freeze({
  en: "english", fr: "french", ar: "arabic", de: "german",
  es: "spanish", it: "italian", tr: "turkish", ru: "russian",
  fa: "persian", ur: "urdu", he: "hebrew", ps: "pashto"
});

const LANGUAGE_LOCALES = Object.freeze({
  en: { label: "English", hl: "en-US", gl: "US", ceid: "US:en" },
  fr: { label: "French", hl: "fr", gl: "FR", ceid: "FR:fr" },
  ar: { label: "Arabic", hl: "ar", gl: "SA", ceid: "SA:ar" },
  de: { label: "German", hl: "de", gl: "DE", ceid: "DE:de" },
  es: { label: "Spanish", hl: "es", gl: "ES", ceid: "ES:es" },
  it: { label: "Italian", hl: "it", gl: "IT", ceid: "IT:it" },
  tr: { label: "Turkish", hl: "tr", gl: "TR", ceid: "TR:tr" },
  ru: { label: "Russian", hl: "ru", gl: "RU", ceid: "RU:ru" },
  fa: { label: "Dari / Persian", hl: "fa", gl: "AF", ceid: "AF:fa" },
  ur: { label: "Urdu", hl: "ur", gl: "PK", ceid: "PK:ur" },
  he: { label: "Hebrew", hl: "he", gl: "IL", ceid: "IL:he" },
  ps: { label: "Pashto", hl: "ps", gl: "AF", ceid: "AF:ps" }
});

const DEEP_SEARCH_LANGUAGE_CODES = Object.freeze(Object.keys(LANGUAGE_LOCALES));


const COUNTRY_LANGUAGE_PRIORITY = Object.freeze([
  { pattern: /\b(?:afghanistan|afghan)\b/i, languages: ["fa", "ps", "ur"] },
  { pattern: /\b(?:pakistan|pakistani)\b/i, languages: ["ur"] },
  { pattern: /\b(?:iran|iranian)\b/i, languages: ["fa"] },
  { pattern: /\b(?:france|french)\b/i, languages: ["fr"] },
  { pattern: /\b(?:germany|german)\b/i, languages: ["de"] },
  { pattern: /\b(?:spain|spanish)\b/i, languages: ["es"] },
  { pattern: /\b(?:italy|italian)\b/i, languages: ["it"] },
  { pattern: /\b(?:turkey|türkiye|turkiye|turkish)\b/i, languages: ["tr"] },
  { pattern: /\b(?:russia|russian)\b/i, languages: ["ru"] },
  { pattern: /\b(?:israel|israeli)\b/i, languages: ["he", "ar"] },
  { pattern: /\b(?:palestine|palestinian|gaza|west bank)\b/i, languages: ["ar", "he"] },
  { pattern: /\b(?:iraq|iraqi|syria|syrian|lebanon|lebanese|jordan|jordanian|saudi arabia|saudi|yemen|yemeni|oman|omani|qatar|qatari|united arab emirates|uae|bahrain|bahraini|kuwait|kuwaiti|egypt|egyptian|libya|libyan|tunisia|tunisian|algeria|algerian|morocco|moroccan|sudan|sudanese|mauritania|mauritanian)\b/i, languages: ["ar"] }
]);

// English and French are always searched with priority: they are the two
// languages CT Atlas analysts read directly, and they are searched first no
// matter which country the question is about.
const ALWAYS_PRIORITY_LANGUAGES = Object.freeze(["en", "fr"]);
const PRIORITY_LANGUAGE_CAP = 5;

function detectCountryLanguages(question) {
  const text = String(question || "");
  const out = [];
  const add = code => {
    if (DEEP_SEARCH_LANGUAGE_CODES.includes(code) && !out.includes(code)) out.push(code);
  };
  for (const rule of COUNTRY_LANGUAGE_PRIORITY) {
    if (rule.pattern.test(text)) rule.languages.forEach(add);
  }
  return out;
}

// Combines the always-on languages, the languages detected from country names
// in the question, and the languages the planner LLM itself proposed, capped
// so the retrieval budget stays well under Cloudflare's subrequest ceiling.
function resolvePriorityLanguages(question, plannerLanguages = []) {
  const merged = [...ALWAYS_PRIORITY_LANGUAGES, ...detectCountryLanguages(question), ...plannerLanguages]
    .filter(code => DEEP_SEARCH_LANGUAGE_CODES.includes(code));
  return [...new Set(merged)].slice(0, PRIORITY_LANGUAGE_CAP);
}

function broadGdeltQuery(plan) {
  const primary = cleanText(plan?.queries?.find(item => item.language === "en" && item.variant === "primary")?.query || "", 220);
  const secondary = cleanText(plan?.queries?.find(item => item.language === "en" && item.variant === "secondary")?.query || "", 220);
  const stop = new Set(["the","and","for","with","from","into","over","under","about","information","data","report","reports","latest","recent"]);
  const tokens = value => (String(value || "").toLowerCase().match(/[a-z0-9][a-z0-9-]{2,}/g) || []).filter(t => !stop.has(t));
  const p = tokens(primary), q = tokens(secondary), qset = new Set(q);
  const shared = p.filter(t => qset.has(t));
  const head = shared[0] || p[0] || q[0] || "";
  const rest = [];
  for (const token of [...p, ...q]) {
    if (!token || token === head || rest.includes(token)) continue;
    rest.push(token);
    if (rest.length >= 4) break;
  }
  if (!head) return "";
  return rest.length ? `${head} (${rest.join(" OR ")})` : head;
}

const PLAN_SCHEMA = {
  type: "object",
  properties: {
    interpreted_request: { type: "string" },
    priority_languages: { type: "array", items: { type: "string", enum: [...DEEP_SEARCH_LANGUAGE_CODES] } },
    queries: {
      type: "object",
      properties: Object.fromEntries(
        DEEP_SEARCH_LANGUAGE_CODES.map(code => [code, {
          type: "object",
          properties: {
            primary: { type: "string" },
            secondary: { type: "string" }
          },
          required: ["primary", "secondary"]
        }])
      ),
      required: [...DEEP_SEARCH_LANGUAGE_CODES]
    }
  },
  required: ["interpreted_request", "queries"]
};

const REPORT_SCHEMA = {
  type: "object",
  properties: {
    title: { type: "string" },
    analysis: { type: "string" }
  },
  required: ["title", "analysis"]
};

const PLAN_INSTRUCTION = `
You are the query-planning component of CT Atlas Deep Search, an authorised
multilingual OSINT research tool.

Interpret the analyst's exact free-text request and create EXACTLY TWO concise
Google News search queries in EACH of the 12 CT Atlas search languages (24 planned
queries total). Every Deep Search must search ALL 12 languages.

MANDATORY 12-LANGUAGE COVERAGE:
- en: English
- fr: French
- ar: Arabic
- de: German
- es: Spanish
- it: Italian
- tr: Turkish
- ru: Russian
- fa: Dari / Persian
- ur: Urdu
- he: Hebrew
- ps: Pashto

QUESTION ANALYSIS (do this before writing any query):
- Identify the core geography, actors and the underlying category of activity
  (terrorism, organised crime, narcotics, trafficking, financing, weapons,
  cybercrime, etc.).
- Identify well-established, directly relevant associated terms, synonyms,
  known actor/group names, methods or evidence types that an expert OSINT
  analyst would also search even when not explicitly named in the question —
  for example a question about maritime piracy off a given coast should also
  consider "hijacking", "hostage" or "ransom" as associated terms where
  relevant.
- Only use associated terms that are well-known and directly relevant. Do not
  invent specific group names, events or claims that are not either stated by
  the analyst or extremely well-established for the requested subject.
- Use this analysis to strengthen — not replace — the literal request when
  building each language's primary/secondary queries.

QUERY DESIGN RULES:
- Silently correct obvious spelling mistakes in the analyst request before making
  search terms.
- NEVER turn the analyst's whole request into one long sentence-like query.
- Each query should normally contain about 3-8 meaningful search terms or short
  phrases, plus the requested geography/actor where needed.
- primary = the broad/core subject of the request.
- secondary = a complementary facet, synonym set or action/evidence dimension
  drawing on the associated terms identified above.
- For multi-part requests, DISTRIBUTE requested facets across primary and secondary
  instead of requiring every concept in the same result.
- Keep the same information need in all 12 languages using natural local terms.
- Preserve precise geography and named actors. Do not drift into unrelated places.
- Adjacent countries are acceptable only for directly relevant routes, networks,
  seizures, cross-border operations or comparisons requested by the analyst.
- Use common synonyms/alternate spellings where they improve recall, but do not
  overload the query with every possible synonym.
- Prefer short, keyword-style terms over fluent grammatical sentences for
  languages with typically sparse news indexing (fa, ur, he, ps): a handful of
  natural local keywords matches published reporting better than a full phrase.

For narcotics research, split complex requests sensibly. One query may cover
cultivation/production/laboratories and the second trafficking/routes/networks/
seizures/decrees/enforcement.

If the analyst asks about narcotics, organised crime, smuggling, weapons,
cybercrime or another adjacent security topic, search it directly even when no
terrorism nexus is stated.

Set priority_languages to up to five supported languages: always include "en"
and "fr", plus up to three languages used locally in the requested countries.
Recognise country names in any language. For example: Afghanistan -> fa, ps, ur;
Egypt or another Arabic-speaking country -> ar; Iran -> fa; Pakistan -> ur;
Israel/Palestine -> he, ar. Arabic and every other required language remain
part of the full 12-language search regardless of priority_languages.

Return only the structured search plan. For every language key, return both
"primary" and "secondary". Do not answer the analyst's question yet.
`;

const REPORT_INSTRUCTION = `
You are CT Atlas Deep Search. Produce a professional OSINT analytical report that
answers the analyst's exact question from the supplied retrieved evidence only.

STRICT SCOPE:
- Stay tightly focused on the requested geography, actors, commodities and time
  period. Do not drift to unrelated countries merely because they appear in
  background reporting.
- A neighbouring country may be discussed only when it directly evidences a
  requested route, network, seizure, enforcement action or comparison.

EVIDENCE RULES:
- Use ONLY the supplied evidence records. Do not rely on outside knowledge.
- Every factual paragraph or bullet must contain one or more source citations
  exactly like [S01] or [S01, S04].
- Never cite a source ID that is not supplied.
- Preserve allegations and uncertainty. Do not turn claims into facts.
- If sources conflict, state the conflict and cite both sides.
- Do not invent quantities, identities, locations, attribution, motives, routes,
  chronology or trends.
- Search-result snippets can be incomplete; do not infer beyond them.
- If the evidence is insufficient for a requested point, say so explicitly.

FORMAT:
Use plain report text inside the "analysis" field, with real newline characters.
Do NOT put JSON, Markdown code fences, triple backticks or a second title/analysis
object inside the analysis field.

Use these headings when relevant:
EXECUTIVE ASSESSMENT
PRODUCTION / CULTIVATION
TRAFFICKING NETWORKS / ROUTES
ENFORCEMENT / DECREES
LABORATORY DESTRUCTION / SEIZURES
KEY EVENTS / FINDINGS
POTENTIAL CT ATLAS GAPS
SOURCE / CONFIDENCE NOTES

Use concise bullets beneath headings when that improves readability. Do not force
headings that are irrelevant.

The field atlas_status is an approximate machine comparison against CT Atlas.
"potential_gap" means only that no sufficiently similar map event was
automatically matched; it is not proof that CT Atlas missed the event.
`;

function decodeXml(value) {
  return String(value || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCharCode(parseInt(n, 16)));
}

function stripHtml(value) {
  return cleanText(decodeXml(String(value || "").replace(/<[^>]+>/g, " ")), 1000);
}

function tagValue(xml, tag) {
  const match = String(xml || "").match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}>`, "i"));
  return match ? decodeXml(match[1]).trim() : "";
}

function parseRss(xml, queryMeta, queryIndex, fallbackLocale = false) {
  const items = String(xml || "").match(/<item\b[\s\S]*?<\/item>/gi) || [];
  const rows = [];
  for (const item of items.slice(0, DEEP_SEARCH_RESULTS_PER_QUERY)) {
    const sourceMatch = item.match(/<source(?:\s[^>]*)?>([\s\S]*?)<\/source>/i);
    const source = cleanText(sourceMatch ? decodeXml(sourceMatch[1]) : "", 140);
    let title = cleanText(tagValue(item, "title"), 500);
    if (source && title.toLowerCase().endsWith((" - " + source).toLowerCase())) {
      title = title.slice(0, -(source.length + 3)).trim();
    }
    const url = cleanText(tagValue(item, "link"), 1200);
    const summary = stripHtml(tagValue(item, "description"));
    const publishedRaw = cleanText(tagValue(item, "pubDate"), 100);
    const publishedDate = publishedRaw ? new Date(publishedRaw) : null;
    if (!title || !url) continue;
    rows.push({
      title, summary, source: source || "Google News source", url,
      published: publishedDate && !Number.isNaN(publishedDate.getTime()) ? publishedDate.toISOString() : "",
      language: queryMeta.language,
      query_index: queryIndex,
      query_variant: queryMeta.variant || "primary",
      search_query: queryMeta.query,
      search_engine: "google_news",
      fallback_locale: Boolean(fallbackLocale)
    });
  }
  return rows;
}

function normalizeTitle(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/https?:\/\/\S+/g, " ")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\b(the|a|an|and|or|of|to|in|on|at|for|from|with|after|over|into|as|by|is|are|was|were|be|says|said|new|latest|report|reports|update|updates)\b/g, " ")
    .replace(/\s+/g, " ").trim();
}

function titleTokens(value) {
  return new Set(normalizeTitle(value).split(" ").filter(token => token.length >= 3));
}

function tokenSimilarity(a, b) {
  const aa = titleTokens(a), bb = titleTokens(b);
  if (!aa.size || !bb.size) return { jaccard: 0, containment: 0, shared: 0 };
  let shared = 0;
  for (const token of aa) if (bb.has(token)) shared++;
  const union = aa.size + bb.size - shared;
  return { jaccard: union ? shared / union : 0, containment: shared / Math.min(aa.size, bb.size), shared };
}

function dateDistanceDays(a, b) {
  const ad = a ? new Date(a) : null, bd = b ? new Date(b) : null;
  if (!ad || !bd || Number.isNaN(ad.getTime()) || Number.isNaN(bd.getTime())) return null;
  return Math.abs(ad.getTime() - bd.getTime()) / 86400000;
}

function deduplicateRows(rows) {
  const sorted = [...rows].sort((a, b) => new Date(b.published || 0) - new Date(a.published || 0));
  const clusters = [];
  for (const row of sorted) {
    const normalized = normalizeTitle(row.title);
    let match = null;
    for (const candidate of clusters) {
      const gap = dateDistanceDays(row.published, candidate.published);
      if (gap !== null && gap > 5) continue;
      if (row.url && candidate.url && row.url === candidate.url) { match = candidate; break; }
      if (normalized && normalized === candidate._normalized) { match = candidate; break; }
      const sim = tokenSimilarity(row.title, candidate.title);
      if (sim.shared >= 4 && (sim.jaccard >= 0.62 || sim.containment >= 0.78)) { match = candidate; break; }
    }
    if (!match) {
      clusters.push({ ...row, _normalized: normalized, sources: [{ source: row.source, url: row.url, language: row.language, published: row.published, search_engine: row.search_engine || "google_news" }] });
    } else {
      if (!match.sources.some(item => item.url === row.url)) {
        match.sources.push({ source: row.source, url: row.url, language: row.language, published: row.published, search_engine: row.search_engine || "google_news" });
      }
      if ((row.summary || "").length > (match.summary || "").length) match.summary = row.summary;
    }
  }
  return clusters.map(({ _normalized, ...row }) => row);
}

function googleNewsUrl(query, locale, periodDays) {
  const term = `${cleanText(query, 220)} when:${periodDays}d`;
  return "https://news.google.com/rss/search?" + new URLSearchParams({
    q: term, hl: locale.hl, gl: locale.gl, ceid: locale.ceid
  }).toString();
}

async function callGeminiJson(env, instruction, input, schema, maxOutputTokens) {
  const response = await fetch(GEMINI_URL, {
    method: "POST",
    headers: { "x-goog-api-key": env.GEMINI_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: DEEP_SEARCH_MODEL,
      input,
      system_instruction: instruction,
      store: false,
      response_format: { type: "text", mime_type: "application/json", schema },
      generation_config: { max_output_tokens: maxOutputTokens, thinking_level: "minimal" }
    })
  });
  if (response.status === 429) {
    const error = new Error("Gemini quota/capacity temporarily unavailable for Deep Search (429). Please retry later.");
    error.code = 429; throw error;
  }
  if (!response.ok) throw new Error(`Gemini Deep Search error ${response.status}: ${cleanText(await response.text(), 600)}`);
  const payload = await response.json();
  const raw = (await extractGeminiText(payload)).trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "");
  return JSON.parse(raw);
}

function sanitizePlan(plan, fallbackQuestion) {
  const queries = [];
  const raw = plan?.queries && typeof plan.queries === "object" && !Array.isArray(plan.queries)
    ? plan.queries
    : {};

  const missing = [];
  for (const language of DEEP_SEARCH_LANGUAGE_CODES) {
    const item = raw[language];
    const primary = cleanText(item?.primary, 220);
    const secondary = cleanText(item?.secondary, 220);
    if (!primary || !secondary) {
      missing.push(language);
      continue;
    }
    queries.push({ language, query: primary, variant: "primary" });
    queries.push({ language, query: secondary, variant: "secondary" });
  }

  if (missing.length) {
    throw new Error(
      "Deep Search planner did not return two usable queries for every required language: " +
      missing.join(", ")
    );
  }

  return {
    interpreted_request: cleanText(plan?.interpreted_request || fallbackQuestion, 700),
    priority_languages: (Array.isArray(plan?.priority_languages) ? plan.priority_languages : []).filter(code => DEEP_SEARCH_LANGUAGE_CODES.includes(code)).slice(0, PRIORITY_LANGUAGE_CAP),
    queries: queries.slice(0, DEEP_SEARCH_MAX_QUERIES)
  };
}

async function fetchNewsWave(item, index, periodDays, locale, fallbackLocale = false) {
  try {
    const response = await fetch(googleNewsUrl(item.query, locale, periodDays), {
      headers: { "User-Agent": "Mozilla/5.0 CT-Atlas-Deep-Search/5.0" },
      cf: { cacheTtl: 300, cacheEverything: true },
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) {
      return { query: { ...item, fallback_locale: fallbackLocale }, ok: false, status: response.status, rows: [] };
    }
    const xml = await response.text();
    if (!/<rss[\s>]/i.test(xml) || !/<channel[\s>]/i.test(xml)) {
      return { query: { ...item, fallback_locale: fallbackLocale }, ok: false,
        status: response.status, error: "Search provider returned non-RSS content", rows: [] };
    }
    return {
      query: { ...item, fallback_locale: fallbackLocale },
      ok: true,
      status: response.status,
      rows: parseRss(xml, item, index, fallbackLocale)
    };
  } catch (error) {
    return {
      query: { ...item, fallback_locale: fallbackLocale },
      ok: false,
      status: 0,
      error: cleanText(error?.message, 180),
      rows: []
    };
  }
}

function gdeltUrl(query, language, periodDays) {
  const lang = GDELT_LANGUAGE_FILTERS[language] || language;
  const timespan = periodDays >= 365 ? "1y" : `${periodDays}d`;
  return GDELT_DOC_URL + "?" + new URLSearchParams({
    query: `${cleanText(query, 280)} sourcelang:${lang}`,
    mode: "artlist",
    format: "json",
    maxrecords: String(GDELT_RESULTS_PER_LANGUAGE),
    timespan
  }).toString();
}

function parseGdeltDate(value) {
  const raw = String(value || "").trim();
  const digits = raw.replace(/\D/g, "");
  if (digits.length >= 14) {
    const iso = `${digits.slice(0,4)}-${digits.slice(4,6)}-${digits.slice(6,8)}T${digits.slice(8,10)}:${digits.slice(10,12)}:${digits.slice(12,14)}Z`;
    const dt = new Date(iso);
    if (!Number.isNaN(dt.getTime())) return dt.toISOString();
  }
  const dt = raw ? new Date(raw) : null;
  return dt && !Number.isNaN(dt.getTime()) ? dt.toISOString() : "";
}

function parseGdeltArticles(payload, language, query) {
  const articles = Array.isArray(payload?.articles) ? payload.articles : [];
  return articles.slice(0, GDELT_RESULTS_PER_LANGUAGE).map(article => {
    const title = cleanText(article?.title, 500);
    const url = cleanText(article?.url || article?.url_mobile, 1200);
    if (!title || !url) return null;
    return {
      title,
      summary: "",
      source: cleanText(article?.domain || article?.sourcecountry || "GDELT source", 140),
      url,
      published: parseGdeltDate(article?.seendate),
      language,
      query_index: -1,
      query_variant: "gdelt-rescue",
      search_query: query,
      search_engine: "gdelt",
      fallback_locale: false
    };
  }).filter(Boolean);
}

async function fetchGdeltWave(language, query, periodDays) {
  try {
    const response = await fetch(gdeltUrl(query, language, periodDays), {
      headers: { "User-Agent": "Mozilla/5.0 CT-Atlas-Deep-Search/5.5" },
      cf: { cacheTtl: 300, cacheEverything: true },
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) {
      return { query: { language, query, variant: "gdelt-rescue", engine: "gdelt" }, ok: false, status: response.status, rows: [] };
    }
    const payload = await response.json().catch(() => ({}));
    return {
      query: { language, query, variant: "gdelt-rescue", engine: "gdelt" },
      ok: true,
      status: response.status,
      rows: parseGdeltArticles(payload, language, query)
    };
  } catch (error) {
    return {
      query: { language, query, variant: "gdelt-rescue", engine: "gdelt" },
      ok: false,
      status: 0,
      error: cleanText(error?.message, 180),
      rows: []
    };
  }
}

async function retrieveNews(plan, periodDays, priorityLanguages = []) {
  // Bound search below Cloudflare Free's 50-subrequest ceiling:
  // 24 Google News + max 5 priority Google rescues + max 9 GDELT = max 38.
  const googleWaves = await Promise.all(
    [...plan.queries].sort((a,b) => Number(priorityLanguages.includes(b.language))-Number(priorityLanguages.includes(a.language))).map((item, index) =>
      fetchNewsWave(item, index, periodDays, LANGUAGE_LOCALES[item.language], false)
    )
  );

  const totals = Object.fromEntries(DEEP_SEARCH_LANGUAGE_CODES.map(code => [code, new Set()]));
  for (const wave of googleWaves) {
    for (const row of wave.rows) totals[wave.query.language].add(row.url);
  }

  // Country-relevant languages get one extra native-language query through the
  // stable en-US Google edition if the local edition returned fewer than 3 items.
  const priorityRescueItems = [];
  for (const language of priorityLanguages.slice(0, PRIORITY_LANGUAGE_CAP)) {
    if ((totals[language]?.size || 0) >= 3) continue;
    const candidate = plan.queries.find(item => item.language === language && item.variant === "primary")
      || plan.queries.find(item => item.language === language);
    if (candidate) priorityRescueItems.push({ ...candidate, variant: "priority-locale-rescue" });
  }
  const priorityRescueWaves = await Promise.all(
    priorityRescueItems.map((item, index) =>
      fetchNewsWave(item, googleWaves.length + index, periodDays, SEARCH_FALLBACK_LOCALE, true)
    )
  );

  const googleAll = [...googleWaves, ...priorityRescueWaves];
  const afterGoogle = Object.fromEntries(DEEP_SEARCH_LANGUAGE_CODES.map(code => [code, new Set()]));
  for (const wave of googleAll) {
    for (const row of wave.rows) afterGoogle[wave.query.language].add(row.url);
  }

  // GDELT rescues priority languages first, then other sparse languages.
  const gdeltQuery = broadGdeltQuery(plan);
  const sparse = DEEP_SEARCH_LANGUAGE_CODES.filter(code => (afterGoogle[code]?.size || 0) < 3);
  const gdeltLanguages = [...new Set([...priorityLanguages, ...sparse])]
    .filter(code => DEEP_SEARCH_LANGUAGE_CODES.includes(code))
    .slice(0, 9);
  const gdeltWaves = [];
  if (gdeltQuery) {
    for (let i = 0; i < gdeltLanguages.length; i += 3) {
      const batch = gdeltLanguages.slice(i, i + 3);
      const results = await Promise.all(batch.map(code => fetchGdeltWave(code, gdeltQuery, periodDays)));
      gdeltWaves.push(...results);
      if (i + 3 < gdeltLanguages.length) await new Promise(resolve => setTimeout(resolve, 250));
    }
  }

  const waves = [...googleAll, ...gdeltWaves];
  return {
    waves,
    rows: waves.flatMap(item => item.rows),
    priority_languages: priorityLanguages,
    subrequest_budget: {
      google_news_requests: googleAll.length,
      gdelt_requests: gdeltWaves.length,
      search_requests: googleAll.length + gdeltWaves.length,
      max_search_requests: 36
    }
  };
}

function candidateMapEvents(db, periodDays) {
  const all = Array.isArray(db) ? db : (Array.isArray(db?.events) ? db.events : []);
  const cutoff = Date.now() - (Math.min(365, periodDays + 14) * 86400000);
  return all.filter(event => {
    const raw = event?.event_date || event?.occurrence_date || event?.published || event?.last_reported;
    if (!raw) return true;
    const dt = new Date(raw);
    return Number.isNaN(dt.getTime()) || dt.getTime() >= cutoff;
  }).map(event => ({
    id: String(event?.id || event?._mapKey || ""),
    title: cleanText(event?.title, 500),
    original_title: cleanText(event?.original_title, 500),
    url: cleanText(event?.url, 1200),
    published: String(event?.event_date || event?.occurrence_date || event?.published || ""),
    country: cleanText(event?.country, 100)
  }));
}

function compareWithAtlas(rows, mapEvents) {
  return rows.map(row => {
    let best = null, bestScore = 0;
    for (const event of mapEvents) {
      const gap = dateDistanceDays(row.published, event.published);
      if (gap !== null && gap > 7) continue;
      if (row.url && event.url && row.url === event.url) { best = event; bestScore = 1; break; }
      for (const candidateTitle of [event.title, event.original_title]) {
        if (!candidateTitle) continue;
        if (normalizeTitle(row.title) === normalizeTitle(candidateTitle)) { best = event; bestScore = 0.99; break; }
        const sim = tokenSimilarity(row.title, candidateTitle);
        const score = Math.max(sim.jaccard, sim.containment * 0.9);
        if (sim.shared >= 4 && score > bestScore) { best = event; bestScore = score; }
      }
      if (bestScore >= 0.90) break;
    }
    const matched = best && bestScore >= 0.64;
    return {
      ...row,
      atlas_status: matched ? "already_in_atlas" : "potential_gap",
      atlas_match_id: matched ? best.id : "",
      atlas_match_title: matched ? best.title : "",
      atlas_match_score: matched ? Math.round(bestScore * 100) : 0
    };
  });
}

function searchRelevance(row) {
  const query = cleanText(row.search_query, 220);
  if (!query) return 0;
  const combined = `${row.title || ""} ${row.summary || ""}`;
  const sim = tokenSimilarity(combined, query);
  return Math.min(30, (sim.containment * 22) + Math.min(8, sim.shared) * 1.4);
}

function evidencePriority(row) {
  let score = searchRelevance(row);
  const published = row.published ? new Date(row.published) : null;
  if (published && !Number.isNaN(published.getTime())) {
    const ageDays = Math.max(0, (Date.now() - published.getTime()) / 86400000);
    score += Math.max(0, 32 - ageDays * 0.35);
  }
  score += Math.min(18, (row.sources?.length || 1) * 4.5);
  if (row.atlas_status === "potential_gap") score += 3;
  if (/justice|interpol|europol|government|police|treasury|ministry|prosecut|united nations|unodc|customs|counter narcotics|interior/i.test(row.source || "")) score += 9;
  return score;
}

function buildEvidence(rows, priorityLanguages = []) {
  const ranked = [...rows].sort((a, b) => evidencePriority(b) - evidencePriority(a));
  const selected = [];
  const used = new Set();

  // Protect two evidence slots per country-priority language when available.
  for (const language of priorityLanguages) {
    for (let take = 0; take < 2 && selected.length < DEEP_SEARCH_MAX_EVIDENCE; take++) {
      const index = ranked.findIndex((row, i) => !used.has(i) && row.language === language);
      if (index < 0) break;
      selected.push(ranked[index]);
      used.add(index);
    }
  }

  // Then preserve at least one item from every other language when available.
  for (const language of DEEP_SEARCH_LANGUAGE_CODES) {
    if (selected.some(row => row.language === language)) continue;
    const index = ranked.findIndex((row, i) => !used.has(i) && row.language === language);
    if (index >= 0 && selected.length < DEEP_SEARCH_MAX_EVIDENCE) {
      selected.push(ranked[index]);
      used.add(index);
    }
  }
  ranked.forEach((row, index) => {
    if (selected.length >= DEEP_SEARCH_MAX_EVIDENCE || used.has(index)) return;
    selected.push(row);
    used.add(index);
  });

  return selected.map((row, index) => ({
    id: `S${String(index + 1).padStart(2, "0")}`,
    title: cleanText(row.title, 420), summary: cleanText(row.summary, 650),
    source: cleanText(row.source, 140), url: cleanText(row.url, 1200),
    published: row.published, language: row.language,
    query_variant: row.query_variant || "primary",
    search_query: cleanText(row.search_query, 280),
    search_engine: row.search_engine || "google_news",
    fallback_locale: Boolean(row.fallback_locale),
    source_count: row.sources?.length || 1,
    additional_sources: (row.sources || []).slice(1, 5).map(source => ({
      source: cleanText(source.source, 140), url: cleanText(source.url, 1200),
      language: source.language, published: source.published,
      search_engine: source.search_engine || "google_news"
    })),
    atlas_status: row.atlas_status, atlas_match_id: row.atlas_match_id,
    atlas_match_title: row.atlas_match_title, atlas_match_score: row.atlas_match_score
  }));
}

function unwrapGeneratedReport(generated) {
  let title = cleanText(generated?.title || "", 180);
  let analysis = String(generated?.analysis || "").trim();

  for (let pass = 0; pass < 2; pass++) {
    const candidate = analysis.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
    if (!(candidate.startsWith("{") && candidate.endsWith("}"))) break;
    try {
      const nested = JSON.parse(candidate);
      if (!nested || typeof nested !== "object" || !nested.analysis) break;
      title = cleanText(nested.title || title, 180);
      analysis = String(nested.analysis || "").trim();
    } catch (_) { break; }
  }

  if (!analysis.includes("\n") && /\\n/.test(analysis)) {
    analysis = analysis.replace(/\\n/g, "\n").replace(/\\"/g, '"');
  }
  analysis = analysis.replace(/^```(?:json|text|markdown)?\s*/i, "").replace(/\s*```$/i, "").trim();
  return { title, analysis };
}

function citationMetrics(analysis, evidence) {
  const valid = new Set(evidence.map(item => item.id)), cited = new Set();
  for (const match of String(analysis || "").matchAll(/\[(S\d{2})(?:,\s*S\d{2})*\]/g)) {
    const ids = match[0].match(/S\d{2}/g) || [];
    ids.forEach(id => { if (valid.has(id)) cited.add(id); });
  }
  const paragraphs = String(analysis || "").split(/\n+/).map(v => v.trim())
    .filter(v => v && !/^[A-Z][A-Z /&-]{4,}$/.test(v));
  const factual = paragraphs.filter(v => v.length >= 35);
  const grounded = factual.filter(v => /\[S\d{2}/.test(v));
  return {
    cited_source_ids: [...cited],
    citation_coverage_percent: factual.length ? Math.round(grounded.length / factual.length * 100) : 100,
    cited_sources: cited.size,
    factual_paragraphs: factual.length,
    cited_factual_paragraphs: grounded.length
  };
}

function languageDiagnostics(plan, retrieval, priorityLanguages = []) {
  const byLanguage = {};
  for (const code of DEEP_SEARCH_LANGUAGE_CODES) {
    byLanguage[code] = {
      code,
      name: LANGUAGE_LOCALES[code]?.label || code,
      query_count: 0,
      article_count: 0,
      successful_queries: 0,
      google_news_articles: 0,
      gdelt_articles: 0,
      priority: priorityLanguages.includes(code)
    };
  }
  for (const wave of retrieval.waves) {
    const code = wave.query.language;
    if (!byLanguage[code]) continue;
    byLanguage[code].query_count++;
    byLanguage[code].article_count += wave.rows.length;
    if (wave.ok) byLanguage[code].successful_queries++;
    const engine = wave.query.engine || (wave.query.variant === "gdelt-rescue" ? "gdelt" : "google_news");
    if (engine === "gdelt") byLanguage[code].gdelt_articles += wave.rows.length;
    else byLanguage[code].google_news_articles += wave.rows.length;
  }
  return Object.values(byLanguage);
}

async function authenticateDeepSearch(request, body, env) {
  const username = normalizeUsername(body.user_id || body.username);
  const token = cleanText(request.headers.get("X-Session-Token"), 160);
  if (!username || !isAllowedUser(username)) return { error: jsonResponse({ error: "Unknown or missing user." }, 400, env) };
  if (!token) return { error: jsonResponse({ error: "Authenticated session required. Please sign in again." }, 401, env) };
  const sessionResponse = await gateCall(env, "/session-get", { session_token: token });
  const session = await sessionResponse.json().catch(() => ({}));
  if (!sessionResponse.ok || session?.username !== username) return { error: jsonResponse({ error: "Unauthorized session." }, 401, env) };
  return { username };
}

export async function handleDeepSearch(request, env, ctx) {
  let body;
  try { body = await request.json(); } catch { return jsonResponse({ error: "Invalid JSON request." }, 400, env); }

  const auth = await authenticateDeepSearch(request, body, env);
  if (auth.error) return auth.error;

  const question = cleanText(body.question, 1200);
  const periodDays = Number(body.period_days || 30);
  if (question.length < 8) return jsonResponse({ error: "Enter a more specific Deep Search question." }, 400, env);
  if (!DEEP_SEARCH_ALLOWED_PERIODS.has(periodDays)) return jsonResponse({ error: "Unsupported Deep Search period." }, 400, env);

  const username = auth.username;
  const cacheKey = await sha256(JSON.stringify({
    question: question.toLowerCase(), periodDays, version: DEEP_SEARCH_VERSION
  }));

  const permitResponse = await gateCall(env, "/acquire", { username });
  const permit = await permitResponse.json().catch(() => ({}));
  if (!permitResponse.ok || !permit?.permit_id) {
    return jsonResponse({
      error: permit?.error || "Deep Search capacity temporarily unavailable.",
      retry_after_seconds: permit?.retry_after_seconds || 20
    }, permitResponse.status || 429, env);
  }
  const permitId = permit.permit_id;

  try {
    const cachedResponse = await gateCall(env, "/cache-get", { cacheKey: "deep:" + cacheKey });
    const cached = await cachedResponse.json().catch(() => ({}));
    if (cached?.hit && cached?.report) {
      const commitResponse = await gateCall(env, "/commit-report", { permitId, username });
      if (!commitResponse.ok) throw new Error("Unable to finalize Deep Search allowance.");
      return jsonResponse({ ...cached.report, cached: true }, 200, env);
    }

    const planRaw = await callGeminiJson(
      env, PLAN_INSTRUCTION,
      `Analyst question: ${question}\nTime window: last ${periodDays} days.`,
      PLAN_SCHEMA, 6000
    );
    const plan = sanitizePlan(planRaw, question);
    if (!plan.queries.length) return jsonResponse({ error: "Deep Search could not create a usable multilingual search plan." }, 422, env);

    const priorityLanguages = resolvePriorityLanguages(question, plan.priority_languages || []);
    const retrieval = await retrieveNews(plan, periodDays, priorityLanguages);
    const unique = deduplicateRows(retrieval.rows);
    const languagesSearched = languageDiagnostics(plan, retrieval, priorityLanguages);

    if (!unique.length) {
      return jsonResponse({
        error: "Deep Search found no usable open-source reporting for this question and period.",
        languages_searched: languagesSearched,
        search_queries: retrieval.waves.map(w => ({ ...w.query, ok: w.ok, status: w.status, result_count: w.rows.length }))
      }, 422, env);
    }

    let db = { events: [] }, databaseVersion = "unavailable";
    try {
      const dbResponse = await fetch(env.EVENTS_URL, { cf: { cacheTtl: 60, cacheEverything: true } });
      if (dbResponse.ok) {
        db = await dbResponse.json();
        databaseVersion = cleanText(db.updated_at || db.generated_at || db.last_updated || "unknown", 100);
      }
    } catch (_) {}

    const compared = compareWithAtlas(unique, candidateMapEvents(db, periodDays));
    const evidence = buildEvidence(compared, priorityLanguages);
    const dataset = {
      analyst_question: question,
      interpreted_request: plan.interpreted_request,
      period_days: periodDays,
      database_version: databaseVersion,
      language_search_coverage: languagesSearched,
      priority_languages: priorityLanguages,
      evidence
    };

    const generatedRaw = await callGeminiJson(
      env, REPORT_INSTRUCTION,
      "Answer the analyst question using only this Deep Search evidence dataset:\n\n" + JSON.stringify(dataset),
      REPORT_SCHEMA, 9000
    );
    const generated = unwrapGeneratedReport(generatedRaw);
    if (!generated.analysis) throw new Error("Deep Search generated an empty analytical report.");

    const metrics = citationMetrics(generated.analysis, evidence);
    const gaps = evidence.filter(item => item.atlas_status === "potential_gap").length;
    const inAtlas = evidence.length - gaps;
    const successfulQueries = retrieval.waves.filter(item => item.ok).length;

    const report = {
      title: generated.title || "CT Atlas Deep Search",
      analysis: generated.analysis,
      question,
      interpreted_request: plan.interpreted_request,
      period_days: periodDays,
      generated_at: new Date().toISOString(),
      database_version: databaseVersion,
      model: DEEP_SEARCH_MODEL,
      version: DEEP_SEARCH_VERSION,
      languages_searched: languagesSearched,
      priority_languages: priorityLanguages,
      search_queries: retrieval.waves.map(w => ({
        language: w.query.language, query: w.query.query,
        variant: w.query.variant,
        engine: w.query.engine || (w.query.variant === "gdelt-rescue" ? "gdelt" : "google_news"),
        fallback_locale: Boolean(w.query.fallback_locale),
        error: w.error || "",
        ok: w.ok, status: w.status, result_count: w.rows.length
      })),
      retrieval: {
        queries_planned: plan.queries.length,
        queries_attempted: retrieval.waves.length,
        queries_successful: successfulQueries,
        articles_retrieved: retrieval.rows.length,
        unique_event_clusters: unique.length,
        evidence_events_used_for_analysis: evidence.length,
        matched_to_atlas: inAtlas,
        potential_atlas_gaps: gaps,
        google_news_articles: retrieval.rows.filter(row => row.search_engine === "google_news").length,
        gdelt_articles: retrieval.rows.filter(row => row.search_engine === "gdelt").length,
        search_subrequests: retrieval.subrequest_budget?.search_requests || retrieval.waves.length
      },
      grounding: {
        ...metrics,
        note: "Citation coverage measures visible source citation coverage; it is not a statistical probability of hallucination."
      },
      evidence
    };

    await gateCall(env, "/cache-put", {
      cacheKey: "deep:" + cacheKey, report,
      expires_at: Date.now() + DEEP_SEARCH_CACHE_TTL_MS
    });

    const commitResponse = await gateCall(env, "/commit-report", { permitId, username });
    if (!commitResponse.ok) {
      const commitError = await commitResponse.json().catch(() => ({}));
      throw new Error(commitError?.error || "Unable to finalize Deep Search allowance.");
    }

    return jsonResponse({ ...report, cached: false }, 200, env);
  } catch (error) {
    console.error("Deep Search failure", error);
    const status = Number(error?.code) === 429 ? 429 : 503;
    return jsonResponse({
      error: cleanText(error?.message || "Deep Search failed.", 400),
      ...(status === 429 ? { retry_after_seconds: 300 } : {})
    }, status, env);
  } finally {
    ctx.waitUntil(gateCall(env, "/release", { permitId, username }));
  }
}
