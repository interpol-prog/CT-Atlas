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

test('buildEmail formats an evaluation submission with a rating AND its own comment right underneath, per item',()=>{
 const h=harness();
 const {subject,text}=h.buildEmail('group-i-4',{
  kind:'evaluation',
  ratings:{report_generator:5,deep_search:3,ct_atlas_ai:4},
  item_comments:{
   report_generator:'Rock solid.',
   deep_search:'Sometimes reads the period wrong.'
  },
  other_comments:'Would like a dark-mode toggle.'
 });
 assert.match(subject,/evaluation from group-i-4/);
 assert.match(text,/Tester: group-i-4/);
 assert.match(text,/Report Generator: 5\/5\n {2}Comment: Rock solid\./);
 assert.match(text,/Deep Search \(BETA\): 3\/5\n {2}Comment: Sometimes reads the period wrong\./);
 assert.match(text,/CT Atlas AI: 4\/5/);
 assert.match(text,/Other:\nWould like a dark-mode toggle\./);
});

test('buildEmail marks an out-of-range or missing rating as not rated, never a bogus number, and covers every listed feature',()=>{
 const h=harness();
 const {text}=h.buildEmail('admin',{kind:'evaluation',ratings:{report_generator:0,deep_search:9},item_comments:{},other_comments:''});
 assert.match(text,/Report Generator: \(not rated\)/);
 assert.match(text,/Deep Search \(BETA\): \(not rated\)/);
 assert.match(text,/CT Atlas AI: \(not rated\)/);
 for(const label of ['Heat Map','Situation 24H','Weekly Analysis','Key Developments','Events Database','Security Features']){
  assert.match(text,new RegExp(`${label}: \\(not rated\\)`),`missing evaluation item: ${label}`);
 }
 assert.match(text,/Other:\n\(none\)/);
});

test('buildEmail omits the per-item Comment line when that item has no comment, instead of printing an empty one',()=>{
 const h=harness();
 const {text}=h.buildEmail('group-s-1',{kind:'evaluation',ratings:{report_generator:5},item_comments:{report_generator:''}});
 assert.match(text,/Report Generator: 5\/5\n\n/);
 assert.ok(!text.includes('Comment: '),'no comment was given, so no "Comment:" line should appear anywhere');
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
