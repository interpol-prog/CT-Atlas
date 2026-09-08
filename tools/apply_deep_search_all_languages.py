from pathlib import Path

PATH = Path("cloudflare-worker/deep-search.js")
text = PATH.read_text(encoding="utf-8")

if 'deep-search-v3-all-12-languages' in text:
    print("Deep Search 12-language mode already applied.")
    raise SystemExit(0)

text = text.replace(
    'const DEEP_SEARCH_MAX_QUERIES = 8;',
    'const DEEP_SEARCH_MAX_QUERIES = 12;'
)
text = text.replace(
    'const DEEP_SEARCH_VERSION = "deep-search-v2-grounded-local-language";',
    'const DEEP_SEARCH_VERSION = "deep-search-v3-all-12-languages";'
)

plan_start = text.index('const PLAN_SCHEMA = {')
report_marker = '\n\nconst REPORT_SCHEMA'
report_pos = text.find(report_marker, plan_start)
if report_pos < 0:
    report_marker = '\n\nconst DEEP_SEARCH_REPORT_SCHEMA'
    report_pos = text.index(report_marker, plan_start)

new_schema = '''const DEEP_SEARCH_LANGUAGE_CODES = Object.freeze(Object.keys(LANGUAGE_LOCALES));

const PLAN_SCHEMA = {
  type: "object",
  properties: {
    interpreted_request: { type: "string" },
    queries: {
      type: "object",
      properties: Object.fromEntries(
        DEEP_SEARCH_LANGUAGE_CODES.map(code => [code, { type: "string" }])
      ),
      required: [...DEEP_SEARCH_LANGUAGE_CODES]
    }
  },
  required: ["interpreted_request", "queries"]
};'''
text = text[:plan_start] + new_schema + text[report_pos:]

instruction_start = text.index('const PLAN_INSTRUCTION = `')
instruction_end = text.index('`;\n\nconst REPORT_INSTRUCTION', instruction_start) + 2
new_instruction = '''const PLAN_INSTRUCTION = `
You are the query-planning component of CT Atlas Deep Search, an authorised
multilingual OSINT research tool.

Interpret the analyst's exact free-text request and create EXACTLY TWELVE Google
News queries: one in each CT Atlas search language. Every Deep Search must search
ALL 12 languages, regardless of the geography or topic. Do not choose or omit
languages based on relevance.

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

For every language, translate/adapt the analyst's SAME core information need into
natural search language. Preserve named actors, organisations, places, commodities,
weapons, routes, dates and other constraints. Do not broaden a precise geography,
actor, commodity or question into generic regional news. Adjacent countries may
appear only when directly relevant to a route, network, cross-border operation or
comparison requested by the analyst.

If the analyst explicitly asks about narcotics, organised crime, smuggling,
weapons, cybercrime or another adjacent security topic, search that topic directly
even when no terrorism nexus is stated. Do not silently force a CT nexus that the
analyst did not request.

For narcotics queries distinguish, when relevant: cultivation, production,
laboratories, precursor chemicals, methamphetamine/synthetic drugs, heroin,
trafficking networks/routes, seizures, decrees/bans, enforcement and laboratory
destruction.

Return only the structured search plan. The queries object MUST contain all 12
language keys and no language may be omitted. Do not answer the analyst's question
yet.
`;'''
text = text[:instruction_start] + new_instruction + text[instruction_end:]

fallback_start = text.index('function requiredLanguages(question) {')
fallback_end = text.index('\n\nasync function retrieveNews', fallback_start)
new_sanitize = '''function sanitizePlan(plan, fallbackQuestion) {
  const queries = [];
  const raw = plan?.queries && typeof plan.queries === "object" && !Array.isArray(plan.queries)
    ? plan.queries
    : {};

  const missing = [];
  for (const language of DEEP_SEARCH_LANGUAGE_CODES) {
    const query = cleanText(raw[language], 420);
    if (!query) {
      missing.push(language);
      continue;
    }
    queries.push({ language, query });
  }

  if (missing.length) {
    throw new Error(
      "Deep Search planner did not return all 12 required language queries: " +
      missing.join(", ")
    );
  }

  return {
    interpreted_request: cleanText(plan?.interpreted_request || fallbackQuestion, 700),
    queries
  };
}'''
text = text[:fallback_start] + new_sanitize + text[fallback_end:]

text = text.replace(
    'User-Agent": "Mozilla/5.0 CT-Atlas-Deep-Search/2.0"',
    'User-Agent": "Mozilla/5.0 CT-Atlas-Deep-Search/3.0"'
)
text = text.replace('PLAN_SCHEMA, 4000', 'PLAN_SCHEMA, 6000')

required = [
    'DEEP_SEARCH_MAX_QUERIES = 12',
    'deep-search-v3-all-12-languages',
    'DEEP_SEARCH_LANGUAGE_CODES',
    'EXACTLY TWELVE',
    'Dari / Persian',
    'Urdu',
    'Pashto',
]
for marker in required:
    if marker not in text:
        raise RuntimeError(f"Missing expected marker after patch: {marker}")

PATH.write_text(text, encoding="utf-8")
print("Applied mandatory 12-language Deep Search mode.")
