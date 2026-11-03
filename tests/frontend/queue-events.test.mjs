import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {api} from '../../frontend/js/api.js';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await tick();}assert.ok(fn());}
const job=(id,status='downloading')=>({id,title:`job ${id}`,status,progress_pct:0});
async function setup(t){
  const dom=new JSDOM(await readFile(new URL('../../frontend/index.html',import.meta.url),'utf8'),{url:'http://localhost/'});
  const keys=['window','document','EventSource'];
  const old=Object.fromEntries(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  let stream;
  for(const key of ['window','document'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
  Object.defineProperty(globalThis,'EventSource',{value:class{constructor(){stream=this;}close(){}},configurable:true});
  const original={listUrls:api.listUrls,listQueue:api.listQueue};
  api.listUrls=async()=>[];
  let records=[job(1)],reads=0,read=async()=>records;
  api.listQueue=()=>{reads++;return read();};
  t.after(()=>{Object.assign(api,original);dom.window.close();for(const key of keys){if(old[key])Object.defineProperty(globalThis,key,old[key]);else delete globalThis[key];}});
  const {initQueue}=await import(`../../frontend/js/queue.js?events=${t.name}`);initQueue();
  await until(()=>document.querySelector('.job-item'));
  return {send:events=>stream.onmessage({data:JSON.stringify(events)}),setRecords:value=>records=value,setRead:fn=>read=fn,reads:()=>reads};
}

test('completed job disappears when the active snapshot becomes empty',async t=>{
  const q=await setup(t);q.setRecords([]);q.send([]);
  await until(()=>!document.querySelector('.job-item'));
  assert.equal(q.reads(),2);
  q.send([]);await tick();assert.equal(q.reads(),2);
});

test('failed job gets retry controls after it leaves active snapshot',async t=>{
  const q=await setup(t);q.setRecords([job(1,'failed')]);q.send([]);
  await until(()=>document.querySelector('.retry-job'));
  assert.equal(document.querySelector('.status-badge').textContent,'failed');
  q.send([]);await tick();assert.equal(q.reads(),2);
});

test('progress updates do not fetch the list; new jobs trigger one fetch at a time',async t=>{
  const q=await setup(t);q.send([{job_id:1,status:'downloading',progress_pct:65}]);
  assert.equal(document.querySelector('.progress-fill').style.width,'65%');assert.equal(q.reads(),1);
  let finish;q.setRead(()=>new Promise(resolve=>{finish=resolve;}));
  const snapshot=[{job_id:1,status:'downloading',progress_pct:66},{job_id:2,status:'pending',progress_pct:0}];
  q.send(snapshot);q.send(snapshot);assert.equal(q.reads(),2);
  finish([job(1),job(2,'pending')]);await until(()=>document.querySelectorAll('.job-item').length===2);
  q.send(snapshot);assert.equal(q.reads(),2);
});

test('snapshot reconciliation retries after a failed list request',async t=>{
  const q=await setup(t);q.setRead(async()=>{throw new Error('offline');});q.send([]);await tick();
  assert.ok(document.querySelector('.job-item'));
  q.setRead(async()=>[]);q.send([]);await until(()=>!document.querySelector('.job-item'));
  assert.equal(q.reads(),3);
});

test('unified intake refreshes the URL list and queue in the download workspace',async t=>{
  const q=await setup(t);api.listUrls=async()=>[{id:2,title:'Added through intake',url:'https://youtu.be/new',url_type:'video',audio_format:'m4a',audio_quality:'192',sync_enabled:true}];
  document.dispatchEvent(new document.defaultView.CustomEvent('url-sources-updated'));
  await until(()=>document.querySelector('.url-item-title')?.textContent==='Added through intake');
  assert.equal(q.reads(),2);
});
