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

const DEEP_SEARCH_ALLOWED_PERIODS = new Set([7, 30, 90, 180]);
const DEEP_SEARCH_MAX_QUERIES = 7;
const DEEP_SEARCH_RESULTS_PER_QUERY = 35;
const DEEP_SEARCH_MAX_EVIDENCE = 48;
const DEEP_SEARCH_CACHE_TTL_MS = 4 * 60 * 60 * 1000;
const DEEP_SEARCH_MODEL = "gemini-3.5-flash-lite";

const LANGUAGE_LOCALES = Object.freeze({
  en: { label: "English", hl: "en-US", gl: "US", ceid: "US:en" },
  fr: { label: "French", hl: "fr", gl: "FR", ceid: "FR:fr" },
  ar: { label: "Arabic", hl: "ar", gl: "SA", ceid: "SA:ar" },
  de: { label: "German", hl: "de", gl: "DE", ceid: "DE:de" },
  es: { label: "Spanish", hl: "es", gl: "ES", ceid: "ES:es" },
  it: { label: "Italian", hl: "it", gl: "IT", ceid: "IT:it" },
  tr: { label: "Turkish", hl: "tr", gl: "TR", ceid: "TR:tr" },
  ru: { label: "Russian", hl: "ru", gl: "RU", ceid: "RU:ru" },
  fa: { label: "Persian / Dari", hl: "fa", gl: "IR", ceid: "IR:fa" },
  ur: { label: "Urdu", hl: "ur", gl: "PK", ceid: "PK:ur" },
  he: { label: "Hebrew", hl: "he", gl: "IL", ceid: "IL:he" },
  ps: { label: "Pashto", hl: "en-US", gl: "US", ceid: "US:en" }
});

const PLAN_SCHEMA = {
  type: "object",
  properties: {
    interpreted_request: { type: "string" },
    queries: {
      type: "array",
      maxItems: DEEP_SEARCH_MAX_QUERIES,
      items: {
        type: "object",
        properties: {
          language: {
            type: "string",
            enum: Object.keys(LANGUAGE_LOCALES)
          },
          query: { type: "string" }
        },
        required: ["language", "query"]
      }
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
counter-terrorism OSINT research tool.

Interpret the analyst's free-text question and create a compact multilingual
Google News search plan. Use only the supplied language codes. Always include
English, and add the most relevant local/regional languages for the geography,
actor or subject. Use 4-7 queries total, not one query per possible language.

Each query must be short enough for a news search engine, should preserve named
actors/organisations/places from the analyst request, and should use natural
search terms in that language. Include operational synonyms where useful, e.g.
attack/arrest/plot/financing/propaganda/piracy, but do not broaden a precise
question into unrelated CT topics.

CT Atlas focuses on non-state terrorist/extremist actors and counter-terrorism
responses. Do not broaden the task into ordinary interstate war or diplomacy
unless the analyst explicitly asks for that context. Maritime piracy is in scope
without a terrorism nexus.

Return only the JSON search plan. Do not answer the analyst's question yet.
`;

const REPORT_INSTRUCTION = `
You are CT Atlas Deep Search. Produce a concise professional counter-terrorism
OSINT research report answering the analyst's exact question from the supplied
retrieved evidence only.

CRITICAL EVIDENCE RULES:
- Use ONLY the supplied evidence records. Do not rely on outside knowledge.
- Every factual paragraph must contain one or more source citations in the exact
  form [S01], [S02], etc.
- Never cite a source ID that is not supplied.
- If sources conflict, state the conflict and cite both sides.
- Preserve allegations, claims and uncertainty. Do not turn claims into facts.
- Do not invent casualty figures, identities, locations, attribution, motives,
  coordination, chronology or trends.
- Search-result snippets can be incomplete; do not infer beyond them.
- If evidence is insufficient to answer part of the question, say so explicitly.

The field atlas_status is a machine-generated approximate comparison against the
current CT Atlas database. "potential_gap" means only that no sufficiently
similar map event was automatically matched. It is NOT proof that CT Atlas
missed the event. Discuss potential gaps only in the dedicated final section.

Use these headings when relevant:
EXECUTIVE ASSESSMENT
KEY EVENTS / FINDINGS
GEOGRAPHIC / ACTOR PATTERNS
COUNTER-TERRORISM RESPONSE
POTENTIAL CT ATLAS GAPS
SOURCE / CONFIDENCE NOTES

Do not force a heading if the evidence does not support it. Keep the report
focused on the analyst question rather than producing a generic terrorism brief.
Return JSON with title and analysis only.
`;

function decodeXml(value) {
  return String(value || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCharCode(parseInt(n, 16)));
}

function stripHtml(value) {
  return cleanText(
    decodeXml(String(value || "").replace(/<[^>]+>/g, " ")),
    1000
  );
}

function tagValue(xml, tag) {
  const match = String(xml || "").match(
    new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}>`, "i")
  );
  return match ? decodeXml(match[1]).trim() : "";
}

function parseRss(xml, language, queryIndex) {
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
      title,
      summary,
      source: source || "Google News source",
      url,
      published: publishedDate && !Number.isNaN(publishedDate.getTime())
        ? publishedDate.toISOString()
        : "",
      language,
      query_index: queryIndex
    });
  }
  return rows;
}

function normalizeTitle(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\b(the|a|an|and|or|of|to|in|on|at|for|from|with|after|over|into|as|by|is|are|was|were|be|says|said|new|latest|report|reports|update|updates)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function titleTokens(value) {
  return new Set(
    normalizeTitle(value)
      .split(" ")
      .filter(token => token.length >= 3)
  );
}

function tokenSimilarity(a, b) {
  const aa = titleTokens(a);
  const bb = titleTokens(b);
  if (!aa.size || !bb.size) return { jaccard: 0, containment: 0, shared: 0 };
  let shared = 0;
  for (const token of aa) if (bb.has(token)) shared++;
  const union = aa.size + bb.size - shared;
  return {
    jaccard: union ? shared / union : 0,
    containment: shared / Math.min(aa.size, bb.size),
    shared
  };
}

function dateDistanceDays(a, b) {
  const ad = a ? new Date(a) : null;
  const bd = b ? new Date(b) : null;
  if (!ad || !bd || Number.isNaN(ad.getTime()) || Number.isNaN(bd.getTime())) return null;
  return Math.abs(ad.getTime() - bd.getTime()) / 86400000;
}

function deduplicateRows(rows) {
  const sorted = [...rows].sort((a, b) =>
    new Date(b.published || 0).getTime() - new Date(a.published || 0).getTime()
  );
  const clusters = [];

  for (const row of sorted) {
    const normalized = normalizeTitle(row.title);
    let match = null;
    for (const candidate of clusters) {
      const gap = dateDistanceDays(row.published, candidate.published);
      if (gap !== null && gap > 5) continue;
      if (normalized && normalized === candidate._normalized) {
        match = candidate;
        break;
      }
      const sim = tokenSimilarity(row.title, candidate.title);
      if (sim.shared >= 4 && (sim.jaccard >= 0.62 || sim.containment >= 0.78)) {
        match = candidate;
        break;
      }
    }

    if (!match) {
      clusters.push({
        ...row,
        _normalized: normalized,
        sources: [{ source: row.source, url: row.url, language: row.language, published: row.published }]
      });
      continue;
    }

    if (!match.sources.some(item => item.url === row.url)) {
      match.sources.push({ source: row.source, url: row.url, language: row.language, published: row.published });
    }
    if ((row.summary || "").length > (match.summary || "").length) match.summary = row.summary;
  }

  return clusters.map(({ _normalized, ...row }) => row);
}

function googleNewsUrl(query, locale, periodDays) {
  const term = `${cleanText(query, 420)} when:${periodDays}d`;
  return "https://news.google.com/rss/search?" + new URLSearchParams({
    q: term,
    hl: locale.hl,
    gl: locale.gl,
    ceid: locale.ceid
  }).toString();
}

async function callGeminiJson(env, instruction, input, schema, maxOutputTokens) {
  const body = {
    model: DEEP_SEARCH_MODEL,
    input,
    system_instruction: instruction,
    store: false,
    response_format: {
      type: "text",
      mime_type: "application/json",
      schema
    },
    generation_config: {
      max_output_tokens: maxOutputTokens,
      thinking_level: "minimal"
    }
  };

  const response = await fetch(GEMINI_URL, {
    method: "POST",
    headers: {
      "x-goog-api-key": env.GEMINI_API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (response.status === 429) {
    const error = new Error("Gemini quota/capacity temporarily unavailable for Deep Search (429). Please retry later.");
    error.code = 429;
    throw error;
  }
  if (!response.ok) {
    throw new Error(`Gemini Deep Search error ${response.status}: ${cleanText(await response.text(), 600)}`);
  }

  const payload = await response.json();
  const raw = (await extractGeminiText(payload))
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/i, "");
  return JSON.parse(raw);
}

function sanitizePlan(plan, fallbackQuestion) {
  const queries = [];
  const seen = new Set();
  for (const item of Array.isArray(plan?.queries) ? plan.queries : []) {
    const language = String(item?.language || "").toLowerCase();
    const query = cleanText(item?.query, 420);
    if (!LANGUAGE_LOCALES[language] || !query) continue;
    const key = language + "|" + query.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    queries.push({ language, query });
    if (queries.length >= DEEP_SEARCH_MAX_QUERIES) break;
  }
  if (!queries.some(item => item.language === "en")) {
    queries.unshift({ language: "en", query: cleanText(fallbackQuestion, 420) });
  }
  return {
    interpreted_request: cleanText(plan?.interpreted_request || fallbackQuestion, 700),
    queries: queries.slice(0, DEEP_SEARCH_MAX_QUERIES)
  };
}

async function retrieveNews(plan, periodDays) {
  const tasks = plan.queries.map(async (item, index) => {
    const locale = LANGUAGE_LOCALES[item.language];
    const url = googleNewsUrl(item.query, locale, periodDays);
    try {
      const response = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 CT-Atlas-Deep-Search/1.0" },
        cf: { cacheTtl: 300, cacheEverything: true }
      });
      if (!response.ok) {
        return { query: item, ok: false, status: response.status, rows: [] };
      }
      return {
        query: item,
        ok: true,
        status: response.status,
        rows: parseRss(await response.text(), item.language, index)
      };
    } catch (error) {
      return { query: item, ok: false, status: 0, error: cleanText(error?.message, 180), rows: [] };
    }
  });

  const waves = await Promise.all(tasks);
  const rows = waves.flatMap(item => item.rows);
  return { waves, rows };
}

function candidateMapEvents(db, periodDays) {
  const all = Array.isArray(db) ? db : (Array.isArray(db?.events) ? db.events : []);
  const cutoff = Date.now() - (Math.min(180, periodDays + 14) * 86400000);
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
    let best = null;
    let bestScore = 0;
    for (const event of mapEvents) {
      const gap = dateDistanceDays(row.published, event.published);
      if (gap !== null && gap > 7) continue;
      if (row.url && event.url && row.url === event.url) {
        best = event;
        bestScore = 1;
        break;
      }
      for (const candidateTitle of [event.title, event.original_title]) {
        if (!candidateTitle) continue;
        if (normalizeTitle(row.title) === normalizeTitle(candidateTitle)) {
          best = event;
          bestScore = 0.99;
          break;
        }
        const sim = tokenSimilarity(row.title, candidateTitle);
        const score = Math.max(sim.jaccard, sim.containment * 0.9);
        if (sim.shared >= 4 && score > bestScore) {
          best = event;
          bestScore = score;
        }
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

function evidencePriority(row) {
  let score = 0;
  const published = row.published ? new Date(row.published) : null;
  if (published && !Number.isNaN(published.getTime())) {
    const ageDays = Math.max(0, (Date.now() - published.getTime()) / 86400000);
    score += Math.max(0, 40 - ageDays * 0.6);
  }
  score += Math.min(20, (row.sources?.length || 1) * 5);
  if (row.atlas_status === "potential_gap") score += 3;
  if (/justice|interpol|europol|government|police|treasury|ministry|prosecut/i.test(row.source || "")) score += 7;
  return score;
}

function buildEvidence(rows) {
  const selected = [...rows]
    .sort((a, b) => evidencePriority(b) - evidencePriority(a))
    .slice(0, DEEP_SEARCH_MAX_EVIDENCE);

  return selected.map((row, index) => ({
    id: `S${String(index + 1).padStart(2, "0")}`,
    title: cleanText(row.title, 420),
    summary: cleanText(row.summary, 650),
    source: cleanText(row.source, 140),
    url: cleanText(row.url, 1200),
    published: row.published,
    language: row.language,
    source_count: row.sources?.length || 1,
    additional_sources: (row.sources || []).slice(1, 5).map(source => ({
      source: cleanText(source.source, 140),
      url: cleanText(source.url, 1200),
      language: source.language,
      published: source.published
    })),
    atlas_status: row.atlas_status,
    atlas_match_id: row.atlas_match_id,
    atlas_match_title: row.atlas_match_title,
    atlas_match_score: row.atlas_match_score
  }));
}

function citationMetrics(analysis, evidence) {
  const valid = new Set(evidence.map(item => item.id));
  const cited = new Set();
  for (const match of String(analysis || "").matchAll(/\[(S\d{2})\]/g)) {
    if (valid.has(match[1])) cited.add(match[1]);
  }

  const paragraphs = String(analysis || "")
    .split(/\n+/)
    .map(value => value.trim())
    .filter(value => value && !/^[A-Z][A-Z /&-]{4,}$/.test(value));
  const factual = paragraphs.filter(value => value.length >= 35);
  const grounded = factual.filter(value => /\[S\d{2}\]/.test(value));
  return {
    cited_source_ids: [...cited],
    citation_coverage_percent: factual.length ? Math.round(grounded.length / factual.length * 100) : 100,
    cited_sources: cited.size,
    factual_paragraphs: factual.length,
    cited_factual_paragraphs: grounded.length
  };
}

async function authenticateDeepSearch(request, body, env) {
  const username = normalizeUsername(body.user_id || body.username);
  const token = cleanText(request.headers.get("X-Session-Token"), 160);
  if (!username || !isAllowedUser(username)) {
    return { error: jsonResponse({ error: "Unknown or missing user." }, 400, env) };
  }
  if (!token) {
    return { error: jsonResponse({ error: "Authenticated session required. Please sign in again." }, 401, env) };
  }
  const sessionResponse = await gateCall(env, "/session-get", { session_token: token });
  const session = await sessionResponse.json().catch(() => ({}));
  if (!sessionResponse.ok || session?.username !== username) {
    return { error: jsonResponse({ error: "Unauthorized session." }, 401, env) };
  }
  return { username };
}

export async function handleDeepSearch(request, env, ctx) {
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid JSON request." }, 400, env);
  }

  const auth = await authenticateDeepSearch(request, body, env);
  if (auth.error) return auth.error;

  const question = cleanText(body.question, 1200);
  const periodDays = Number(body.period_days || 30);
  if (question.length < 8) {
    return jsonResponse({ error: "Enter a more specific Deep Search question." }, 400, env);
  }
  if (!DEEP_SEARCH_ALLOWED_PERIODS.has(periodDays)) {
    return jsonResponse({ error: "Unsupported Deep Search period." }, 400, env);
  }

  const username = auth.username;
  const cacheKey = await sha256(JSON.stringify({
    question: question.toLowerCase(),
    periodDays,
    version: "deep-search-v1"
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
      env,
      PLAN_INSTRUCTION,
      `Analyst question: ${question}\nTime window: last ${periodDays} days.`,
      PLAN_SCHEMA,
      3500
    );
    const plan = sanitizePlan(planRaw, question);
    if (!plan.queries.length) {
      return jsonResponse({ error: "Deep Search could not create a usable multilingual search plan." }, 422, env);
    }

    const retrieval = await retrieveNews(plan, periodDays);
    const unique = deduplicateRows(retrieval.rows);
    if (!unique.length) {
      return jsonResponse({
        error: "Deep Search found no usable open-source reporting for this question and period.",
        languages_searched: [...new Set(plan.queries.map(item => item.language))]
      }, 422, env);
    }

    let db = { events: [] };
    let databaseVersion = "unavailable";
    try {
      const dbResponse = await fetch(env.EVENTS_URL, { cf: { cacheTtl: 60, cacheEverything: true } });
      if (dbResponse.ok) {
        db = await dbResponse.json();
        databaseVersion = cleanText(db.updated_at || db.generated_at || db.last_updated || "unknown", 100);
      }
    } catch (_) {}

    const compared = compareWithAtlas(unique, candidateMapEvents(db, periodDays));
    const evidence = buildEvidence(compared);
    const dataset = {
      analyst_question: question,
      interpreted_request: plan.interpreted_request,
      period_days: periodDays,
      database_version: databaseVersion,
      evidence
    };

    const generated = await callGeminiJson(
      env,
      REPORT_INSTRUCTION,
      "Answer the analyst question using only this Deep Search evidence dataset:\n\n" + JSON.stringify(dataset),
      REPORT_SCHEMA,
      9000
    );

    const analysis = String(generated.analysis || "").trim();
    if (!analysis) throw new Error("Deep Search generated an empty analytical report.");

    const metrics = citationMetrics(analysis, evidence);
    const languages = [...new Set(plan.queries.map(item => item.language))];
    const gaps = evidence.filter(item => item.atlas_status === "potential_gap").length;
    const inAtlas = evidence.length - gaps;
    const successfulQueries = retrieval.waves.filter(item => item.ok).length;

    const report = {
      title: cleanText(generated.title || "CT Atlas Deep Search", 180),
      analysis,
      question,
      interpreted_request: plan.interpreted_request,
      period_days: periodDays,
      generated_at: new Date().toISOString(),
      database_version: databaseVersion,
      model: DEEP_SEARCH_MODEL,
      languages_searched: languages.map(code => ({ code, name: LANGUAGE_LOCALES[code]?.label || code })),
      search_queries: plan.queries,
      retrieval: {
        queries_planned: plan.queries.length,
        queries_successful: successfulQueries,
        articles_retrieved: retrieval.rows.length,
        unique_event_clusters: unique.length,
        evidence_events_used_for_analysis: evidence.length,
        matched_to_atlas: inAtlas,
        potential_atlas_gaps: gaps
      },
      grounding: {
        ...metrics,
        note: "Citation coverage measures visible source citation coverage; it is not a statistical probability of hallucination."
      },
      evidence
    };

    await gateCall(env, "/cache-put", {
      cacheKey: "deep:" + cacheKey,
      report,
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
