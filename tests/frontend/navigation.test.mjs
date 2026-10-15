import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {initNavigation} from '../../frontend/js/navigation.js';
const html = await readFile(new URL('../../frontend/index.html', import.meta.url), 'utf8');
function setup(t, hash='') {
  const dom = new JSDOM(html, {url:'http://localhost/'+hash});
  const keys = ['window','document','location','history'];
  const old = Object.fromEntries(keys.map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  for (const k of keys) Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
  t.after(()=>{dom.window.close();for(const k of keys){if(old[k])Object.defineProperty(globalThis,k,old[k]);else delete globalThis[k];}});
  initNavigation();
  return dom.window.document;
}
test('sync is the default and other workspaces take no space', t=>{
  const doc=setup(t);
  assert.equal(doc.querySelector('.panel.active').id,'playlists-panel');
  assert.equal(doc.querySelector('#right-panel').hidden,true);
  assert.equal(doc.querySelector('#player-bar').classList.contains('hidden'),true);
  assert.equal(doc.querySelector('[aria-current="page"]').textContent.trim(),'↻同期');
});
test('all four workspaces are reachable and switching retains existing DOM and expanded details',t=>{
  const doc=setup(t);
  const details=doc.querySelector('#sync-add-panel');details.open=true;
  for(const id of ['settings-panel','right-panel','left-panel','playlists-panel']){
    doc.querySelector(`[data-panel="${id}"]`).click();
    assert.equal(doc.querySelector('.panel.active').id,id);
    assert.equal(doc.querySelectorAll('.layout > .panel:not([hidden])').length,1);
  }
  assert.equal(doc.querySelector('#sync-add-panel'),details);
  assert.equal(details.open,true);
});
test('direct file and settings routes open the requested workspace',t=>{
  const doc=setup(t,'#files');
  assert.equal(doc.querySelector('.panel.active').id,'right-panel');
  doc.querySelector('[data-navigate="settings-panel"]').click();
  assert.equal(location.hash,'#settings');
  assert.equal(doc.querySelector('#yt-auth-section').closest('.panel').id,'settings-panel');
});
test('add action opens the addition form without replacing the sync list',t=>{
  const doc=setup(t);
  const list=doc.querySelector('#yt-sync-list');
  doc.querySelector('#open-sync-add').click();
  assert.equal(doc.querySelector('#sync-add-panel').open,true);
  assert.equal(doc.querySelector('#yt-sync-list'),list);
});
