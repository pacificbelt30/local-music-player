import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

test('saved playback stays hidden; only explicit preview starts audio and close stops it', async t=>{
  const dom=new JSDOM(await readFile(new URL('../../frontend/index.html',import.meta.url),'utf8'),{url:'http://localhost/'});
  const keys=['window','document','localStorage','Audio','fetch','confirm'];
  const old=Object.fromEntries(keys.map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  for(const k of ['window','document','localStorage'])Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
  let audio;
  class FakeAudio extends EventTarget {
    constructor(){super();audio=this;this.paused=true;this.playCalls=0;this.currentTime=0;}
    play(){this.paused=false;this.playCalls++;return Promise.resolve();}
    pause(){this.paused=true;}
  }
  Object.defineProperty(globalThis,'Audio',{value:FakeAudio,configurable:true});
  const track={id:1,title:'試聴ファイル',artist:'Artist',stream_url:'/stream/1',download_url:'/download/1',duration_secs:60};
  localStorage.setItem('player_playlist',JSON.stringify([track]));localStorage.setItem('player_index','0');
  globalThis.fetch=async()=>new Response(JSON.stringify([track]),{status:200});
  t.after(()=>{dom.window.close();for(const k of keys){if(old[k])Object.defineProperty(globalThis,k,old[k]);else delete globalThis[k];}});
  const {initLibrary}=await import('../../frontend/js/library.js');initLibrary();
  for(let i=0;i<50&&!document.querySelector('.track-item');i++)await new Promise(r=>setImmediate(r));
  const bar=document.querySelector('#player-bar'),row=document.querySelector('.track-item');
  assert.ok(row);
  assert.equal(bar.classList.contains('hidden'),true);
  assert.equal(audio.src,undefined);
  row.click();assert.equal(audio.playCalls,0);
  row.querySelector('.preview-track').click();
  assert.equal(audio.playCalls,1);
  assert.equal(bar.classList.contains('hidden'),false);
  document.querySelector('.close-player').click();
  assert.equal(audio.paused,true);
  assert.equal(bar.classList.contains('hidden'),true);
});
