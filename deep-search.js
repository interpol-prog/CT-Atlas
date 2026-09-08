(function(){
"use strict";

const API_BASE="https://ct-report-generator.fairpeace.workers.dev";
const TOKEN_KEY="ct_map_session_token";
const USER_KEY="ct_map_username";
let lastPayload=null;
let backendReady=false;

function esc(value){
  return String(value??"")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#039;");
}
function token(){return String(sessionStorage.getItem(TOKEN_KEY)||"");}
function user(){return String(sessionStorage.getItem(USER_KEY)||"").trim().toLowerCase();}

function ensureCss(){
  if(document.getElementById("deepSearchCss"))return;
  const link=document.createElement("link");
  link.id="deepSearchCss";
  link.rel="stylesheet";
  link.href="deep-search.css?v=2";
  document.head.appendChild(link);
}

function inject(){
  ensureCss();
  if(document.getElementById("deepSearchPanel"))return;

  const reportButton=document.getElementById("reportGeneratorButton");
  if(reportButton&&!document.getElementById("deepSearchButton")){
    const button=document.createElement("button");
    button.id="deepSearchButton";
    button.type="button";
    button.textContent="DEEP SEARCH";
    reportButton.insertAdjacentElement("afterend",button);
  }

  document.body.insertAdjacentHTML("beforeend",`
    <div id="deepSearchPanel" aria-hidden="true">
      <div id="deepSearchWindow" role="dialog" aria-modal="true" aria-labelledby="deepSearchTitle">
        <div id="deepSearchHeader">
          <div>
            <div id="deepSearchTitle">DEEP SEARCH</div>
            <div id="deepSearchSubtitle">Multilingual ad hoc OSINT search beyond the current CT Atlas database</div>
          </div>
          <button id="deepSearchClose" type="button" aria-label="Close Deep Search">×</button>
        </div>
        <div id="deepSearchBody">
          <div id="deepSearchControls">
            <label class="deep-field deep-question-field">
              <span>ANALYST QUESTION</span>
              <textarea id="deepSearchQuestion" rows="4" maxlength="1200" placeholder="Example: Identify recent reporting on ISKP facilitation networks, local-language sources and potential CT Atlas gaps."></textarea>
            </label>
            <label class="deep-field">
              <span>SEARCH PERIOD</span>
              <select id="deepSearchPeriod">
                <option value="7">Last 7 days</option>
                <option value="30" selected>Last 30 days</option>
                <option value="90">Last 90 days</option>
                <option value="180">Last 6 months</option>
                <option value="365">Last 1 year</option>
              </select>
            </label>
            <div id="deepSearchMethod">
              Deep Search runs two complementary searches in each of the 12 supported languages, retrieves open-source reporting, clusters duplicate coverage, compares results with CT Atlas and generates a source-cited analytical report. Zero-result language searches are automatically retried through a fallback news edition.
            </div>
            <button id="deepSearchRun" type="button">RUN DEEP SEARCH</button>
            <div id="deepSearchStatus"></div>
          </div>

          <div id="deepSearchResult" hidden>
            <div id="deepSearchResultTopline">
              <div>
                <div id="deepSearchResultTitle">DEEP SEARCH REPORT</div>
                <div id="deepSearchResultMeta"></div>
              </div>
              <div id="deepSearchActions">
                <button id="deepSearchCopy" type="button">COPY</button>
                <button id="deepSearchPrint" type="button">PRINT / PDF</button>
              </div>
            </div>

            <div id="deepSearchMetrics"></div>

            <div class="deep-section-head deep-search-coverage-head">SEARCH COVERAGE</div>
            <div id="deepSearchLanguageCoverage"></div>

            <div class="deep-section-head">ANALYTICAL REPORT</div>
            <div id="deepSearchReport"></div>

            <div class="deep-section-head">SOURCES CITED / EVIDENCE PACK</div>
            <div id="deepSearchEvidence"></div>

            <div id="deepSearchDisclaimer">
              Deep Search uses live open-source search results and AI-assisted analysis. Automatic CT Atlas gap matching is approximate. Citation coverage is not a statistical hallucination probability. Source material and significant claims should be independently validated before operational or decision-making use.
            </div>
          </div>
        </div>
      </div>
    </div>`);

  document.getElementById("deepSearchButton")?.addEventListener("click",open);
  document.getElementById("deepSearchClose")?.addEventListener("click",close);
  document.getElementById("deepSearchPanel")?.addEventListener("click",event=>{if(event.target.id==="deepSearchPanel")close();});
  document.getElementById("deepSearchRun")?.addEventListener("click",run);
  document.getElementById("deepSearchCopy")?.addEventListener("click",copyReport);
  document.getElementById("deepSearchPrint")?.addEventListener("click",printReport);
  document.getElementById("deepSearchQuestion")?.addEventListener("keydown",event=>{
    if((event.ctrlKey||event.metaKey)&&event.key==="Enter")run();
  });
  checkBackend();
}

async function checkBackend(){
  const button=document.getElementById("deepSearchButton");
  if(!button)return;
  try{
    const response=await fetch(API_BASE+"/health",{cache:"no-store"});
    const payload=await response.json().catch(()=>({}));
    backendReady=Boolean(response.ok&&payload.deep_search===true);
  }catch(_){backendReady=false;}
  if(backendReady){
    button.disabled=false; button.textContent="DEEP SEARCH"; button.title="Multilingual ad hoc OSINT search";
  }else{
    button.disabled=true; button.textContent="DEEP SEARCH · DEPLOY PENDING";
    button.title="Deep Search backend is not currently available.";
  }
}

function open(){
  const panel=document.getElementById("deepSearchPanel");
  panel?.classList.add("open"); panel?.setAttribute("aria-hidden","false");
  setTimeout(()=>document.getElementById("deepSearchQuestion")?.focus(),30);
}
function close(){
  const panel=document.getElementById("deepSearchPanel");
  panel?.classList.remove("open"); panel?.setAttribute("aria-hidden","true");
}
function setStatus(message,type=""){
  const status=document.getElementById("deepSearchStatus");
  if(!status)return;
  status.textContent=message; status.className=type?"deep-status "+type:"deep-status";
}

function stripFence(value){
  return String(value||"").trim()
    .replace(/^```(?:json|text|markdown)?\s*/i,"")
    .replace(/\s*```$/i,"").trim();
}

function normalizePayload(payload){
  const normalized={...(payload||{})};
  let title=String(normalized.title||"").trim();
  let analysis=String(normalized.analysis||"").trim();

  for(let pass=0;pass<2;pass++){
    const candidate=stripFence(analysis);
    if(!(candidate.startsWith("{")&&candidate.endsWith("}")))break;
    try{
      const nested=JSON.parse(candidate);
      if(!nested||typeof nested!=="object"||!nested.analysis)break;
      title=String(nested.title||title).trim();
      analysis=String(nested.analysis||"").trim();
    }catch(_){break;}
  }

  if(!analysis.includes("\n")&&analysis.includes("\\n")){
    analysis=analysis.replace(/\\n/g,"\n").replace(/\\"/g,'"');
  }
  analysis=stripFence(analysis)
    .replace(/^\*\*```(?:json)?\*\*/i,"")
    .replace(/\*\*```\*\*$/i,"").trim();

  normalized.title=title||"CT Atlas Deep Search";
  normalized.analysis=analysis;
  return normalized;
}

function inlineMarkup(value){
  let safe=esc(value);
  safe=safe.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  safe=safe.replace(/\[(S\d{2}(?:,\s*S\d{2})*)\]/g,(_,ids)=>{
    const label=ids.split(",").map(x=>x.trim()).join(", ");
    return `<span class="deep-citation">[${label}]</span>`;
  });
  return safe;
}

function formatAnalysis(text){
  const clean=stripFence(String(text||"")).replace(/\r\n?/g,"\n");
  const lines=clean.split("\n");
  const out=[];
  let inList=false;

  function closeList(){
    if(inList){out.push("</ul>");inList=false;}
  }

  for(const raw of lines){
    let value=raw.trim();
    if(!value){closeList();continue;}
    value=value.replace(/^#{1,6}\s*/,"").trim();

    if(/^[A-Z][A-Z0-9 /&()’'–—-]{3,}$/.test(value)){
      closeList();
      out.push(`<h4>${inlineMarkup(value)}</h4>`);
      continue;
    }

    if(/^[-•]\s+/.test(value)){
      if(!inList){out.push('<ul class="deep-report-list">');inList=true;}
      out.push(`<li>${inlineMarkup(value.replace(/^[-•]\s+/,""))}</li>`);
      continue;
    }

    closeList();
    out.push(`<p>${inlineMarkup(value)}</p>`);
  }
  closeList();
  return out.join("");
}

function fmtDate(value){
  if(!value)return "Date unavailable";
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return String(value);
  return date.toLocaleString("en-GB",{day:"2-digit",month:"short",year:"numeric"});
}

function languageCoverageHtml(payload){
  const languages=Array.isArray(payload.languages_searched)?payload.languages_searched:[];
  if(!languages.length)return '<div class="deep-language-empty">Language diagnostics unavailable for this cached result.</div>';
  return languages.map(item=>{
    const count=Number(item.article_count||0);
    const queryCount=Number(item.query_count||0);
    const cls=count>0?" has-results":" no-results";
    return `<div class="deep-language${cls}">
      <span class="deep-language-name">${esc(item.name||item.code||"Language")}</span>
      <strong>${count}</strong>
      <small>${count===1?"article":"articles"} · ${queryCount||1} ${queryCount===1?"query":"queries"}</small>
    </div>`;
  }).join("");
}

function evidenceHtml(payload){
  const evidence=Array.isArray(payload.evidence)?payload.evidence:[];
  const cited=new Set(payload.grounding?.cited_source_ids||[]);
  const ordered=[...evidence].sort((a,b)=>(cited.has(b.id)?1:0)-(cited.has(a.id)?1:0));
  return ordered.map(item=>{
    const citedClass=cited.has(item.id)?" cited":"";
    const gap=item.atlas_status==="potential_gap";
    const gapLabel=gap?"POTENTIAL ATLAS GAP":"MATCHED IN CT ATLAS";
    const gapClass=gap?" gap":" matched";
    const extras=Array.isArray(item.additional_sources)?item.additional_sources:[];
    return `
      <article class="deep-evidence${citedClass}">
        <div class="deep-evidence-head">
          <strong>${esc(item.id)}</strong>
          <span class="deep-evidence-source">${esc(item.source||"Source")}</span>
          <span class="deep-gap-badge${gapClass}">${gapLabel}</span>
        </div>
        <div class="deep-evidence-title">${esc(item.title||"")}</div>
        <div class="deep-evidence-meta">${esc(fmtDate(item.published))} · ${esc(String(item.language||"").toUpperCase())}${Number(item.source_count||1)>1?` · ${Number(item.source_count)} merged sources`:""}</div>
        ${item.summary?`<div class="deep-evidence-summary">${esc(item.summary)}</div>`:""}
        <div class="deep-evidence-links">
          ${item.url?`<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">OPEN ARTICLE</a>`:""}
          ${item.atlas_match_id?`<span>Atlas match: ${esc(item.atlas_match_title||item.atlas_match_id)} (${Number(item.atlas_match_score||0)}%)</span>`:""}
        </div>
        ${extras.length?`<details><summary>${extras.length} additional merged source${extras.length===1?"":"s"}</summary>${extras.map(source=>`<div class="deep-extra-source">${esc(source.source||"Source")} · ${esc(fmtDate(source.published))}${source.url?` · <a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">open</a>`:""}</div>`).join("")}</details>`:""}
      </article>`;
  }).join("");
}

function render(rawPayload){
  const payload=normalizePayload(rawPayload);
  lastPayload=payload;
  const result=document.getElementById("deepSearchResult");
  if(result)result.hidden=false;
  document.getElementById("deepSearchResultTitle").textContent=payload.title||"DEEP SEARCH REPORT";

  const languages=(payload.languages_searched||[]).map(item=>item.name||item.code).join(", ");
  const retrieved=payload.retrieval||{};
  document.getElementById("deepSearchResultMeta").textContent=
    `Generated ${new Date(payload.generated_at||Date.now()).toLocaleString("en-GB")} · ${payload.model||"Gemini"} · ${languages||"multilingual"}${payload.cached?" · CACHED":""}`;

  document.getElementById("deepSearchMetrics").innerHTML=`
    <div class="deep-metric"><span>ARTICLES</span><strong>${Number(retrieved.articles_retrieved||0)}</strong></div>
    <div class="deep-metric"><span>UNIQUE EVENTS</span><strong>${Number(retrieved.unique_event_clusters||0)}</strong></div>
    <div class="deep-metric"><span>EVIDENCE USED</span><strong>${Number(retrieved.evidence_events_used_for_analysis||0)}</strong></div>
    <div class="deep-metric"><span>ATLAS MATCHES</span><strong>${Number(retrieved.matched_to_atlas||0)}</strong></div>
    <div class="deep-metric"><span>POTENTIAL GAPS</span><strong>${Number(retrieved.potential_atlas_gaps||0)}</strong></div>
    <div class="deep-metric"><span>CITATION COVERAGE</span><strong>${Number(payload.grounding?.citation_coverage_percent||0)}%</strong></div>`;

  document.getElementById("deepSearchLanguageCoverage").innerHTML=languageCoverageHtml(payload);
  document.getElementById("deepSearchReport").innerHTML=formatAnalysis(payload.analysis||"");
  document.getElementById("deepSearchEvidence").innerHTML=evidenceHtml(payload);
}

async function run(){
  if(!backendReady){setStatus("Deep Search backend is not available.","warning");return;}
  const question=String(document.getElementById("deepSearchQuestion")?.value||"").trim();
  const period=Number(document.getElementById("deepSearchPeriod")?.value||30);
  const username=user(), sessionToken=token(), button=document.getElementById("deepSearchRun");
  if(question.length<8){setStatus("Enter a more specific analyst question.","warning");return;}
  if(!username||!sessionToken){setStatus("Deep Search requires an authenticated CT Atlas session. Sign in again.","error");return;}

  if(button){button.disabled=true;button.textContent="SEARCHING MULTILINGUAL SOURCES…";}
  const result=document.getElementById("deepSearchResult");
  if(result)result.hidden=true;
  setStatus("Building multilingual search plan, retrieving fresh reporting and comparing it with CT Atlas…","working");

  try{
    const response=await fetch(API_BASE+"/deep-search",{
      method:"POST",
      headers:{"Content-Type":"application/json","X-Session-Token":sessionToken},
      body:JSON.stringify({user_id:username,question,period_days:period})
    });
    const payload=await response.json().catch(()=>({}));
    if(!response.ok){
      const retry=Number(payload.retry_after_seconds||0);
      throw new Error((payload.error||"Deep Search failed.")+(retry?` Retry in approximately ${Math.ceil(retry/60)} minute(s).`:""));
    }
    render(payload);
    setStatus(`Deep Search complete · ${Number(payload.retrieval?.articles_retrieved||0)} articles · ${Number(payload.retrieval?.unique_event_clusters||0)} unique event clusters · ${Number(payload.retrieval?.potential_atlas_gaps||0)} potential CT Atlas gaps.`,"success");
  }catch(error){setStatus(error?.message||"Deep Search failed.","error");}
  finally{if(button){button.disabled=false;button.textContent="RUN DEEP SEARCH";}}
}

async function copyReport(){
  if(!lastPayload)return;
  const cited=new Set(lastPayload.grounding?.cited_source_ids||[]);
  const sourceText=(lastPayload.evidence||[]).filter(item=>cited.has(item.id))
    .map(item=>`${item.id} — ${item.source} — ${item.title} — ${item.url}`).join("\n");
  const text=`${lastPayload.title||"CT Atlas Deep Search"}\n\nQuestion: ${lastPayload.question||""}\n\n${lastPayload.analysis||""}\n\nSOURCES CITED\n${sourceText}`;
  try{await navigator.clipboard.writeText(text);setStatus("Deep Search report and cited sources copied to clipboard.","success");}
  catch(_){setStatus("Clipboard access was unavailable.","warning");}
}

function printReport(){
  if(!lastPayload)return;
  const popup=window.open("","_blank","noopener,noreferrer,width=980,height=800");
  if(!popup){setStatus("Popup blocked. Allow popups to use PRINT / PDF.","warning");return;}
  const cited=new Set(lastPayload.grounding?.cited_source_ids||[]);
  const sources=(lastPayload.evidence||[]).filter(item=>cited.has(item.id));
  const coverage=languageCoverageHtml(lastPayload);
  popup.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(lastPayload.title||"Deep Search")}</title>
  <style>body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;color:#111;line-height:1.55}h1{font-size:24px}h2{margin-top:32px;font-size:16px;border-bottom:1px solid #ddd;padding-bottom:5px}h4{font-size:13px;margin:22px 0 8px;color:#174d70}p{margin:8px 0}ul{margin:7px 0 12px 20px}.meta{color:#555;font-size:12px}.source{border-top:1px solid #ddd;padding:10px 0;font-size:12px}.source a{color:#0645ad}.deep-language{display:inline-block;border:1px solid #ccc;padding:6px 8px;margin:3px;font-size:11px}.deep-language strong{margin-left:7px}.deep-language small{display:block;color:#666}.deep-citation{font-weight:bold;color:#8a6518}</style>
  </head><body><h1>${esc(lastPayload.title||"CT Atlas Deep Search")}</h1>
  <div class="meta">Question: ${esc(lastPayload.question||"")} · Generated ${esc(new Date(lastPayload.generated_at||Date.now()).toLocaleString("en-GB"))}</div>
  <h2>SEARCH COVERAGE</h2><div>${coverage}</div>
  <h2>ANALYTICAL REPORT</h2>${formatAnalysis(lastPayload.analysis||"")}
  <h2>SOURCES CITED / EVIDENCE PACK</h2>${sources.map(item=>`<div class="source"><strong>${esc(item.id)} · ${esc(item.source)}</strong><br>${esc(item.title)}<br>${esc(fmtDate(item.published))}<br>${item.url?`<a href="${esc(item.url)}">${esc(item.url)}</a>`:""}</div>`).join("")}
  <p class="meta">AI-assisted OSINT analysis. Validate significant claims against source material before operational use.</p></body></html>`);
  popup.document.close(); popup.focus(); setTimeout(()=>popup.print(),250);
}

document.addEventListener("keydown",event=>{if(event.key==="Escape")close();});
document.addEventListener("DOMContentLoaded",inject);
if(document.readyState!=="loading")inject();
})();