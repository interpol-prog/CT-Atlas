import{ALLOWED_USERS,REPORT_COOLDOWN_MS,SESSION_TTL_MS,normalizeUsername,isAllowedUser,parisDayKey,usageTemplate}from"./shared.js";
export class ReportGate{
constructor(state,env){this.state=state;this.env=env;}
async incrementUsage(username,metrics={},now=Date.now()){
username=normalizeUsername(username);if(!isAllowedUser(username))return null;
const totalKey=`usage-total:${username}`,dayKey=`usage-day:${parisDayKey(now)}:${username}`;
const[currentTotal,currentDay]=await Promise.all([this.state.storage.get(totalKey),this.state.storage.get(dayKey)]);
const total={...usageTemplate(username),...(currentTotal||{})},day={...usageTemplate(username),...(currentDay||{})};
for(const[metric,raw]of Object.entries(metrics||{})){const value=Number(raw||0);if(!Number.isFinite(value)||value===0||!(metric in total)||metric==="username"||metric==="last_activity")continue;total[metric]=Number(total[metric]||0)+value;day[metric]=Number(day[metric]||0)+value;}
const iso=new Date(now).toISOString();total.last_activity=iso;day.last_activity=iso;await this.state.storage.put({[totalKey]:total,[dayKey]:day});return total;}
async usageStats(period){
const users=Array.from(ALLOWED_USERS),rowsByUser=new Map(users.map(u=>[u,usageTemplate(u)]));
if(period==="all"){
const keys=users.map(u=>`usage-total:${u}`),stored=await this.state.storage.get(keys);
for(const u of users){const value=stored.get(`usage-total:${u}`);if(value)rowsByUser.set(u,{...usageTemplate(u),...value,username:u});}
}else{
const days=period==="today"?1:Number(period),keys=[];
for(let offset=0;offset<days;offset++){const day=parisDayKey(Date.now()-offset*86400000);for(const u of users)keys.push(`usage-day:${day}:${u}`);}
const stored=await this.state.storage.get(keys);
for(const[key,value]of stored.entries()){if(!value)continue;const u=normalizeUsername(String(key).split(":").pop());if(!rowsByUser.has(u))continue;const row=rowsByUser.get(u);for(const metric of["logins","searches","map_searches","event_list_searches","report_requests","reports_generated","cached_reports","blocked_report_requests"])row[metric]=Number(row[metric]||0)+Number(value[metric]||0);const candidate=String(value.last_activity||"");if(candidate&&(!row.last_activity||candidate>row.last_activity))row.last_activity=candidate;}
}
const rows=users.map(u=>rowsByUser.get(u));
const summary={active_users:rows.filter(row=>["logins","searches","report_requests","reports_generated","cached_reports"].some(m=>Number(row[m]||0)>0)).length,logins:0,searches:0,map_searches:0,event_list_searches:0,report_requests:0,reports_generated:0,cached_reports:0,blocked_report_requests:0};
for(const row of rows)for(const metric of["logins","searches","map_searches","event_list_searches","report_requests","reports_generated","cached_reports","blocked_report_requests"])summary[metric]+=Number(row[metric]||0);
const label=period==="today"?"Today · Europe/Paris":period==="7"?"Last 7 days · Europe/Paris":period==="30"?"Last 30 days · Europe/Paris":"All time";
return{period,period_label:label,generated_at:new Date().toISOString(),summary,users:rows};}
async fetch(request){
const url=new URL(request.url),body=await request.json().catch(()=>({})),now=Date.now();
if(url.pathname==="/cache-get"){const entry=await this.state.storage.get("cache:"+body.cacheKey);if(!entry||entry.expires_at<now){if(entry)await this.state.storage.delete("cache:"+body.cacheKey);return Response.json({hit:false});}return Response.json({hit:true,report:entry.report});}
if(url.pathname==="/cache-put"){await this.state.storage.put("cache:"+body.cacheKey,{report:body.report,expires_at:body.expires_at});return Response.json({ok:true});}
if(url.pathname==="/release"){const active=(await this.state.storage.get("active"))||{};if(body.permitId&&active[body.permitId]){delete active[body.permitId];await this.state.storage.put("active",active);}return Response.json({ok:true});}
if(url.pathname==="/session-create"){const username=normalizeUsername(body.username);if(!isAllowedUser(username))return Response.json({error:"Unknown user."},{status:400});const ttl=Math.min(SESSION_TTL_MS,Math.max(5*60*1000,Number(body.ttl_ms||SESSION_TTL_MS)));const sessionToken=crypto.randomUUID()+crypto.randomUUID().replace(/-/g,"");const expiresAt=now+ttl;await this.state.storage.put(`session:${sessionToken}`,{username,created_at:new Date(now).toISOString(),expires_at:expiresAt});return Response.json({session_token:sessionToken,username,expires_at:new Date(expiresAt).toISOString()});}
if(url.pathname==="/session-get"){const token=String(body.session_token||"");if(!token)return Response.json({error:"Missing session."},{status:401});const key=`session:${token}`,session=await this.state.storage.get(key);if(!session||Number(session.expires_at||0)<=now){if(session)await this.state.storage.delete(key);return Response.json({error:"Session expired."},{status:401});}return Response.json({ok:true,username:normalizeUsername(session.username),expires_at:new Date(Number(session.expires_at)).toISOString()});}
if(url.pathname==="/login-record"){const username=normalizeUsername(body.username);if(!isAllowedUser(username))return Response.json({error:"Unknown user."},{status:400});const logs=(await this.state.storage.get("login-logs"))||[];logs.unshift({username,server_time:new Date(now).toISOString(),client_time:String(body.client_time||""),user_agent:String(body.user_agent||"").slice(0,320),country:String(body.country||"").slice(0,16),ip_hash:String(body.ip_hash||"").slice(0,64)});await this.state.storage.put("login-logs",logs.slice(0,500));const counts=(await this.state.storage.get("login-counts"))||{};counts[username]=Number(counts[username]||0)+1;await this.state.storage.put("login-counts",counts);await this.incrementUsage(username,{logins:1},now);return Response.json({ok:true});}
if(url.pathname==="/login-stats"){const logs=(await this.state.storage.get("login-logs"))||[],counts=(await this.state.storage.get("login-counts"))||{};return Response.json({counts,recent_logins:logs.slice(0,100)});}
if(url.pathname==="/usage-record"){const username=normalizeUsername(body.username),action=String(body.action||"");if(!isAllowedUser(username))return Response.json({error:"Unknown user."},{status:400});if(action==="map_search")await this.incrementUsage(username,{searches:1,map_searches:1},now);else if(action==="event_list_search")await this.incrementUsage(username,{searches:1,event_list_searches:1},now);else return Response.json({error:"Unsupported action."},{status:400});return Response.json({ok:true});}
if(url.pathname==="/usage-increment"){const username=normalizeUsername(body.username);if(!isAllowedUser(username))return Response.json({error:"Unknown user."},{status:400});await this.incrementUsage(username,body.metrics||{},now);return Response.json({ok:true});}
if(url.pathname==="/usage-stats"){const period=String(body.period||"today");if(!["today","7","30","all"].includes(period))return Response.json({error:"Unsupported period."},{status:400});return Response.json(await this.usageStats(period));}
if(url.pathname!=="/acquire")return new Response("Not found",{status:404});
const username=normalizeUsername(body.username);if(!isAllowedUser(username))return Response.json({error:"Unknown user."},{status:400});
const active=(await this.state.storage.get("active"))||{};for(const[id,item]of Object.entries(active))if(!item?.started_at||now-item.started_at>180000)delete active[id];
if(Object.keys(active).length>=4){await this.state.storage.put("active",active);return Response.json({error:"Four reports are already being generated. Please retry shortly.",retry_after_seconds:20},{status:429});}
if(Object.values(active).some(item=>item.user_id===username)){await this.state.storage.put("active",active);return Response.json({error:"You already have one report being generated.",retry_after_seconds:15},{status:429});}
if(username!=="admin"){
const lastKey=`report-last:${username}`,last=Number((await this.state.storage.get(lastKey))||0),elapsed=now-last;
if(last&&elapsed<REPORT_COOLDOWN_MS){const remaining=Math.ceil((REPORT_COOLDOWN_MS-elapsed)/1000);await this.incrementUsage(username,{blocked_report_requests:1},now);return Response.json({error:"Report limit: one report every 20 minutes per user. Admin is exempt.",retry_after_seconds:remaining},{status:429});}
}
const dayBucket=parisDayKey(now),globalDayKey=`global-day:${dayBucket}`,globalDay=Number((await this.state.storage.get(globalDayKey))||0);
if(globalDay>=100)return Response.json({error:"Daily report generation limit reached (100/day).",retry_after_seconds:3600},{status:429});
if(username!=="admin")await this.state.storage.put(`report-last:${username}`,now);
const permitId=crypto.randomUUID();active[permitId]={user_id:username,started_at:now};await this.state.storage.put({active,[globalDayKey]:globalDay+1});await this.incrementUsage(username,{report_requests:1},now);return Response.json({permit_id:permitId});
}
}
