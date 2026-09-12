const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('cloudflare-worker/deep-search.js','utf8').replace(/^import[\s\S]*?from "\.\/shared.js";\s*/,'').replace(/export /g,'');
function harness(fetch){
 const c=vm.createContext({fetch,URLSearchParams,AbortSignal,setTimeout:fn=>fn(),cleanText:(v,n)=>String(v||'').trim().slice(0,n)});
 vm.runInContext(source,c);
 return vm.runInContext('({sanitizePlan,retrieveNews,resolvePriorityLanguages,buildEvidence,fetchNewsWave,fetchGdeltGlobalWave,splitGdeltRowsByLanguage,broadGdeltQuery,computeLanguageAnchors,filterByAnchor,DEEP_SEARCH_LANGUAGE_CODES,extractExplicitQuestionDate,resolveEffectivePeriodDays,fetchAcledWave,isLikelyTransientFetchIssue})',c);
}
function plan(h){return h.sanitizePlan({priority_languages:['fa','ps','ur','invalid'],queries:Object.fromEntries(h.DEEP_SEARCH_LANGUAGE_CODES.map(l=>[l,{primary:`${l} Afghanistan opium`,secondary:`${l} Afghanistan heroin`}]))},'Afghanistan drugs');}
test('Afghanistan narcotics prioritises English, French, Dari, Pashto and Urdu',()=>{
 const h=harness();assert.deepEqual(Array.from(h.resolvePriorityLanguages('Afghanistan drug trafficking',[])),['en','fr','fa','ps','ur']);
 assert.deepEqual(Array.from(plan(h).priority_languages),['fa','ps','ur']);
});
test('English and French are always prioritised even without a detected country',()=>{
 const h=harness();assert.deepEqual(Array.from(h.resolvePriorityLanguages('What is the current threat level?',[])),['en','fr']);
});
test('Egypt questions prioritise Arabic alongside English and French',()=>{
 const h=harness();assert.deepEqual(Array.from(h.resolvePriorityLanguages('Recent extremist activity in Egypt',[])),['en','fr','ar']);
});
test('sparse local feeds get native queries through fallback edition within 29 search calls (24 google + 3 rescue + 1 single global GDELT call + 1 single ACLED call)',async()=>{
 const calls=[];const h=harness(async url=>{calls.push(new URL(url));return new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>');});
 const result=await h.retrieveNews(plan(h),180,['fa','ps','ur']);
 assert.equal(calls.length,29);assert.equal(result.subrequest_budget.search_requests,29);
 assert.equal(calls.filter(u=>u.href.includes('gdelt')).length,1,'GDELT must be queried exactly once, never per-language');
 assert.equal(calls.filter(u=>(u.searchParams.get('q')||'').includes('site:acleddata.com')).length,1,'ACLED must be queried exactly once');
 const rescue=result.waves.filter(w=>w.query.variant==='priority-locale-rescue');
 assert.deepEqual(Array.from(rescue,w=>w.query.language),['fa','ps','ur']);
 assert.ok(rescue.every(w=>w.query.fallback_locale));
 assert.ok(calls[0].searchParams.get('q').startsWith('fa '));
});
test('ACLED is queried once via a Google News query scoped to site:acleddata.com, tagged with search_engine "acled"',async()=>{
 const h=harness(async()=>new Response('<rss><channel><item><title>ACLED raid report</title><link>https://acleddata.com/x</link></item></channel></rss>'));
 const wave=await h.fetchAcledWave('Afghanistan opium cultivation',30);
 assert.ok(wave.ok);
 assert.equal(wave.query.engine,'acled');
 assert.equal(wave.rows.length,1);
 assert.equal(wave.rows[0].search_engine,'acled');
 assert.equal(wave.rows[0].language,'en');
});
test('retrieveNews includes exactly one ACLED wave alongside the Google News and GDELT waves',async()=>{
 const h=harness(async url=>new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>'));
 const result=await h.retrieveNews(plan(h),30,[]);
 const acledWaves=result.waves.filter(w=>w.query.engine==='acled');
 assert.equal(acledWaves.length,1);
 assert.equal(result.subrequest_budget.acled_requests,1);
});
test('English priority rescue uses a genuinely different locale than its own primary/secondary queries, not a no-op duplicate',async()=>{
 // Regression test for v5.18: SEARCH_FALLBACK_LOCALE (en-US/US/US:en) used
 // to be reused for English's own rescue, but LANGUAGE_LOCALES.en is
 // *already* en-US/US/US:en -- so the "rescue" resent the exact same
 // request and could never surface anything new. English must get a
 // distinct fallback (the UK edition) instead.
 const calls=[];const h=harness(async url=>{calls.push(new URL(url));return new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>');});
 await h.retrieveNews(plan(h),30,['en','fr','fa','ps','ur']);
 const englishCalls=calls.filter(u=>(u.searchParams.get('q')||'').toLowerCase().startsWith('en '));
 assert.ok(englishCalls.length>=3,'expected English primary, secondary, and a rescue call');
 const locales=new Set(englishCalls.map(u=>u.searchParams.get('hl')));
 assert.ok(locales.size>1,'English rescue must use a different hl than en-US, otherwise it just resends the identical request: '+[...locales]);
 assert.ok(englishCalls.some(u=>u.searchParams.get('hl')==='en-GB'&&u.searchParams.get('gl')==='GB'));
});
test('five priority languages still stay within the 31-call search budget, well under the 50 subrequest ceiling once the ~9 non-search calls are counted',async()=>{
 const calls=[];const h=harness(async url=>{calls.push(new URL(url));return new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>');});
 const result=await h.retrieveNews(plan(h),30,h.resolvePriorityLanguages('Afghanistan drug trafficking',[]));
 assert.equal(calls.length,31);assert.equal(result.subrequest_budget.search_requests,31);
 assert.ok(result.subrequest_budget.search_requests+9<50);
 const rescue=result.waves.filter(w=>w.query.variant==='priority-locale-rescue');
 assert.equal(rescue.length,5);
 assert.equal(calls.filter(u=>u.href.includes('gdelt')).length,1,'GDELT must be queried exactly once even with 5 priority languages');
 assert.equal(calls.filter(u=>(u.searchParams.get('q')||'').includes('site:acleddata.com')).length,1,'ACLED must be queried exactly once even with 5 priority languages');
});
test('a failing wave is never retried — retries risk blowing the subrequest ceiling on exactly the runs where most waves are failing',async()=>{
 let calls=0;const h=harness(async()=>{calls++;return new Response('rate limited',{status:429});});
 await h.fetchNewsWave({language:'en',query:'q',variant:'primary'},0,30,{hl:'en-US',gl:'US',ceid:'US:en'});
 assert.equal(calls,1);
 calls=0;await h.fetchGdeltGlobalWave('q',30);
 assert.equal(calls,1);
});
test('GDELT is queried once globally and its mixed-language response is split back into one wave per language',async()=>{
 // Regression test for v5.19: GDELT allows ~1 request per 5 seconds (its own
 // 429 response says so), so it must never be queried more than once per
 // Deep Search. A single global query (no sourcelang filter) is split back
 // into per-language rows using each article's own reported language.
 const h=harness();
 const globalWave={ok:true,status:200,rows:[
   {title:'Afghanistan opium seizure reported',summary:'',source:'x',url:'https://x/1',published:'',language:'en',query_index:-1,query_variant:'gdelt-rescue',search_query:'q',search_engine:'gdelt',fallback_locale:false},
   {title:'Article en arabe',summary:'',source:'x',url:'https://x/2',published:'',language:'ar',query_index:-1,query_variant:'gdelt-rescue',search_query:'q',search_engine:'gdelt',fallback_locale:false},
 ]};
 const waves=h.splitGdeltRowsByLanguage(globalWave,'q',['en','ar','fr']);
 assert.deepEqual(Array.from(waves,w=>w.query.language).sort(),['ar','en','fr']);
 assert.equal(waves.find(w=>w.query.language==='en').rows.length,1);
 assert.equal(waves.find(w=>w.query.language==='ar').rows.length,1);
 assert.equal(waves.find(w=>w.query.language==='fr').rows.length,0);
 assert.ok(waves.every(w=>w.ok===true&&w.status===200),'the shared fetch outcome must be visible on every derived per-language wave');
});
test('GDELT articles in an unrecognized language are dropped, not miscounted',async()=>{
 const json=JSON.stringify({articles:[
   {title:'English piece',url:'https://x/1',language:'English',domain:'x.com',seendate:'20260101120000Z'},
   {title:'Unknown script piece',url:'https://x/2',language:'Klingon',domain:'x.com',seendate:'20260101120000Z'},
 ]});
 const h=harness(async()=>new Response(json));
 const wave=await h.fetchGdeltGlobalWave('q',30);
 assert.equal(wave.rows.length,1);
 assert.equal(wave.rows[0].language,'en');
});
test('HTML 200 provider failures remain distinct from empty RSS',async()=>{
 const h=harness(async url=>new Response(url.includes('gdelt')?'{}':'<html>Unavailable</html>'));
 const r=await h.retrieveNews(plan(h),7,[]);
 assert.ok(r.waves.filter(w=>!w.query.engine).every(w=>!w.ok&&w.error.includes('non-RSS')));
});
test('missing language plans fail explicitly',()=>{assert.throws(()=>harness().sanitizePlan({queries:{}},''),/every required language/);});
test('GDELT broad query appends planner-supplied exclude terms as -term',()=>{
 const h=harness();
 const gdeltPlan={
   gdelt_broad_terms:['methamphetamine','fentanyl','cartel'],
   gdelt_exclude_terms:['spain','madrid'],
   queries:[
     {language:'en',variant:'primary',query:'Afghanistan opium cultivation ban enforcement decree'},
     {language:'en',variant:'secondary',query:'Afghanistan methamphetamine heroin laboratory seizure trafficking'},
   ]};
 assert.equal(h.broadGdeltQuery(gdeltPlan),'afghanistan (methamphetamine OR fentanyl OR cartel) -spain -madrid');
});
test('computeLanguageAnchors finds the shared geography token per language, in any script',()=>{
 const h=harness();
 const p={queries:[
   {language:'en',variant:'primary',query:'Afghanistan opium cultivation'},
   {language:'en',variant:'secondary',query:'Afghanistan heroin trafficking'},
   {language:'es',variant:'primary',query:'Afganistán cultivo de opio'},
   {language:'es',variant:'secondary',query:'Afganistán tráfico de heroína'},
   {language:'ar',variant:'primary',query:'أفغانستان زراعة الأفيون'},
   {language:'ar',variant:'secondary',query:'أفغانستان تهريب الهيروين'},
   {language:'de',variant:'primary',query:'Drogen Opium Anbau'},
   {language:'de',variant:'secondary',query:'Heroin Schmuggel Labor'},
 ]};
 const anchors=h.computeLanguageAnchors(p);
 assert.equal(anchors.en,'afghanistan');
 assert.equal(anchors.es,'afganistán');
 assert.equal(anchors.ar,'أفغانستان');
 assert.equal(anchors.de,undefined,'no shared token in German queries above: should not guess an anchor');
});
test('computeLanguageAnchors prefers the planner-supplied explicit anchor, fixing the real case where secondary never repeats the geography',()=>{
 const h=harness();
 // This is the exact failure mode found in production: the secondary query
 // is a global/comparative facet that never repeats "Afghanistan", so the
 // old shared-token heuristic found no anchor at all and left English rows
 // completely unfiltered — letting unrelated Nigeria/Mexico/Colombia drug
 // stories into the evidence pack.
 const p={
   anchors:{en:'afghanistan'},
   queries:[
     {language:'en',variant:'primary',query:'Afghanistan opium cultivation ban'},
     {language:'en',variant:'secondary',query:'global methamphetamine production trends emerging hubs'},
   ]};
 const anchors=h.computeLanguageAnchors(p);
 assert.equal(anchors.en,'afghanistan');
 const rows=[
   {language:'en',title:'NDLEA Uncovers Mexican Cartel Links to Ogun, Oyo Meth Labs',summary:''},
   {language:'en',title:'Afghanistan opium ban devastates farmers, UN says',summary:''},
 ];
 assert.deepEqual(h.filterByAnchor(rows,anchors).map(r=>r.title),['Afghanistan opium ban devastates farmers, UN says']);
});
test('sanitizePlan extracts the explicit anchor per language but does not require it',()=>{
 const h=harness();
 const raw={queries:Object.fromEntries(h.DEEP_SEARCH_LANGUAGE_CODES.map(l=>[l,{primary:`${l} p`,secondary:`${l} s`,anchor:l==='en'?'Afghanistan':''}]))};
 const sanitized=h.sanitizePlan(raw,'q');
 assert.equal(sanitized.anchors.en,'afghanistan');
 assert.equal(sanitized.anchors.fr,undefined);
});
test('filterByAnchor drops off-topic articles but is lenient when a language has no anchor',()=>{
 const h=harness();
 const anchors={es:'afganistán'};
 const rows=[
   {language:'es',title:'Detenido con heroína en Huelva',summary:'sin relación con el país solicitado'},
   {language:'es',title:'Afganistán: incautan heroína en ruta hacia Europa',summary:''},
   {language:'de',title:'Beliebiger Artikel ohne Anker',summary:''},
 ];
 const kept=h.filterByAnchor(rows,anchors);
 assert.deepEqual(kept.map(r=>r.title),['Afganistán: incautan heroína en ruta hacia Europa','Beliebiger Artikel ohne Anker']);
});
test('retrieveNews filters out an off-topic article for a language with a confident anchor',async()=>{
 const onTopicRss='<rss><channel><item><title>Afghanistan opium seizure reported</title><link>https://x/1</link></item></channel></rss>';
 const offTopicRss='<rss><channel><item><title>Domestic heroin bust unrelated to the requested country</title><link>https://x/2</link></item><item><title>Afganistán: incautan opio en la frontera</title><link>https://x/3</link></item></channel></rss>';
 const h=harness(async url=>new Response(url.includes('gdelt')?'{}':(url.includes('hl=es')?offTopicRss:onTopicRss)));
 const p=h.sanitizePlan({queries:Object.fromEntries(h.DEEP_SEARCH_LANGUAGE_CODES.map(l=>[l,{primary:`${l==='es'?'Afganistán':'Afghanistan'} opium cultivation`,secondary:`${l==='es'?'Afganistán':'Afghanistan'} heroin trafficking`}]))},'Afghanistan drugs');
 const result=await h.retrieveNews(p,30,[]);
 // Both the primary and secondary "es" queries hit the same mocked feed, so
 // the off-topic item must be dropped from each of those two waves.
 const esRows=result.waves.filter(w=>w.query.language==='es').flatMap(w=>w.rows);
 assert.equal(esRows.length,2);
 assert.ok(esRows.every(r=>r.title==='Afganistán: incautan opio en la frontera'));
});
test('GDELT broad query uses the planner-supplied gdelt_broad_terms when available, ignoring the static heuristic',()=>{
 const h=harness();
 const gdeltPlan={
   gdelt_broad_terms:['methamphetamine','fentanyl','cartel'],
   queries:[
     {language:'en',variant:'primary',query:'Afghanistan opium cultivation ban enforcement decree'},
     {language:'en',variant:'secondary',query:'Afghanistan methamphetamine heroin laboratory seizure trafficking'},
   ]};
 assert.equal(h.broadGdeltQuery(gdeltPlan),'afghanistan (methamphetamine OR fentanyl OR cartel)');
});
test('GDELT broad query falls back to the heuristic when the planner gives too few broad terms',()=>{
 const h=harness();
 const gdeltPlan={
   gdelt_broad_terms:['opium'],
   queries:[
     {language:'en',variant:'primary',query:'Afghanistan opium cultivation ban enforcement decree'},
     {language:'en',variant:'secondary',query:'Afghanistan methamphetamine heroin laboratory seizure trafficking'},
   ]};
 const q=h.broadGdeltQuery(gdeltPlan);
 assert.ok(q.startsWith('afghanistan ('),q);
 assert.ok(!/\bban\b/.test(q)&&!/\benforcement\b/.test(q),'should still use the deprioritised heuristic, not the raw single AI term: '+q);
});
test('GDELT broad query prefers specific topic nouns from both primary and secondary over generic administrative words',()=>{
 const h=harness();
 const gdeltPlan={queries:[
   {language:'en',variant:'primary',query:'Afghanistan opium cultivation ban enforcement decree'},
   {language:'en',variant:'secondary',query:'Afghanistan methamphetamine heroin laboratory seizure trafficking'},
 ]};
 const q=h.broadGdeltQuery(gdeltPlan);
 assert.ok(q.startsWith('afghanistan ('),q);
 assert.ok(q.includes('methamphetamine')||q.includes('heroin'),'secondary-only drug nouns must not be crowded out: '+q);
 assert.ok(!q.includes(' ban ')&&!q.includes('(ban')&&!/\bban\b/.test(q),'generic "ban" should be deprioritised out of the top 4: '+q);
 assert.ok(!/\benforcement\b/.test(q),'generic "enforcement" should be deprioritised out of the top 4: '+q);
});
test('buildEvidence guarantees English at least a third of the final evidence even when another language ranks higher throughout',()=>{
 const h=harness();
 const arabicRow=(n)=>({title:`Ministry of Interior attack report ${n}`,summary:'attack operation',source:'Ministry of Interior',url:`https://x/ar${n}`,published:new Date().toISOString(),language:'ar',search_query:'attack',sources:[{},{},{}]});
 const englishRow=(n)=>({title:`Old blog post ${n}`,summary:'unrelated commentary',source:'Random Blog',url:`https://x/en${n}`,published:new Date(Date.now()-90*86400000).toISOString(),language:'en',search_query:'attack',sources:[{}]});
 const rows=[...Array.from({length:7},(_,i)=>arabicRow(i)),...Array.from({length:5},(_,i)=>englishRow(i))];
 const evidence=h.buildEvidence(rows,['en']);
 assert.equal(evidence.length,12);
 const englishCount=evidence.filter(e=>e.language==='en').length;
 assert.ok(englishCount>=Math.ceil(12/3),`expected at least 4 English items even though Arabic ranks higher throughout, got ${englishCount}`);
});
test('buildEvidence never fabricates English items beyond what was actually retrieved',()=>{
 const h=harness();
 const rows=[{title:'Only Arabic item',summary:'x',source:'x',url:'https://x/1',published:new Date().toISOString(),language:'ar',search_query:'x',sources:[{}]}];
 const evidence=h.buildEvidence(rows,['en']);
 assert.equal(evidence.length,1);
 assert.equal(evidence.filter(e=>e.language==='en').length,0);
});
test('a date explicitly named in the question widens the search period instead of returning "no coverage"',()=>{
 // Regression test for the real user report: "...Herat province on 10 april
 // 2026" with the 30-day dropdown default silently never reaching back to
 // April -- the period must widen to actually cover the named date.
 const h=harness();
 const q='Killing of civilians Shia Shrine in Herat province on 10 april 2026';
 const resolved=h.resolveEffectivePeriodDays(q,30);
 assert.equal(resolved.widened,true);
 assert.ok(resolved.periodDays>=resolved.detected_days_ago,`period ${resolved.periodDays} must cover ${resolved.detected_days_ago} days ago`);
 assert.ok(h.DEEP_SEARCH_LANGUAGE_CODES.length>0); // sanity: harness context loaded correctly
});
test('resolveEffectivePeriodDays never narrows an already-sufficient period, and handles month-day-year and ISO dates',()=>{
 const h=harness();
 assert.equal(h.resolveEffectivePeriodDays('generic question with no date',90).widened,false);
 const monthNames=['January','February','March','April','May','June','July','August','September','October','November','December'];
 const fiftyDaysAgo=new Date(Date.now()-50*86400000);
 const mdY=`${monthNames[fiftyDaysAgo.getUTCMonth()]} ${fiftyDaysAgo.getUTCDate()}, ${fiftyDaysAgo.getUTCFullYear()}`;
 assert.equal(h.resolveEffectivePeriodDays(`something on ${mdY}`,90).widened,false,'a 90-day period already covers a date only ~50 days ago');
 const isoStr=fiftyDaysAgo.toISOString().slice(0,10);
 const iso=h.resolveEffectivePeriodDays(`event on ${isoStr}`,7);
 assert.equal(iso.widened,true);
 assert.equal(iso.periodDays,90,'a ~50-day-old date must widen a 7-day request up to the next allowed bucket (90)');
});
test('isLikelyTransientFetchIssue flags a zero-result report only when every single wave failed',()=>{
 // Regression test for a real report: "AI in terrorism" over 1 year came
 // back with 0 results because every one of 35 search waves got a 503
 // (Google News) or 429 (GDELT) from Cloudflare's shared egress IPs -- a
 // transient infrastructure condition, not evidence that no coverage
 // exists. Confirmed live: the same Google News query succeeded (HTTP 200)
 // from a non-Cloudflare IP at the same time.
 const h=harness();
 const allFailed=[{ok:false},{ok:false},{ok:false}];
 assert.equal(h.isLikelyTransientFetchIssue(allFailed),true);
 const someSucceeded=[{ok:false},{ok:true},{ok:false}];
 assert.equal(h.isLikelyTransientFetchIssue(someSucceeded),false,'even one successful wave means this is a real (if sparse) search, not a wholesale outage');
 assert.equal(h.isLikelyTransientFetchIssue([]),false,'no waves at all is a different failure mode (e.g. planner error), not a fetch outage');
});
test('pdfDisplayUrl truncates long URLs so the PDF never renders a 200+ char unbroken string',()=>{
 const js=fs.readFileSync('deep-search.js','utf8');
 const fn=js.slice(js.indexOf('function pdfDisplayUrl'),js.indexOf('\nasync function downloadPdf'));
 const c=vm.createContext({});
 vm.runInContext(fn,c);
 const longUrl='https://news.google.com/rss/articles/'+'A'.repeat(250)+'?oc=5';
 const result=vm.runInContext('pdfDisplayUrl',c)(longUrl);
 assert.ok(result.length<=101,'expected truncation to ~100 chars, got '+result.length);
 assert.ok(result.endsWith('…'));
 assert.ok(longUrl.startsWith(result.slice(0,-1)));
 const shortUrl='https://example.com/short';
 assert.equal(vm.runInContext('pdfDisplayUrl',c)(shortUrl),shortUrl);
});
test('long PDF export renders bounded canvases and advances to the final page',async()=>{
 const js=fs.readFileSync('deep-search.js','utf8');
 const fn=js.slice(js.indexOf('async function savePagedPdf'),js.indexOf('\nfunction pdfSafeName'));
 const captures=[];let images=0,saved=false;
 const c=vm.createContext({window:{jspdf:{jsPDF:class{addPage(){}addImage(){images++}save(){saved=true}}},html2canvas:async(s,o)=>{captures.push(o);return {width:1560,height:o.height*2,toDataURL:()=>''}}}});
 vm.runInContext(fn,c);
 await c.savePagedPdf({offsetWidth:780,scrollHeight:45000,getBoundingClientRect:()=>({top:0}),querySelectorAll:()=>[]},'test.pdf');
 assert.ok(saved);assert.ok(images>35);assert.ok(captures.every(o=>o.height<=1130));
 assert.equal(captures.at(-1).y+captures.at(-1).height,45000);
});
