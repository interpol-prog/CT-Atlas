from pathlib import Path

# --- Backend ---
p = Path('cloudflare-worker/deep-search.js')
s = p.read_text(encoding='utf-8')
if 'deep-search-v5.7-subrequest-safe' not in s:
    raise SystemExit('Expected v5.7 backend not found')
s = s.replace('deep-search-v5.7-subrequest-safe', 'deep-search-v5.8-priority-language', 1)

anchor = 'const DEEP_SEARCH_LANGUAGE_CODES = Object.freeze(Object.keys(LANGUAGE_LOCALES));\n'
if anchor not in s:
    raise SystemExit('Language anchor missing')
insert = r'''

const COUNTRY_LANGUAGE_PRIORITY = Object.freeze([
  { pattern: /\b(?:afghanistan|afghan)\b/i, languages: ["fa", "ps"] },
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

function detectPriorityLanguages(question) {
  const text = String(question || "");
  const out = [];
  const add = code => {
    if (DEEP_SEARCH_LANGUAGE_CODES.includes(code) && !out.includes(code)) out.push(code);
  };
  for (const rule of COUNTRY_LANGUAGE_PRIORITY) {
    if (rule.pattern.test(text)) rule.languages.forEach(add);
  }
  // Urdu is not an official Afghan language, but it is highly relevant to
  // Afghanistan-Pakistan narcotics routes and cross-border enforcement reporting.
  if (/\b(?:afghanistan|afghan)\b/i.test(text) && /\b(?:drug|narcotic|opium|heroin|meth|methamphetamine|traffick|smuggl|seizure|laborator)\w*\b/i.test(text)) add("ur");
  return out.slice(0, 3);
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
'''
s = s.replace(anchor, anchor + insert, 1)

start = s.index('async function retrieveNews(plan, periodDays) {')
end = s.index('\nfunction candidateMapEvents', start)
new_retrieve = r'''async function retrieveNews(plan, periodDays, priorityLanguages = []) {
  // Bound search below Cloudflare Free's 50-subrequest ceiling:
  // 24 Google News + max 3 priority Google rescues + max 9 GDELT = max 36.
  const googleWaves = await Promise.all(
    plan.queries.map((item, index) =>
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
  for (const language of priorityLanguages.slice(0, 3)) {
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
'''
s = s[:start] + new_retrieve + s[end:]

if 'function buildEvidence(rows) {' not in s:
    raise SystemExit('buildEvidence signature missing')
s = s.replace('function buildEvidence(rows) {', 'function buildEvidence(rows, priorityLanguages = []) {', 1)
old_loop = '''  // Preserve multilingual evidence when it exists: take the best hit from each
  // searched language first, then fill the remaining slots by overall relevance.
  for (const language of DEEP_SEARCH_LANGUAGE_CODES) {
    const index = ranked.findIndex((row, i) => !used.has(i) && row.language === language);
    if (index >= 0 && selected.length < DEEP_SEARCH_MAX_EVIDENCE) {
      selected.push(ranked[index]);
      used.add(index);
    }
  }
'''
new_loop = '''  // Protect two evidence slots per country-priority language when available.
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
'''
if old_loop not in s:
    raise SystemExit('Multilingual evidence loop missing')
s = s.replace(old_loop, new_loop, 1)

if 'function languageDiagnostics(plan, retrieval) {' not in s:
    raise SystemExit('Diagnostics signature missing')
s = s.replace('function languageDiagnostics(plan, retrieval) {', 'function languageDiagnostics(plan, retrieval, priorityLanguages = []) {', 1)
s = s.replace('      gdelt_articles: 0\n    };', '      gdelt_articles: 0,\n      priority: priorityLanguages.includes(code)\n    };', 1)

old_handle = '''    const retrieval = await retrieveNews(plan, periodDays);
    const unique = deduplicateRows(retrieval.rows);
    const languagesSearched = languageDiagnostics(plan, retrieval);
'''
new_handle = '''    const priorityLanguages = detectPriorityLanguages(question);
    const retrieval = await retrieveNews(plan, periodDays, priorityLanguages);
    const unique = deduplicateRows(retrieval.rows);
    const languagesSearched = languageDiagnostics(plan, retrieval, priorityLanguages);
'''
if old_handle not in s:
    raise SystemExit('Retrieval call anchor missing')
s = s.replace(old_handle, new_handle, 1)
s = s.replace('    const evidence = buildEvidence(compared);', '    const evidence = buildEvidence(compared, priorityLanguages);', 1)
s = s.replace('      language_search_coverage: languagesSearched,\n      evidence', '      language_search_coverage: languagesSearched,\n      priority_languages: priorityLanguages,\n      evidence', 1)
s = s.replace('      languages_searched: languagesSearched,\n      search_queries:', '      languages_searched: languagesSearched,\n      priority_languages: priorityLanguages,\n      search_queries:', 1)
s = s.replace('        gdelt_articles: retrieval.rows.filter(row => row.search_engine === "gdelt").length\n', '        gdelt_articles: retrieval.rows.filter(row => row.search_engine === "gdelt").length,\n        search_subrequests: retrieval.subrequest_budget?.search_requests || retrieval.waves.length\n', 1)
p.write_text(s, encoding='utf-8')

idx = Path('cloudflare-worker/index.js')
t = idx.read_text(encoding='utf-8')
if 'version: "5.7"' not in t:
    raise SystemExit('Expected Worker health v5.7 not found')
idx.write_text(t.replace('version: "5.7"', 'version: "5.8"', 1), encoding='utf-8')

# --- Frontend PDF + diagnostics ---
f = Path('deep-search.js')
js = f.read_text(encoding='utf-8')
old_method = 'Deep Search runs two native-language Google News searches in each of the 12 supported languages. Languages with sparse results are automatically supplemented through GDELT; all reporting is then merged, deduplicated, compared with CT Atlas and analysed with source citations.'
new_method = 'Deep Search runs two native-language Google News searches in each of the 12 supported languages. Languages relevant to the country in the analyst question receive priority rescue searches; sparse coverage is then supplemented through GDELT before deduplication, CT Atlas comparison and source-cited analysis.'
if old_method in js:
    js = js.replace(old_method, new_method, 1)

old_diag = '    const gdeltCount=Number(item.gdelt_articles||0);\n    const cls=count>0?" has-results":" no-results";'
new_diag = '    const gdeltCount=Number(item.gdelt_articles||0);\n    const priority=Boolean(item.priority);\n    const cls=count>0?" has-results":" no-results";'
if old_diag not in js:
    raise SystemExit('Frontend diagnostics anchor missing')
js = js.replace(old_diag, new_diag, 1)
old_small = '${count===1?"article":"articles"} · Google ${googleCount} · GDELT ${gdeltCount} · ${queryCount||1}'
new_small = '${count===1?"article":"articles"}${priority?" · PRIORITY":""} · Google ${googleCount} · GDELT ${gdeltCount} · ${queryCount||1}'
if old_small not in js:
    raise SystemExit('Frontend coverage label anchor missing')
js = js.replace(old_small, new_small, 1)

old_style = 'shell.style.cssText="position:fixed;left:0;top:0;z-index:-9999;width:780px;background:#fff;color:#111;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;padding:30px;box-sizing:border-box";'
new_style = 'shell.style.cssText="position:absolute;left:0;top:0;z-index:2147483000;width:780px;height:auto;overflow:visible;background:#fff;color:#111;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;padding:30px;box-sizing:border-box;pointer-events:none";'
if old_style not in js:
    raise SystemExit('PDF shell style anchor missing')
js = js.replace(old_style, new_style, 1)
old_append = '''    document.body.appendChild(shell);

    await html2pdf().set({'''
new_append = '''    shell.id="ctAtlasDeepPdfSource";
    document.body.appendChild(shell);
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    if(document.fonts?.ready){try{await document.fonts.ready;}catch(_){}}
    const rect=shell.getBoundingClientRect();
    if(shell.scrollHeight<100||rect.width<100)throw new Error("PDF source did not render correctly.");

    await html2pdf().set({'''
if old_append not in js:
    raise SystemExit('PDF append anchor missing')
js = js.replace(old_append, new_append, 1)
old_canvas = 'html2canvas:{scale:2,useCORS:true,logging:false,backgroundColor:"#ffffff"}'
new_canvas = 'html2canvas:{scale:2,useCORS:true,logging:false,backgroundColor:"#ffffff",scrollX:0,scrollY:0,windowWidth:780,windowHeight:Math.max(shell.scrollHeight,1120)}'
if old_canvas not in js:
    raise SystemExit('html2canvas options anchor missing')
js = js.replace(old_canvas, new_canvas, 1)
f.write_text(js, encoding='utf-8')
