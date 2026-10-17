import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

async function until(fn){for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setImmediate(r));}assert.ok(fn());}

test('delete failure keeps the row, reports its reason, blocks duplicates and allows retry',async t=>{
  const dom=new JSDOM(await readFile(new URL('../../frontend/index.html',import.meta.url),'utf8'),{url:'http://localhost/'});
  const keys=['window','document','localStorage','Audio','fetch','confirm'];
  const old=Object.fromEntries(keys.map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  for(const key of ['window','document','localStorage'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true,writable:true});
  Object.defineProperty(globalThis,'Audio',{value:class extends EventTarget{},configurable:true});
  t.after(()=>{dom.window.close();for(const key of keys){if(old[key])Object.defineProperty(globalThis,key,old[key]);else delete globalThis[key];}});
  let allow=false,readCount=0,deleteCount=0,finish;
  let records=[{id:1,title:'ファイル1',download_url:'#'},{id:2,title:'ファイル2',download_url:'#'}];
  let response=()=>new Promise(resolve=>{finish=resolve;});
  globalThis.confirm=()=>allow;
  globalThis.fetch=async(path,options)=>{
    if(options.method==='DELETE'){deleteCount++;return response();}
    readCount++;return new Response(JSON.stringify(records),{status:200});
  };
  const {initLibrary}=await import('../../frontend/js/library.js');initLibrary();
  await until(()=>document.querySelectorAll('.track-item').length===2);
  const row=document.querySelector('.track-item'),button=row.querySelector('.delete-track'),retry=row.querySelector('.retry-delete-track'),notice=row.querySelector('.track-delete-feedback');
  button.click();assert.equal(deleteCount,0);
  allow=true;button.click();
  assert.equal(button.disabled,true);assert.equal(row.getAttribute('aria-busy'),'true');
  button.click();retry.click();assert.equal(deleteCount,1);
  finish(new Response(JSON.stringify({detail:'権限がありません <script>bad</script>'}),{status:403}));
  await until(()=>!button.disabled);
  assert.equal(document.querySelector('.track-item'),row);
  assert.equal(readCount,1);
  assert.equal(notice.hidden,false);assert.equal(retry.hidden,false);
  assert.match(notice.textContent,/権限がありません/);
  assert.equal(notice.querySelector('script'),null);
  assert.equal(row.hasAttribute('aria-busy'),false);
  response=()=>{throw new Error('offline');};
  retry.click();await until(()=>!retry.disabled);
  assert.match(notice.textContent,/offline/);assert.equal(readCount,1);
  response=()=>{records=records.filter(r=>r.id!==1);return new Response(null,{status:204});};
  retry.click();await until(()=>document.querySelectorAll('.track-item').length===1);
  assert.equal(document.querySelector('.track-item').dataset.trackId,'2');
  assert.equal(deleteCount,3);
});
