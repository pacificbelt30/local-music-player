import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {api} from '../../frontend/js/api.js';
import {initDownloadPreferenceSettings} from '../../frontend/js/settings.js';
import {initNavigation} from '../../frontend/js/navigation.js';
import {currentDownloadPreferences} from '../../frontend/js/download-preferences.js';
const html=await readFile(new URL('../../frontend/index.html',import.meta.url),'utf8');
let sequence=0;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await tick();}assert.ok(fn());}
async function setup(t,options={}){
  const dom=new JSDOM(html,{url:'http://localhost/#settings'});
  const keys=['window','document','location','history','CustomEvent','EventSource','alert','confirm'];
  const old=Object.fromEntries(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  for(const key of ['window','document','location','history','CustomEvent'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
  Object.defineProperty(globalThis,'EventSource',{value:class{close(){}},configurable:true});
  Object.defineProperty(globalThis,'alert',{value:()=>{},configurable:true});
  Object.defineProperty(globalThis,'confirm',{value:()=>true,configurable:true});
  const original={...api};
  const state={values:{default_audio_format:'m4a',default_audio_quality:'320',account_playlist_method:'api'},writes:[],creates:[],urls:[],accountReads:0,privacyWrites:0};
  let failLoad=options.failLoad;
  api.getSettings=async()=>{if(failLoad){failLoad=false;throw new Error('offline');}return {...state.values};};
  api.updateSettings=async values=>{state.writes.push(values);if(state.rejectSave)throw new Error('save offline');state.values={...state.values,...values};return {...state.values};};
  api.youtubeAuthStatus=async()=>({authenticated:options.authenticated!==false});
  api.youtubeListAccountPlaylists=async()=>{state.accountReads++;return [{playlist_id:'PLown',title:'My playlist',privacy_status:options.private?'private':'public',item_count:2}];};
  api.youtubeListSyncs=async()=>[];
  api.youtubeSetPlaylistPrivacy=async()=>{state.privacyWrites++;};
  api.youtubeCreateSync=async values=>{state.creates.push(values);return {id:1,playlist_id:'PLown',playlist_name:'Shared playlist',enabled:true,track_count:0,...values};};
  api.listUrls=async()=>[];api.listQueue=async()=>[];
  api.addUrl=async values=>{state.urls.push(values);};
  t.after(()=>{Object.assign(api,original);dom.window.close();for(const key of keys){if(old[key])Object.defineProperty(globalThis,key,old[key]);else delete globalThis[key];}});
  initNavigation();initDownloadPreferenceSettings();
  const form=document.querySelector('#download-preferences-form');
  state.form=form;state.field=name=>form.elements.namedItem(name);
  state.submit=()=>form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
  state.change=(name,value)=>{state.field(name).value=value;state.field(name).dispatchEvent(new dom.window.Event('change',{bubbles:true}));};
  state.ready=()=>until(()=>!form.querySelector('[type="submit"]').disabled);
  if(!options.failLoad)await state.ready();
  state.initWorkspaces=async()=>{
    const {initQueue}=await import(`../../frontend/js/queue.js?preferences=${++sequence}`);initQueue();
    const {initPlaylists}=await import(`../../frontend/js/playlists.js?preferences=${++sequence}`);initPlaylists();
    await until(()=>options.authenticated===false?document.querySelector('#yt-connect-btn'):document.querySelector('.yt-add-sync-btn'));
  };
  state.dom=dom;
  return state;
}

test('settings show saved values and video formats disable irrelevant audio quality',async t=>{
  const s=await setup(t);
  assert.equal(s.field('default_audio_format').value,'m4a');assert.equal(s.field('account_playlist_method').value,'api');
  s.change('default_audio_format','mp4');assert.equal(s.field('default_audio_quality').disabled,true);
  s.submit();s.submit();await s.ready();
  assert.equal(s.writes.length,1);assert.equal(s.writes[0].default_audio_format,'mp4');
  assert.match(document.querySelector('#download-preferences-status').textContent,/保存しました/);
});

test('saved defaults update both addition forms and the account API selection without refetching playlists',async t=>{
  const s=await setup(t);await s.initWorkspaces();
  const rows=document.querySelector('#yt-account-playlists');
  s.change('default_audio_format','flac');s.change('default_audio_quality','best');s.submit();await s.ready();
  assert.equal(document.querySelector('#yt-url-format').value,'flac');
  assert.equal(document.querySelector('#add-url-form').elements.namedItem('audio_format').value,'flac');
  document.querySelector('.yt-add-sync-btn').click();
  assert.equal(document.querySelector('#yt-sync-format').value,'flac');
  assert.equal(document.querySelector('input[name="yt-sync-method"]:checked').value,'api');
  document.querySelector('#yt-sync-confirm-btn').click();await until(()=>s.creates.length===1);
  assert.equal(s.creates[0].source_type,undefined);assert.equal(s.creates[0].audio_quality,'best');
  assert.equal(s.accountReads,1);assert.equal(document.querySelector('#yt-account-playlists'),rows);
});

test('saving URL mode changes the default method without changing playlist privacy',async t=>{
  const s=await setup(t);await s.initWorkspaces();s.change('account_playlist_method','url');s.submit();await s.ready();
  document.querySelector('.yt-add-sync-btn').click();
  assert.equal(document.querySelector('input[name="yt-sync-method"]:checked').value,'url');
  document.querySelector('#yt-sync-confirm-btn').click();await until(()=>s.creates.length===1);
  assert.equal(s.creates[0].source_type,'url');assert.equal(s.privacyWrites,0);
});

test('private account playlist stays private and defaults to API even when URL mode is saved',async t=>{
  const s=await setup(t,{private:true});s.change('account_playlist_method','url');s.submit();await s.ready();await s.initWorkspaces();
  document.querySelector('.yt-add-sync-btn').click();
  assert.equal(document.querySelector('input[name="yt-sync-method"]:checked').value,'api');
  document.querySelector('#yt-sync-confirm-btn').click();await until(()=>s.creates.length===1);
  assert.equal(s.privacyWrites,0);assert.equal(s.creates[0].source_type,undefined);
});

test('someone else shared playlist can be added without YouTube login even with API mode saved',async t=>{
  const s=await setup(t,{authenticated:false});await s.initWorkspaces();
  document.querySelector('#open-sync-add').click();
  assert.match(document.querySelector('#yt-url-sync-section').textContent,/自分のもの以外/);
  document.querySelector('#yt-playlist-url-input').value='https://www.youtube.com/playlist?list=PLsomeone';
  document.querySelector('#yt-add-url-btn').click();await until(()=>s.creates.length===1);
  assert.deepEqual(s.creates[0],{source_type:'url',source_url:'https://www.youtube.com/playlist?list=PLsomeone',audio_format:'m4a',audio_quality:'320'});
  assert.equal(s.accountReads,0);
});

test('single download uses defaults and an explicit per-download override is retained',async t=>{
  const s=await setup(t);await s.initWorkspaces();
  const form=document.querySelector('#add-url-form');form.elements.namedItem('url').value='https://youtu.be/jNQXAC9IVRw';
  const format=form.elements.namedItem('audio_format');format.value='ogg';format.dispatchEvent(new s.dom.window.Event('change'));
  s.change('default_audio_format','flac');s.submit();await s.ready();
  assert.equal(format.value,'ogg');
  form.dispatchEvent(new s.dom.window.Event('submit',{cancelable:true}));await until(()=>s.urls.length===1);
  assert.equal(s.urls[0].audio_format,'ogg');assert.equal(s.urls[0].audio_quality,'320');
});

test('save failure retains the last applied settings and allows retry',async t=>{
  const s=await setup(t);s.rejectSave=true;s.change('default_audio_format','ogg');s.submit();await s.ready();
  assert.match(document.querySelector('#download-preferences-status').textContent,/save offline/);
  assert.equal(currentDownloadPreferences().default_audio_format,'m4a');assert.equal(s.field('default_audio_format').value,'ogg');
  s.rejectSave=false;s.submit();await s.ready();assert.equal(currentDownloadPreferences().default_audio_format,'ogg');
});

test('failed initial settings load disables saving and can be retried',async t=>{
  const s=await setup(t,{failLoad:true});await until(()=>!document.querySelector('#download-preferences-retry').hidden);
  assert.equal(s.form.querySelector('[type="submit"]').disabled,true);
  document.querySelector('#download-preferences-retry').click();await s.ready();assert.equal(s.field('default_audio_format').value,'m4a');
});
