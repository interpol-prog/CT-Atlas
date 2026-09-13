const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('cloudflare-worker/feedback.js','utf8').replace(/^import[\s\S]*?from "\.\/shared.js";\s*/,'').replace(/export /g,'');

function harness(){
 const c=vm.createContext({cleanText:(v,n)=>String(v||'').trim().slice(0,n)});
 vm.runInContext(source,c);
 return vm.runInContext('({buildEmail,FEEDBACK_VERSION})',c);
}

test('buildEmail formats an evaluation submission with ratings and comments',()=>{
 const h=harness();
 const {subject,text}=h.buildEmail('group-i-4',{
  kind:'evaluation',
  ratings:{report_generator:5,deep_search:3,ct_atlas_ai:4},
  comments:'Deep Search sometimes reads the period wrong.'
 });
 assert.match(subject,/evaluation from group-i-4/);
 assert.match(text,/Tester: group-i-4/);
 assert.match(text,/Report Generator: 5\/5/);
 assert.match(text,/Deep Search \(BETA\): 3\/5/);
 assert.match(text,/CT Atlas AI: 4\/5/);
 assert.match(text,/Deep Search sometimes reads the period wrong\./);
});

test('buildEmail marks an out-of-range or missing rating as not rated, never a bogus number',()=>{
 const h=harness();
 const {text}=h.buildEmail('admin',{kind:'evaluation',ratings:{report_generator:0,deep_search:9},comments:''});
 assert.match(text,/Report Generator: \(not rated\)/);
 assert.match(text,/Deep Search \(BETA\): \(not rated\)/);
 assert.match(text,/CT Atlas AI: \(not rated\)/);
 assert.match(text,/Comments:\n\(none\)/);
});

test('buildEmail formats an issue report with category and description',()=>{
 const h=harness();
 const {subject,text}=h.buildEmail('group-p-2',{
  kind:'issue',
  category:'Bug',
  description:'Deep Search returned an empty report for a valid question.'
 });
 assert.match(subject,/issue from group-p-2/);
 assert.match(text,/Category: Bug/);
 assert.match(text,/Deep Search returned an empty report for a valid question\./);
});

test('FEEDBACK_VERSION is exported',()=>{
 const h=harness();
 assert.equal(typeof h.FEEDBACK_VERSION,'string');
 assert.ok(h.FEEDBACK_VERSION.length>0);
});
