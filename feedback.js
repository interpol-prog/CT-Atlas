(function(){
"use strict";

const API_BASE="https://ct-report-generator.fairpeace.workers.dev";
const TOKEN_KEY="ct_map_session_token";
const USER_KEY="ct_map_username";
let backendReady=false;

function token(){return String(sessionStorage.getItem(TOKEN_KEY)||"");}
function user(){return String(sessionStorage.getItem(USER_KEY)||"").trim().toLowerCase();}

function ensureCss(){
  if(document.getElementById("feedbackCss"))return;
  const link=document.createElement("link");
  link.id="feedbackCss";
  link.rel="stylesheet";
  link.href="feedback.css?v=1";
  document.head.appendChild(link);
}

// Anchors off the Deep Search button when present (falls back to Report
// Generator, and retries briefly) so it never depends on deep-search.js's
// own load timing -- same pattern quick-ask.js used before it moved to the
// small Download Map button group.
function findAnchor(){
  return document.getElementById("deepSearchButton")||document.getElementById("reportGeneratorButton");
}

function ratingScale(name){
  return [1,2,3,4,5].map(n=>
    `<label class="fb-scale-opt"><input type="radio" name="${name}" value="${n}"><span>${n}</span></label>`
  ).join("");
}

function inject(){
  ensureCss();
  if(document.getElementById("feedbackPanel"))return;

  const anchor=findAnchor();
  if(!anchor){setTimeout(inject,150);return;}

  if(!document.getElementById("feedbackButton")){
    const button=document.createElement("button");
    button.id="feedbackButton";
    button.type="button";
    button.textContent="SEND FEEDBACK";
    anchor.insertAdjacentElement("afterend",button);
  }

  document.body.insertAdjacentHTML("beforeend",`
    <div id="feedbackPanel" aria-hidden="true">
      <div id="feedbackWindow" role="dialog" aria-modal="true" aria-labelledby="feedbackTitle">
        <div id="feedbackHeader">
          <div>
            <div id="feedbackTitle">SEND FEEDBACK</div>
            <div id="feedbackSubtitle">Sent directly to the CT Atlas team -- rate the tools, or report a problem any time.</div>
          </div>
          <button id="feedbackClose" type="button" aria-label="Close feedback">×</button>
        </div>
        <div id="feedbackBody">
          <div class="fb-tabs">
            <button class="fb-tab active" type="button" data-tab="evaluation">General evaluation</button>
            <button class="fb-tab" type="button" data-tab="issue">Report an issue</button>
          </div>

          <div class="fb-pane active" data-pane="evaluation">
            <div class="fb-rating">
              <span class="fb-rating-label">Report Generator</span>
              <div class="fb-scale">${ratingScale("fb-rg")}</div>
            </div>
            <div class="fb-rating">
              <span class="fb-rating-label">Deep Search (BETA)</span>
              <div class="fb-scale">${ratingScale("fb-ds")}</div>
            </div>
            <div class="fb-rating">
              <span class="fb-rating-label">CT Atlas AI</span>
              <div class="fb-scale">${ratingScale("fb-ai")}</div>
            </div>
            <label class="fb-field" style="margin-top:14px">
              <span>WHAT'S WORKING WELL / WHAT'S MISSING</span>
              <textarea id="fbEvalComments" maxlength="3000" placeholder="Optional, but very useful"></textarea>
            </label>
            <button class="fb-submit" type="button" data-submit="evaluation">SEND EVALUATION</button>
          </div>

          <div class="fb-pane" data-pane="issue">
            <label class="fb-field">
              <span>CATEGORY</span>
              <select id="fbIssueCategory">
                <option value="Bug">Bug / error</option>
                <option value="Incorrect data">Incorrect or misleading data</option>
                <option value="Confusing UI">Confusing or hard to use</option>
                <option value="Missing feature">Missing feature</option>
                <option value="Other">Other</option>
              </select>
            </label>
            <label class="fb-field">
              <span>WHAT HAPPENED?</span>
              <textarea id="fbIssueDescription" maxlength="3000" placeholder="Describe the problem -- what you did, what you expected, what happened instead"></textarea>
            </label>
            <button class="fb-submit" type="button" data-submit="issue">SEND ISSUE REPORT</button>
          </div>

          <div id="feedbackStatus" class="fb-status"></div>
        </div>
      </div>
    </div>`);

  document.getElementById("feedbackButton")?.addEventListener("click",open);
  document.getElementById("feedbackClose")?.addEventListener("click",close);
  document.getElementById("feedbackPanel")?.addEventListener("click",event=>{if(event.target.id==="feedbackPanel")close();});
  document.querySelectorAll(".fb-tab").forEach(tab=>tab.addEventListener("click",()=>switchTab(tab.dataset.tab)));
  document.querySelectorAll("[data-submit]").forEach(btn=>btn.addEventListener("click",()=>submit(btn.dataset.submit)));
  checkBackend();
}

function switchTab(name){
  document.querySelectorAll(".fb-tab").forEach(tab=>tab.classList.toggle("active",tab.dataset.tab===name));
  document.querySelectorAll(".fb-pane").forEach(pane=>pane.classList.toggle("active",pane.dataset.pane===name));
  setStatus("");
}

async function checkBackend(){
  const button=document.getElementById("feedbackButton");
  if(!button)return;
  try{
    const response=await fetch(API_BASE+"/health",{cache:"no-store"});
    const payload=await response.json().catch(()=>({}));
    backendReady=Boolean(response.ok&&payload.feedback_version);
  }catch(_){backendReady=false;}
  if(backendReady){
    button.disabled=false; button.textContent="SEND FEEDBACK"; button.title="Send an evaluation or report a problem -- goes directly to the CT Atlas team.";
  }else{
    button.disabled=true; button.textContent="SEND FEEDBACK · DEPLOY PENDING";
    button.title="Feedback backend is not currently available.";
  }
}

function open(){
  const panel=document.getElementById("feedbackPanel");
  panel?.classList.add("open"); panel?.setAttribute("aria-hidden","false");
}
function close(){
  const panel=document.getElementById("feedbackPanel");
  panel?.classList.remove("open"); panel?.setAttribute("aria-hidden","true");
}
function setStatus(message,type=""){
  const status=document.getElementById("feedbackStatus");
  if(!status)return;
  status.textContent=message; status.className=type?"fb-status "+type:"fb-status";
}

function ratingValue(name){
  const checked=document.querySelector(`input[name="${name}"]:checked`);
  return checked?Number(checked.value):null;
}

async function submit(kind){
  if(!backendReady){setStatus("Feedback backend is not available.","warning");return;}
  const username=user(), sessionToken=token();
  if(!username||!sessionToken){setStatus("Sending feedback requires an authenticated CT Atlas session. Sign in again.","error");return;}

  const button=document.querySelector(`[data-submit="${kind}"]`);
  let payload={user_id:username,kind};

  if(kind==="evaluation"){
    payload.ratings={
      report_generator:ratingValue("fb-rg"),
      deep_search:ratingValue("fb-ds"),
      ct_atlas_ai:ratingValue("fb-ai")
    };
    payload.comments=String(document.getElementById("fbEvalComments")?.value||"").trim();
  }else{
    const description=String(document.getElementById("fbIssueDescription")?.value||"").trim();
    if(description.length<5){setStatus("Please describe the issue.","warning");return;}
    payload.category=String(document.getElementById("fbIssueCategory")?.value||"Other");
    payload.description=description;
  }

  if(button){button.disabled=true;button.textContent="SENDING…";}
  setStatus("Sending…","working");

  try{
    const response=await fetch(API_BASE+"/feedback",{
      method:"POST",
      headers:{"Content-Type":"application/json","X-Session-Token":sessionToken},
      body:JSON.stringify(payload)
    });
    const result=await response.json().catch(()=>({}));
    if(!response.ok){
      const retry=Number(result.retry_after_seconds||0);
      throw new Error((result.error||"Sending feedback failed.")+(retry?` Retry in approximately ${Math.ceil(retry/60)} minute(s).`:""));
    }
    setStatus(kind==="evaluation"?"Evaluation sent -- thank you.":"Issue report sent -- thank you.","success");
    if(kind==="evaluation"){
      document.querySelectorAll('#feedbackPanel [data-pane="evaluation"] input[type="radio"]').forEach(r=>r.checked=false);
      document.getElementById("fbEvalComments").value="";
    }else{
      document.getElementById("fbIssueDescription").value="";
    }
  }catch(error){setStatus(error?.message||"Sending feedback failed.","error");}
  finally{
    if(button){button.disabled=false;button.textContent=kind==="evaluation"?"SEND EVALUATION":"SEND ISSUE REPORT";}
  }
}

document.addEventListener("keydown",event=>{if(event.key==="Escape")close();});
document.addEventListener("DOMContentLoaded",inject);
if(document.readyState!=="loading")inject();
})();
