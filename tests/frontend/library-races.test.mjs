import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {api} from '../../frontend/js/api.js';

const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(fn) { for (let i=0;i<100;i++) { if(fn()) return; await tick(); } assert.ok(fn()); }
const track = id => ({id, title:`track ${id}`, download_url:'#'});
async function setup(t) {
  const dom = new JSDOM(await readFile(new URL('../../frontend/index.html',import.meta.url),'utf8'),{url:'http://localhost/'});
  const keys=['window','document','localStorage','Audio'];
  const old=Object.fromEntries(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  for(const key of ['window','document','localStorage']) Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
  Object.defineProperty(globalThis,'Audio',{value:class extends EventTarget{},configurable:true});
  const original=api.listTracks;
  const pending=[];
  api.listTracks=params=>new Promise((resolve,reject)=>pending.push({params,resolve,reject}));
  t.after(()=>{api.listTracks=original;dom.window.close();for(const key of keys){if(old[key])Object.defineProperty(globalThis,key,old[key]);else delete globalThis[key];}});
  const {initLibrary}=await import(`../../frontend/js/library.js?race=${t.name}`);
  initLibrary();
  return {pending, search:async value=>{
    const input=document.querySelector('#search-input');input.value=value;input.dispatchEvent(new dom.window.Event('input'));
    await new Promise(resolve=>setTimeout(resolve,320));
  }};
}

test('new search ignores older successful responses and preserves pagination offset',async t=>{
  const {pending,search}=await setup(t);
  await search('new');
  pending[1].resolve(Array.from({length:50},(_,i)=>track(i+100)));
  await until(()=>document.querySelectorAll('.track-item').length===50);
  pending[0].resolve([track(1)]);await tick();
  assert.equal(document.querySelector('.track-item').dataset.trackId,'100');
  document.querySelector('.load-more-btn').click();
  assert.deepEqual(pending[2].params,{limit:50,offset:50,search:'new'});
  pending[2].resolve([]);await tick();
});

test('older failed response cannot replace current search results',async t=>{
  const {pending,search}=await setup(t);await search('new');
  pending[1].resolve([track(2)]);await until(()=>document.querySelector('.track-item'));
  pending[0].reject(new Error('old failure'));await tick();
  assert.equal(document.querySelector('.track-item').dataset.trackId,'2');
});

test('load more blocks duplicate requests and cannot append to a newer search',async t=>{
  const {pending,search}=await setup(t);
  pending[0].resolve(Array.from({length:50},(_,i)=>track(i)));await until(()=>document.querySelector('.load-more-btn'));
  const button=document.querySelector('.load-more-btn');button.click();button.click();
  assert.equal(pending.length,2);
  await search('new');pending[2].resolve([track(100)]);await until(()=>document.querySelector('.track-item')?.dataset.trackId==='100');
  pending[1].resolve([track(50)]);await tick();
  assert.equal(document.querySelectorAll('.track-item').length,1);
  assert.equal(document.querySelector('.track-item').dataset.trackId,'100');
});
