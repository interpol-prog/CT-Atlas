const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions";
const ALLOWED_PERIODS = new Set([7, 30, 90, 180]);
const MAX_EVENTS_CURRENT = 80;
const MAX_EVENTS_PREVIOUS = 60;
const CACHE_TTL_MS = 8 * 60 * 60 * 1000;
const REPORT_COOLDOWN_MS = 20 * 60 * 1000;
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
// Bump whenever the report SHAPE changes (new fields, schema, citation
// rules) so an existing cache entry from before the change is never served
// as-is -- folded into the cache key in index.js's /report handler.
const REPORT_GENERATOR_VERSION = "report-v2-sources-and-citations";

const USER_PASSWORD_HASHES = Object.freeze({
  "officer-1": "79897f92c7b84a5c0b058faf5f3602382c554a1735a37de00ffa3d498436dcb8",
  "officer-2": "7950649bc82fbbc915e453cb4d705d1f9f2a709f64a98d5f30d473de2e5e0e02",
  "officer-3": "00140e9495c1a1b23304f8fe802fe572f13c7965b2f9854ef403cf052725a5bd",
  "officer-4": "87e0ed35aa02667e7190ee9a39a35f2f2ea94ffe78459cd00f68dc3f4483dfbd",
  "officer-5": "05f5f227035a3dcf258511962e88cc09a0cb812f6cc09bcc9032a52a173f08ff",
  "officer-6": "b895f20fa5e24ee731b1caa56e85f6e52ef8f81ac18061263395c816aca68f6f",
  "officer-7": "e2743009701596d746582b21a0755a52ff905634c7e6ba1d1e9124e1f4c8f57d",
  "analyst-1": "e970d0863e28dfb5a895e5c98646dc230f10058c631bc65e361c792359920aae",
  "analyst-2": "f53a8aea70c7ca9776a7d9cb7a9897b59878e0f20488694b165d705b8247ce01",
  "analyst-3": "d0587044d19f89b9898b6df2ea0ad6e094173096a7ee8f59246e5823b65dad66",
  "analyst-4": "ea5d73b943c3a551882003913c63c6cd4f1024fbfcc0abd78aa7283734bb6213",
  "analyst-5": "37b38c51aa196afdd04fb0f144d0afbb45008ce7b3c951820851f3c94ecca8a8",
  "analyst-6": "eaa49279899a1e8d1b422dc5e1218c35b9c9928f5500d773a8b04bd2a0e410b3",
  "analyst-7": "581a4064b3f601d79d9ae9bbac31e4b2419c622bc7b275f053f1c82dd24bf30e",
  "analyst-8": "c0f087d586fa81991cc27ab3461f48805b1768bdd26f361ccdb2b139b294b859",
  "senior-1": "28472578e349d9e15d181ccf235640bca6f48a97826ef49c042e625fd7e8a79f",
  "senior-2": "a6794f640ff8ef70e3adf8eead194c9a799eb7870e507e62b3fe2888fe191697",
  "senior-3": "ca703462862c64efc3a40cf4487422066a9806c6294ff1d9da53fb05bea45817",
  "senior-4": "7084c90c9114c3627d3e1465334e3b9a19a3a607d62188daefa6a82d8520436b",
  "senior-5": "85bb9ca20baff78dda7e2b4ea39b0015685d5de67733d71e2c05b15eddc5bb40",
  "admin": "a7cdf5d0586b392473dd0cd08c9ba833240006a8a7310bf9bc8bf1aefdfaeadb"
});
const ALLOWED_USERS = new Set(Object.keys(USER_PASSWORD_HASHES));

const REPORT_SCHEMA = {
  type: "object",
  properties: {
    title: { type: "string" },
    analysis: { type: "string" }
  },
  required: ["title", "analysis"]
};

const SYSTEM_INSTRUCTION = `
You are producing an on-demand counter-terrorism criminal-analysis report
from a deduplicated OSINT event database.

Write approximately 650-900 words in professional analytical English.

Use these headings exactly:
EXECUTIVE ASSESSMENT
KEY DEVELOPMENTS
GEOGRAPHIC PATTERNS
TACTICS / MODUS OPERANDI
COUNTER-TERRORISM RESPONSE
SIGNIFICANT CHANGES
OUTLOOK / WATCHPOINTS
SOURCE / CONFIDENCE NOTES

When a comparison period is supplied, focus on WHAT CHANGED between the current
period and the immediately preceding equivalent period. Distinguish reporting
volume from evidence of an actual operational change whenever possible.

Prioritise concrete countries, regions, cities, attacks, arrests, clashes,
disrupted plots, weapons/explosives, terrorist financing, CBRN, cyber and
emerging-technology developments when materially relevant to the selected topic.

Do not invent facts, casualty figures, attribution, coordination, causes or
predictions. Preserve uncertainty. Use only the supplied records and statistics.
The outlook may identify watchpoints but must not make unsupported forecasts.

CITATION RULES (this is how the analyst checks the report against real
sources and catches hallucination -- follow exactly):
- Every priority_events record carries a source_id like "S01". Cite it
  in brackets immediately after the claim it supports, exactly like
  [S01] or [S01, S07]. Never invent a source_id that was not supplied.
- Every factual sentence or bullet in EXECUTIVE ASSESSMENT, KEY
  DEVELOPMENTS, GEOGRAPHIC PATTERNS, TACTICS / MODUS OPERANDI,
  COUNTER-TERRORISM RESPONSE and SIGNIFICANT CHANGES must carry at least
  one citation. A sentence with no citation is read as your own
  unsupported inference, not a database fact -- avoid that.
- In SOURCE / CONFIDENCE NOTES, briefly state the overall reliability of
  this report: how many independent records it draws on, whether key
  claims rest on a single source or are corroborated by several
  (each record's source_count says how many outlets reported it), and
  name any specific claim above that is weakly supported (single-source,
  low relevance score, or otherwise uncertain). If the underlying data is
  thin for the requested topic/period, say so plainly instead of padding
  the report with speculation.
`;

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS,GET",
    "Access-Control-Allow-Headers": "Content-Type,X-Session-Token",
    "Content-Type": "application/json; charset=utf-8"
  };
}

function jsonResponse(body, status, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: corsHeaders(env)
  });
}

function cleanText(value, max = 700) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, max);
}

function normalizeUsername(value) {
  return cleanText(value, 64).toLowerCase();
}

function isAllowedUser(username) {
  return ALLOWED_USERS.has(normalizeUsername(username));
}

function parisDayKey(timestamp = Date.now()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(new Date(timestamp));
  const get = type => parts.find(part => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function usageTemplate(username = "") {
  return {
    username,
    logins: 0,
    searches: 0,
    map_searches: 0,
    event_list_searches: 0,
    report_requests: 0,
    reports_generated: 0,
    cached_reports: 0,
    blocked_report_requests: 0,
    last_activity: ""
  };
}

function parseEventDate(event) {
  for (const key of [
    "event_date","occurrence_date","occurred_at","incident_date","attack_date",
    "published_at","publication_date","published","pub_date","date","updated_at"
  ]) {
    if (!event?.[key]) continue;
    const date = new Date(event[key]);
    if (!Number.isNaN(date.getTime())) return date;
  }
  return null;
}

function eventCategories(event) {
  const raw = event?.categories ?? (event?.category ? [event.category] : []);
  return Array.isArray(raw) ? raw.map(String) : [String(raw)];
}

function matchesTopic(event, topic) {
  if (!topic || topic === "ALL") return true;
  return eventCategories(event).includes(topic);
}

const REPORT_REGION_COUNTRY_CODES = Object.freeze({
  "REGION:AFRICA": new Set([
    "DZ","AO","BJ","BW","BF","BI","CV","CM","CF","TD","KM","CG","CD","CI","DJ","EG",
    "GQ","ER","SZ","ET","GA","GM","GH","GN","GW","KE","LS","LR","LY","MG","MW","ML",
    "MR","MU","MA","MZ","NA","NE","NG","RW","ST","SN","SC","SL","SO","ZA","SS","SD",
    "TZ","TG","TN","UG","EH","ZM","ZW"
  ]),
  "REGION:MENA": new Set([
    "DZ","BH","EG","IR","IQ","IL","JO","KW","LB","LY","MA","OM","PS","QA","SA","SY",
    "TN","TR","AE","YE"
  ]),
  "REGION:AMERICAS": new Set([
    "AI","AG","AR","AW","BS","BB","BZ","BM","BO","BQ","BR","CA","KY","CL","CO","CR",
    "CU","CW","DM","DO","EC","SV","FK","GF","GL","GD","GP","GT","GY","HT","HN","JM",
    "MQ","MX","MS","NI","PA","PY","PE","PR","BL","KN","LC","MF","PM","VC","SX","SR",
    "TT","TC","US","UY","VE","VG","VI"
  ]),
  "REGION:ASIA_SOUTH_PACIFIC": new Set([
    "AF","AU","BD","BT","BN","KH","CN","FJ","HK","IN","ID","JP","KI","KP","KR","KG",
    "LA","MO","MY","MV","MH","FM","MN","MM","NR","NP","NZ","PK","PW","PG","PH","SG",
    "SB","LK","TJ","TH","TL","TM","TV","TW","UZ","VU","VN","WS","TO"
  ]),
  "REGION:EUROPE": new Set([
    "AL","AD","AM","AT","AZ","BY","BE","BA","BG","HR","CY","CZ","DK","EE","FI","FR",
    "GE","DE","GR","HU","IS","IE","IT","XK","LV","LI","LT","LU","MT","MD","MC","ME",
    "NL","MK","NO","PL","PT","RO","RU","SM","RS","SK","SI","ES","SE","CH","TR","UA",
    "GB","VA"
  ])
});

function matchesRegion(event, region) {
  const selected = String(region || "").trim().toUpperCase();
  if (!selected || selected === "GLOBAL") return true;

  const broadRegion = REPORT_REGION_COUNTRY_CODES[selected];
  if (broadRegion) {
    const countryCode = String(event?.country_code || event?.country_iso2 || event?.countryCode || event?.iso2 || "")
      .trim()
      .toUpperCase();
    if (countryCode && broadRegion.has(countryCode)) return true;

    const storedRegion = String(event?.region || "").trim().toUpperCase();
    const labelAliases = {
      "REGION:AFRICA": ["AFRICA", "SUB-SAHARAN AFRICA", "NORTH AFRICA"],
      "REGION:MENA": ["MENA", "MIDDLE EAST", "NORTH AFRICA", "MIDDLE EAST & NORTH AFRICA"],
      "REGION:AMERICAS": ["AMERICAS", "NORTH AMERICA", "CENTRAL AMERICA", "SOUTH AMERICA", "CARIBBEAN"],
      "REGION:ASIA_SOUTH_PACIFIC": ["ASIA", "SOUTH ASIA", "SOUTHEAST ASIA", "EAST ASIA", "ASIA PACIFIC", "OCEANIA", "SOUTH PACIFIC"],
      "REGION:EUROPE": ["EUROPE", "EASTERN EUROPE", "WESTERN EUROPE", "NORTHERN EUROPE", "SOUTHERN EUROPE"]
    };
    return (labelAliases[selected] || []).some(alias => storedRegion.includes(alias));
  }

  const target = String(region || "").trim().toLowerCase();
  return [event?.country, event?.region, event?.city]
    .some(v => String(v || "").trim().toLowerCase() === target);
}

function compactEvent(event) {
  return {
    id: String(event.id || event._mapKey || ""),
    title: cleanText(event.title, 280),
    summary: cleanText(event.summary, 560),
    categories: eventCategories(event),
    country: cleanText(event.country, 80),
    region: cleanText(event.region, 100),
    city: cleanText(event.city, 100),
    date: parseEventDate(event)?.toISOString() || "",
    source: cleanText(event.source, 140),
    url: cleanText(event.url, 1200),
    source_count: Number(event.source_count || 1),
    relevance: Number(event.ai_relevance_score || 0)
  };
}

// Shared by both the Report Generator and Deep Search: counts how many
// factual paragraphs in the generated analysis actually carry a [Sxx] /
// [Sxx, Syy] citation pointing at a real supplied source id, versus how
// many read as a bare, uncited claim. This is the concrete anti-hallucination
// signal surfaced to the user -- a citation coverage below 100% means some
// factual statements in the report are not directly traceable to a source.
function citationMetrics(analysis, validIds) {
  const valid = new Set(validIds);
  const cited = new Set();
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

function stats(events) {
  const category = {};
  const country = {};
  for (const e of events) {
    for (const c of eventCategories(e)) category[c] = (category[c] || 0) + 1;
    const co = cleanText(e.country, 80);
    if (co) country[co] = (country[co] || 0) + 1;
  }
  const topCountries = Object.entries(country).sort((a,b)=>b[1]-a[1]).slice(0,10);
  return { event_count: events.length, categories: category, top_countries: topCountries };
}

function priority(event) {
  const cats = eventCategories(event);
  let score = Number(event.ai_relevance_score || 0);
  if (cats.includes("Attacks")) score += 40;
  if (cats.includes("Counter Terrorism Action")) score += 35;
  if (cats.includes("Arrests")) score += 25;
  score += Math.min(20, Number(event.source_count || 1) * 3);
  return score;
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("");
}

async function gateCall(env, path, payload) {
  const id = env.REPORT_GATE.idFromName("global");
  const stub = env.REPORT_GATE.get(id);
  return stub.fetch("https://gate.internal" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

async function extractGeminiText(payload) {
  if (typeof payload?.output_text === "string" && payload.output_text.trim()) {
    return payload.output_text;
  }

  if (Array.isArray(payload?.steps)) {
    const chunks = [];
    for (const step of payload.steps) {
      if (step?.type !== "model_output") continue;
      if (typeof step?.text === "string" && step.text.trim()) chunks.push(step.text);
      if (Array.isArray(step?.content)) {
        for (const part of step.content) {
          if (typeof part?.text === "string" && part.text.trim()) chunks.push(part.text);
        }
      }
    }
    if (chunks.length) return chunks.join("\n");
  }

  if (Array.isArray(payload?.outputs)) {
    const chunks = [];
    for (const item of payload.outputs) {
      if (typeof item?.text === "string" && item.text.trim()) chunks.push(item.text);
      if (Array.isArray(item?.content)) {
        for (const part of item.content) {
          if (typeof part?.text === "string" && part.text.trim()) chunks.push(part.text);
        }
      }
    }
    if (chunks.length) return chunks.join("\n");
  }

  if (Array.isArray(payload?.candidates)) {
    const parts = payload.candidates?.[0]?.content?.parts || [];
    const text = parts.map(part => part?.text || "").join("");
    if (text.trim()) return text;
  }

  const status = cleanText(payload?.status || "", 40);
  const detail = cleanText(
    payload?.error?.message ||
    payload?.failure_reason ||
    payload?.incomplete_details?.reason ||
    "",
    180
  );
  throw new Error(
    `Gemini returned no readable output${status ? ` (status: ${status})` : ""}${detail ? `: ${detail}` : "."}`
  );
}

async function callGemini(env, input) {
  const models = [];
  const primaryModel = env.GEMINI_MODEL || "gemini-3.5-flash-lite";
  const fallbackModel = env.GEMINI_FALLBACK_MODEL || "gemini-3.6-flash";
  for (const model of [primaryModel, fallbackModel]) {
    if (model && !models.includes(model)) models.push(model);
  }

  let lastError = null;

  for (let attempt = 0; attempt < Math.max(3, models.length); attempt++) {
    const model = models[Math.min(attempt, models.length - 1)];
    const body = {
      model,
      input: "Produce the requested analytical report using only this JSON dataset:\n\n" + JSON.stringify(input),
      system_instruction: SYSTEM_INSTRUCTION,
      store: false,
      response_format: {
        type: "text",
        mime_type: "application/json",
        schema: REPORT_SCHEMA
      },
      generation_config: {
        max_output_tokens: 9000,
        thinking_level: "minimal"
      }
    };

    try {
      const response = await fetch(GEMINI_URL, {
        method: "POST",
        headers: {
          "x-goog-api-key": env.GEMINI_API_KEY,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });

      if (response.status === 429 || response.status >= 500) {
        lastError = new Error(`Gemini temporary error ${response.status} on ${model}`);
        await new Promise(r => setTimeout(r, (attempt + 1) * 2200));
        continue;
      }

      if (!response.ok) {
        throw new Error(`Gemini error ${response.status}: ${await response.text()}`);
      }

      const payload = await response.json();
      const status = String(payload?.status || "").toLowerCase();

      if (["failed", "cancelled"].includes(status)) {
        throw new Error(
          cleanText(payload?.error?.message || `Gemini interaction ${status}.`, 300)
        );
      }

      let raw;
      try {
        raw = await extractGeminiText(payload);
      } catch (error) {
        lastError = error;
        if (status === "incomplete" || attempt < 2) {
          await new Promise(r => setTimeout(r, (attempt + 1) * 1200));
          continue;
        }
        throw error;
      }

      const normalizedRaw = raw
        .trim()
        .replace(/^```(?:json)?\s*/i, "")
        .replace(/\s*```$/i, "");

      let parsed;
      try {
        parsed = JSON.parse(normalizedRaw);
      } catch (error) {
        lastError = new Error("Gemini returned text, but the report JSON could not be parsed.");
        console.error("Gemini JSON parse failure", {
          model,
          status: payload?.status,
          preview: normalizedRaw.slice(0, 500)
        });
        if (attempt < 2) {
          await new Promise(r => setTimeout(r, (attempt + 1) * 1200));
          continue;
        }
        throw lastError;
      }

      if (!parsed?.analysis) {
        lastError = new Error("Gemini returned an empty report.");
        if (attempt < 2) continue;
        throw lastError;
      }

      return parsed;
    } catch (error) {
      lastError = error;
      if (attempt < 2 && /temporary|incomplete|no readable output|could not be parsed|empty report/i.test(String(error?.message || ""))) {
        await new Promise(r => setTimeout(r, (attempt + 1) * 1200));
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("Gemini request failed.");
}

export {
  GEMINI_URL,
  ALLOWED_PERIODS,
  REPORT_GENERATOR_VERSION,
  MAX_EVENTS_CURRENT,
  MAX_EVENTS_PREVIOUS,
  CACHE_TTL_MS,
  REPORT_COOLDOWN_MS,
  SESSION_TTL_MS,
  USER_PASSWORD_HASHES,
  ALLOWED_USERS,
  REPORT_SCHEMA,
  SYSTEM_INSTRUCTION,
  corsHeaders,
  jsonResponse,
  cleanText,
  normalizeUsername,
  isAllowedUser,
  parisDayKey,
  usageTemplate,
  parseEventDate,
  eventCategories,
  matchesTopic,
  matchesRegion,
  compactEvent,
  citationMetrics,
  stats,
  priority,
  sha256,
  gateCall,
  extractGeminiText,
  callGemini
};
