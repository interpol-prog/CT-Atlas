const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions";
const ALLOWED_PERIODS = new Set([7, 30, 90, 180]);
const MAX_EVENTS_CURRENT = 80;
const MAX_EVENTS_PREVIOUS = 60;
const CACHE_TTL_MS = 8 * 60 * 60 * 1000;
const REPORT_COOLDOWN_MS = 20 * 60 * 1000;
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

const USER_PASSWORD_HASHES = Object.freeze({
  "intel-analyst": "d4cc63dfe1815a0b323c3d8471eae21ebf00499e8f6b7a8cc26e7bd4fde7646c",
  "police-officer": "d1e48410ae1823482d68cd4de5efc759dabd3c515eb14c06fcf8bb0588268593",
  "policy-analyst": "19c030b579851bf0ac2704dba514f2a35c412a92db431bda9379055b20d5e5bc",
  "senior-coordinator": "f2df56e5da8c9a04074faf5b8c171b89c1383de1e6bd992f0b91b8029bd34b9c",
  "assistant-director": "dc1cedf11a92a1fed5956cda3aaedad5ee1103989df2bff42cce5e764d526085",
  "director": "034ddc176af334156fcdbd0b693cfc83a50d2c76821d3a9f68adea0587ffb311",
  "stephen": "500751a25650c0eea7e0745fdfd936632cbda412fb8569515923742ec89f0bbf",
  "marius": "8e29ba49c55fb07b7acaa406f6d81fec1e779d260b0c506ae2b49c9014db4726",
  "edward": "23734a74e5ef6010f0c63c69674a9b22225ad4e2c456ec7a4ebd1b9139fb2c3e",
  "bridget": "4ac628e4079320de4c74cee9422aa04f79cd8e570f970415efb5dc2ae39cf365",
  "oskar": "68a1e856c146c106d49a3ac820ad9b533944888f06ed3694a7a4ca5085f1aa4d",
  "elodie": "26a6ab8e51c5633b74703a9458aa7aabd512fbcc4ad7b68bc1d263b582d5645f",
  "abdulla": "f3641445e1bd86a7fb2a2118bf3dc6340c10c3a42a62b787ab9c8293f7354a67",
  "kayla": "376c4a8db9fb07e293dc2086ec926af8425b6aec974527b4904ac8fda80ec31d",
  "anastasia": "b3ef423a6b0bd6b523d292b2c7cb081a6e04c4dc5d34805938d3dccde0d70052",
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

When a comparison period is supplied, focus on WHAT CHANGED between the current
period and the immediately preceding equivalent period. Distinguish reporting
volume from evidence of an actual operational change whenever possible.

Prioritise concrete countries, regions, cities, attacks, arrests, clashes,
disrupted plots, weapons/explosives, terrorist financing, CBRN, cyber and
emerging-technology developments when materially relevant to the selected topic.

Do not invent facts, casualty figures, attribution, coordination, causes or
predictions. Preserve uncertainty. Use only the supplied records and statistics.
The outlook may identify watchpoints but must not make unsupported forecasts.
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
    source_count: Number(event.source_count || 1),
    relevance: Number(event.ai_relevance_score || 0)
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
  stats,
  priority,
  sha256,
  gateCall,
  extractGeminiText,
  callGemini
};
