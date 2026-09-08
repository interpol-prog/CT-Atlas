const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('cloudflare-worker/deep-search.js','utf8').replace(/^import[\s\S]*?from "\.\/shared.js";\s*/,'').replace(/export /g,'');
function harness(fetch){
 const c=vm.createContext({fetch,URLSearchParams,AbortSignal,setTimeout:fn=>fn(),cleanText:(v,n)=>String(v||'').trim().slice(0,n)});
 vm.runInContext(source,c);
 return vm.runInContext('({sanitizePlan,retrieveNews,resolvePriorityLanguages,buildEvidence,fetchNewsWave,fetchGdeltWave,broadGdeltQuery,DEEP_SEARCH_LANGUAGE_CODES})',c);
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
test('sparse local feeds get native queries through fallback edition within 32 search calls',async()=>{
 const calls=[];const h=harness(async url=>{calls.push(new URL(url));return new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>');});
 const result=await h.retrieveNews(plan(h),180,['fa','ps','ur']);
 assert.equal(calls.length,32);assert.equal(result.subrequest_budget.search_requests,32);
 const rescue=result.waves.filter(w=>w.query.variant==='priority-locale-rescue');
 assert.deepEqual(Array.from(rescue,w=>w.query.language),['fa','ps','ur']);
 assert.ok(rescue.every(w=>w.query.fallback_locale));
 assert.ok(calls[0].searchParams.get('q').startsWith('fa '));
});
test('five priority languages still stay within the 34-call search budget, well under the 50 subrequest ceiling once the ~9 non-search calls are counted',async()=>{
 const calls=[];const h=harness(async url=>{calls.push(new URL(url));return new Response(url.includes('gdelt')?'{}':'<rss><channel></channel></rss>');});
 const result=await h.retrieveNews(plan(h),30,h.resolvePriorityLanguages('Afghanistan drug trafficking',[]));
 assert.equal(calls.length,34);assert.equal(result.subrequest_budget.search_requests,34);
 assert.ok(result.subrequest_budget.search_requests+9<50);
 const rescue=result.waves.filter(w=>w.query.variant==='priority-locale-rescue');
 assert.equal(rescue.length,5);
});
test('a failing wave is never retried — retries risk blowing the subrequest ceiling on exactly the runs where most waves are failing',async()=>{
 let calls=0;const h=harness(async()=>{calls++;return new Response('rate limited',{status:429});});
 await h.fetchNewsWave({language:'en',query:'q',variant:'primary'},0,30,{hl:'en-US',gl:'US',ceid:'US:en'});
 assert.equal(calls,1);
 calls=0;await h.fetchGdeltWave('en','q',30);
 assert.equal(calls,1);
});
test('HTML 200 provider failures remain distinct from empty RSS',async()=>{
 const h=harness(async url=>new Response(url.includes('gdelt')?'{}':'<html>Unavailable</html>'));
 const r=await h.retrieveNews(plan(h),7,[]);
 assert.ok(r.waves.filter(w=>!w.query.engine).every(w=>!w.ok&&w.error.includes('non-RSS')));
});
test('missing language plans fail explicitly',()=>{assert.throws(()=>harness().sanitizePlan({queries:{}},''),/every required language/);});
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
