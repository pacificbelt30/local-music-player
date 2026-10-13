import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

const html = await readFile(new URL('../../frontend/index.html', import.meta.url), 'utf8');
let moduleId = 0;
const originalGlobals = Object.fromEntries(['window', 'document', 'location', 'history', 'fetch', 'alert', 'confirm', 'CustomEvent'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
async function until(condition) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.ok(condition(), 'UI did not reach the expected state');
}
const playlist = (id = 'PL1') => ({playlist_id: id, title: 'Playlist ' + id, item_count: 2, privacy_status: 'public', total_duration_secs: 120});
const sync = (id = 1, playlistId = 'PL1') => ({id, playlist_id: playlistId, playlist_name: 'Playlist ' + playlistId, source_type: 'api', audio_format: 'mp3', audio_quality: '192', enabled: true, track_count: 2, downloaded_count: 1, last_synced: null, last_error: 'server error'});
const track = (id = 10) => ({id, title: 'Song ' + id, artist: 'Artist', status: 'failed', error_message: 'track error', duration_secs: 60});

async function setup(t, options = {}) {
  const dom = new JSDOM(html, {url: 'http://localhost/'});
  for (const key of ['window', 'document', 'location', 'history', 'CustomEvent']) {
    Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true, writable: true});
  }
  const state = {playlists: options.playlists || [playlist()], syncs: options.syncs || [sync()], calls: [], handlers: new Map(), alerts: []};
  globalThis.alert = message => state.alerts.push(message);
  globalThis.confirm = () => true;
  globalThis.fetch = async (path, opts = {}) => {
    const method = opts.method || 'GET';
    const key = `${method} ${path}`;
    const body = opts.body ? JSON.parse(opts.body) : null;
    state.calls.push({key, body});
    let value;
    if (state.handlers.has(key)) value = await state.handlers.get(key)(body);
    else if (path.endsWith('/youtube/auth/status')) value = {authenticated: true};
    else if (path.endsWith('/youtube/playlists')) value = state.playlists;
    else if (path.endsWith('/youtube/syncs') && method === 'GET') value = state.syncs;
    else if (path.endsWith('/tracks')) value = [track()];
    else if (/\/syncs\/\d+$/.test(path) && method === 'PATCH') {
      const id = Number(path.split('/').at(-1));
      state.syncs = state.syncs.map(s => s.id === id ? {...s, ...body} : s);
      value = state.syncs.find(s => s.id === id);
    } else if (path.endsWith('/youtube/syncs') && method === 'POST') {
      value = {...sync(2), source_type: body.source_type || 'api', audio_format: body.audio_format};
      state.syncs = [...state.syncs, value];
    } else if (method === 'DELETE') {
      const id = Number(path.match(/\/syncs\/(\d+)/)?.[1]);
      state.syncs = state.syncs.filter(s => s.id !== id);
      return new Response(null, {status: 204});
    } else value = {};
    return value instanceof Response ? value : new Response(JSON.stringify(value), {status: 200, headers: {'Content-Type': 'application/json'}});
  };
  t.after(() => {
    dom.window.close();
    for (const [key, descriptor] of Object.entries(originalGlobals)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  const {initPlaylists} = await import(new URL(`../../frontend/js/playlists.js?test=${++moduleId}`, import.meta.url));
  initPlaylists();
  await until(() => document.querySelector('.yt-pl-item') && (state.syncs.length ? document.querySelector('.yt-sync-card') : document.querySelector('#yt-sync-list .empty-state')));
  state.doc = dom.window.document;
  state.count = key => state.calls.filter(call => call.key === key).length;
  return state;
}

async function expandDetails(state) {
  const card = state.doc.querySelector('.yt-sync-card');
  card.querySelector('.yt-tracks-toggle').click();
  await until(() => card.querySelector('.yt-track-item'));
  card.querySelector('.yt-sync-error-detail-btn').click();
  card.querySelector('.yt-track-error-btn').click();
  return {card, tracks: card.querySelector('.yt-sync-tracks'), track: card.querySelector('.yt-track-item')};
}

test('pause and resume update only the card, preserving tracks, errors, scroll and account rows', async t => {
  const state = await setup(t);
  const {card, tracks, track: trackRow} = await expandDetails(state);
  const accountRow = state.doc.querySelector('.yt-pl-item');
  const toggle = card.querySelector('.yt-sync-toggle-btn');
  const readCount = state.count('GET /api/v1/youtube/playlists');
  tracks.scrollTop = 53;
  toggle.click();
  await until(() => toggle.textContent === '再開');
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  assert.equal(card.querySelector('.yt-sync-tracks'), tracks);
  assert.equal(card.querySelector('.yt-track-item'), trackRow);
  assert.equal(tracks.style.display, '');
  assert.equal(tracks.scrollTop, 53);
  assert.equal(card.querySelector('.yt-sync-error-detail').style.display, '');
  assert.equal(card.querySelector('.yt-track-error-text').style.display, '');
  assert.equal(state.doc.querySelector('.yt-pl-item'), accountRow);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), readCount);
  toggle.click();
  await until(() => toggle.textContent === '一時停止');
  assert.equal(state.count('PATCH /api/v1/youtube/syncs/1'), 2);
});

test('adding another format does not refetch or erase account playlists', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  const account = state.doc.querySelector('.yt-pl-item');
  const button = account.querySelector('.yt-add-sync-btn');
  const readCount = state.count('GET /api/v1/youtube/playlists');
  const pending = deferred();
  state.handlers.set('POST /api/v1/youtube/syncs', async () => {
    await pending.promise;
    const result = {...sync(2), source_type: 'url', audio_format: 'm4a'};
    state.syncs.push(result);
    return result;
  });
  button.click();
  state.doc.getElementById('yt-sync-format').value = 'm4a';
  state.doc.getElementById('yt-sync-confirm-btn').click();
  assert.equal(state.doc.querySelector('.yt-pl-item'), account);
  assert.equal(button.textContent, '追加中…');
  pending.resolve();
  await until(() => state.doc.querySelectorAll('.yt-sync-card').length === 2 && !button.disabled);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), readCount);
  assert.equal(state.doc.querySelector('.yt-pl-item'), account);
  assert.equal(state.doc.querySelector('[data-sync-id="1"]'), card);
  assert.equal(card.querySelector('.yt-sync-tracks'), tracks);
  assert.equal(tracks.style.display, '');
  assert.equal(button.textContent, '+ 別形式で同期');
});

test('slow sync refresh preserves DOM, expanded tracks and keyboard focus before and after response', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  const toggle = card.querySelector('.yt-sync-toggle-btn');
  toggle.focus();
  const pending = deferred();
  state.handlers.set('GET /api/v1/youtube/syncs', () => pending.promise);
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  assert.equal(state.doc.activeElement, toggle);
  pending.resolve([{...sync(), downloaded_count: 2}]);
  await until(() => card.querySelector('.yt-sync-progress').textContent.includes('2/2'));
  assert.equal(state.doc.activeElement, toggle);
  assert.equal(card.querySelector('.yt-sync-tracks'), tracks);
  assert.equal(tracks.style.display, '');
});

test('failed sync refresh preserves cards and retry succeeds without replacing controls', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  state.handlers.set('GET /api/v1/youtube/syncs', () => {throw new Error('offline');});
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  await until(() => state.doc.getElementById('yt-sync-list-status').textContent.includes('offline'));
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  assert.equal(tracks.style.display, '');
  state.handlers.delete('GET /api/v1/youtube/syncs');
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  await until(() => !state.doc.getElementById('yt-sync-list-status').textContent);
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
});

test('slow and failed account refresh retain rows, scroll position and focus', async t => {
  const state = await setup(t);
  const row = state.doc.querySelector('.yt-pl-item');
  const list = state.doc.getElementById('yt-account-playlists');
  const button = row.querySelector('.yt-add-sync-btn');
  list.scrollTop = 88;
  button.focus();
  const pending = deferred();
  state.handlers.set('GET /api/v1/youtube/playlists', () => pending.promise);
  state.doc.getElementById('yt-refresh-account-btn').click();
  assert.equal(state.doc.querySelector('.yt-pl-item'), row);
  pending.reject(new Error('account offline'));
  await until(() => state.doc.getElementById('yt-account-status').textContent.includes('account offline'));
  assert.equal(state.doc.querySelector('.yt-pl-item'), row);
  assert.equal(list.scrollTop, 88);
  assert.equal(state.doc.activeElement, button);
});

test('account refresh updates titles in place without losing focus', async t => {
  const state = await setup(t);
  const row = state.doc.querySelector('.yt-pl-item');
  const button = row.querySelector('.yt-add-sync-btn');
  button.focus();
  state.playlists = [{...playlist(), title: 'Renamed playlist'}];
  state.doc.getElementById('yt-refresh-account-btn').click();
  await until(() => row.querySelector('.yt-pl-title').textContent === 'Renamed playlist');
  assert.equal(state.doc.querySelector('.yt-pl-item'), row);
  assert.equal(state.doc.activeElement, button);
  assert.equal(button.dataset.name, 'Renamed playlist');
});

test('stale sync read cannot undo a saved pause', async t => {
  const state = await setup(t);
  const card = state.doc.querySelector('.yt-sync-card');
  const toggle = card.querySelector('.yt-sync-toggle-btn');
  const stale = deferred();
  state.handlers.set('GET /api/v1/youtube/syncs', () => stale.promise);
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  toggle.click();
  await until(() => toggle.textContent === '再開');
  stale.resolve([sync()]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(toggle.dataset.enabled, 'false');
  assert.equal(toggle.textContent, '再開');
});

test('stale sync read cannot resurrect a deleted card or its sync badge', async t => {
  const state = await setup(t);
  const stale = deferred();
  state.handlers.set('GET /api/v1/youtube/syncs', () => stale.promise);
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  state.doc.querySelector('.yt-sync-delete-btn').click();
  await until(() => !state.doc.querySelector('.yt-sync-card'));
  stale.resolve([sync()]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.doc.querySelector('.yt-sync-card'), null);
  assert.equal(state.doc.querySelector('.yt-add-sync-btn').textContent, '+ 同期追加');
});

test('failed pause leaves the prior state and restores the button', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  const toggle = card.querySelector('.yt-sync-toggle-btn');
  state.handlers.set('PATCH /api/v1/youtube/syncs/1', () => new Response(JSON.stringify({detail: 'save failed'}), {status: 500}));
  toggle.click();
  await until(() => card.querySelector('.yt-sync-action-status').textContent.includes('save failed'));
  assert.equal(toggle.dataset.enabled, 'true');
  assert.equal(toggle.textContent, '一時停止');
  assert.equal(toggle.disabled, false);
  assert.equal(tracks.style.display, '');
});

test('failed addition keeps account rows and restores the original button label', async t => {
  const state = await setup(t);
  const row = state.doc.querySelector('.yt-pl-item');
  const button = row.querySelector('.yt-add-sync-btn');
  state.handlers.set('POST /api/v1/youtube/syncs', () => new Response(JSON.stringify({detail: 'duplicate format'}), {status: 409}));
  button.click();
  state.doc.querySelector('input[name="yt-sync-method"][value="api"]').checked = true;
  state.doc.getElementById('yt-sync-confirm-btn').click();
  await until(() => !button.disabled);
  assert.equal(button.textContent, '+ 別形式で同期');
  assert.equal(state.doc.querySelector('.yt-pl-item'), row);
  assert.match(state.doc.getElementById('yt-account-status').textContent, /duplicate format/);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), 1);
});

test('successful privacy switch updates the cached badge without refetching playlists', async t => {
  const state = await setup(t, {playlists: [{...playlist(), privacy_status: 'private'}]});
  const row = state.doc.querySelector('.yt-pl-item');
  const button = row.querySelector('.yt-add-sync-btn');
  button.click();
  state.doc.querySelector('input[name="yt-sync-method"][value="url-switch"]').checked = true;
  state.doc.getElementById('yt-sync-confirm-btn').click();
  await until(() => !button.disabled);
  assert.equal(button.dataset.privacy, 'unlisted');
  assert.match(row.querySelector('.yt-pl-meta-row').textContent, /限定公開/);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), 1);
});

test('two account refreshes cannot apply an older response last', async t => {
  const state = await setup(t);
  const older = deferred(), newer = deferred();
  let request = 0;
  state.handlers.set('GET /api/v1/youtube/playlists', () => (++request === 1 ? older.promise : newer.promise));
  state.doc.getElementById('yt-refresh-account-btn').click();
  state.doc.getElementById('yt-refresh-account-btn').click();
  newer.resolve([{...playlist(), title: 'Newer title'}]);
  await until(() => state.doc.querySelector('.yt-pl-title').textContent === 'Newer title');
  older.resolve([{...playlist(), title: 'Older title'}]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.doc.querySelector('.yt-pl-title').textContent, 'Newer title');
});

test('malformed offline payload does not clear cached account or sync lists', async t => {
  const state = await setup(t);
  const row = state.doc.querySelector('.yt-pl-item');
  const card = state.doc.querySelector('.yt-sync-card');
  state.handlers.set('GET /api/v1/youtube/playlists', () => ({}));
  state.handlers.set('GET /api/v1/youtube/syncs', () => ({}));
  state.doc.getElementById('yt-refresh-account-btn').click();
  state.doc.getElementById('yt-refresh-syncs-btn').click();
  await until(() => state.doc.getElementById('yt-account-status').classList.contains('error-msg') && state.doc.getElementById('yt-sync-list-status').classList.contains('error-msg'));
  assert.equal(state.doc.querySelector('.yt-pl-item'), row);
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
});

test('refresh binds each action only once', async t => {
  const state = await setup(t);
  for (let i = 0; i < 3; i++) {
    state.doc.getElementById('yt-refresh-syncs-btn').click();
    await until(() => !state.doc.getElementById('yt-sync-list').hasAttribute('aria-busy'));
  }
  state.doc.querySelector('.yt-sync-toggle-btn').click();
  await until(() => state.doc.querySelector('.yt-sync-toggle-btn').textContent === '再開');
  assert.equal(state.count('PATCH /api/v1/youtube/syncs/1'), 1);
});

test('URL-based addition keeps the existing sync and account cards visible', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  const account = state.doc.querySelector('.yt-pl-item');
  const pending = deferred();
  state.handlers.set('POST /api/v1/youtube/syncs', async () => {
    await pending.promise;
    const result = {...sync(2, 'PL2'), source_type: 'url'};
    state.syncs.push(result);
    return result;
  });
  state.doc.getElementById('yt-playlist-url-input').value = 'https://www.youtube.com/playlist?list=PL2';
  state.doc.getElementById('yt-add-url-btn').click();
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  pending.resolve();
  await until(() => state.doc.querySelectorAll('.yt-sync-card').length === 2 && !state.doc.getElementById('yt-add-url-btn').disabled);
  assert.equal(state.doc.querySelector('[data-sync-id="1"]'), card);
  assert.equal(card.querySelector('.yt-sync-tracks'), tracks);
  assert.equal(state.doc.querySelector('.yt-pl-item'), account);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), 1);
});

test('manual sync completion refresh keeps expanded tracks and disclosures', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  t.mock.timers.enable({apis: ['setTimeout']});
  const button = card.querySelector('.yt-sync-now-btn');
  button.click();
  await until(() => button.textContent === 'キュー登録済み');
  state.syncs = [{...sync(), downloaded_count: 2}];
  t.mock.timers.tick(3000);
  await until(() => card.querySelector('.yt-sync-progress').textContent.includes('2/2'));
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  assert.equal(card.querySelector('.yt-sync-tracks'), tracks);
  assert.equal(tracks.style.display, '');
  assert.equal(card.querySelector('.yt-sync-error-detail').style.display, '');
  assert.equal(state.count('GET /api/v1/youtube/playlists'), 1);
});

test('track refresh failure retains previously loaded rows and their error details', async t => {
  const state = await setup(t);
  const {card, tracks, track: row} = await expandDetails(state);
  const pending = deferred();
  state.handlers.set('GET /api/v1/youtube/syncs/1/tracks', () => pending.promise);
  card.querySelector('.yt-tracks-toggle').click();
  card.querySelector('.yt-tracks-toggle').click();
  assert.equal(tracks.querySelector('.yt-track-item'), row);
  pending.reject(new Error('tracks offline'));
  await until(() => tracks.querySelector('.yt-track-refresh-error'));
  assert.equal(tracks.querySelector('.yt-track-item'), row);
  assert.equal(row.querySelector('.yt-track-error-text').style.display, '');
});

test('an older track response cannot overwrite the latest expanded list', async t => {
  const state = await setup(t);
  const {card, tracks} = await expandDetails(state);
  const older = deferred(), newer = deferred();
  let request = 0;
  state.handlers.set('GET /api/v1/youtube/syncs/1/tracks', () => (++request === 1 ? older.promise : newer.promise));
  for (let i = 0; i < 2; i++) {
    card.querySelector('.yt-tracks-toggle').click();
    card.querySelector('.yt-tracks-toggle').click();
  }
  newer.resolve([{...track(), title: 'Newer song'}]);
  await until(() => tracks.textContent.includes('Newer song'));
  older.resolve([{...track(), title: 'Older song'}]);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(tracks.textContent, /Newer song/);
});

test('an in-flight account response cannot reverse a successful privacy change', async t => {
  const state = await setup(t, {playlists: [{...playlist(), privacy_status: 'private'}]});
  const pending = deferred();
  state.handlers.set('GET /api/v1/youtube/playlists', () => pending.promise);
  state.doc.getElementById('yt-refresh-account-btn').click();
  const button = state.doc.querySelector('.yt-add-sync-btn');
  button.click();
  state.doc.querySelector('input[name="yt-sync-method"][value="url-switch"]').checked = true;
  state.doc.getElementById('yt-sync-confirm-btn').click();
  await until(() => !button.disabled);
  pending.resolve([{...playlist(), privacy_status: 'private'}]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(button.dataset.privacy, 'unlisted');
  assert.equal(state.doc.getElementById('yt-account-playlists').hasAttribute('aria-busy'), false);
});

test('disconnect invalidates pending account reads and clears account-specific cache', async t => {
  const state = await setup(t);
  const pending = deferred();
  state.handlers.set('GET /api/v1/youtube/playlists', () => pending.promise);
  state.doc.getElementById('yt-refresh-account-btn').click();
  state.handlers.set('GET /api/v1/youtube/auth/status', () => ({authenticated: false}));
  state.doc.getElementById('yt-disconnect-btn').click();
  await until(() => state.doc.getElementById('yt-playlist-picker').style.display === 'none');
  pending.resolve([playlist()]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.doc.querySelector('.yt-pl-item'), null);
});

test('a pending settings save prevents a competing delete on the same card', async t => {
  const state = await setup(t);
  const card = state.doc.querySelector('.yt-sync-card');
  const pending = deferred();
  state.handlers.set('PATCH /api/v1/youtube/syncs/1', () => pending.promise);
  const toggle = card.querySelector('.yt-sync-toggle-btn');
  const remove = card.querySelector('.yt-sync-delete-btn');
  toggle.click();
  assert.equal(remove.disabled, true);
  remove.click();
  assert.equal(state.count('DELETE /api/v1/youtube/syncs/1?delete_files=true'), 0);
  pending.resolve({...sync(), enabled: false});
  await until(() => !toggle.disabled);
  assert.equal(remove.disabled, false);
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
});

test('settings save restores keyboard focus only if it was lost when disabling the button', async t => {
  const state = await setup(t);
  const toggle = state.doc.querySelector('.yt-sync-toggle-btn');
  const pending = deferred();
  state.handlers.set('PATCH /api/v1/youtube/syncs/1', () => pending.promise);
  toggle.focus();
  toggle.click();
  // Simulate browsers moving focus to the document when disabling a button.
  state.doc.body.tabIndex = -1;
  state.doc.body.focus();
  assert.equal(state.doc.activeElement, state.doc.body);
  pending.resolve({...sync(), enabled: false});
  await until(() => !toggle.disabled);
  assert.equal(state.doc.activeElement, toggle);
});

test('settings save does not steal focus if the user moves to another control', async t => {
  const state = await setup(t);
  const toggle = state.doc.querySelector('.yt-sync-toggle-btn');
  const pending = deferred();
  state.handlers.set('PATCH /api/v1/youtube/syncs/1', () => pending.promise);
  toggle.focus();
  toggle.click();
  const other = state.doc.querySelector('.yt-add-sync-btn');
  other.focus();
  pending.resolve({...sync(), enabled: false});
  await until(() => !toggle.disabled);
  assert.equal(state.doc.activeElement, other);
});

test('OAuth check reports refresh refusal without rebuilding playlist or track views', async t => {
  const state = await setup(t);
  const card = state.doc.querySelector('.yt-sync-card');
  const account = state.doc.querySelector('.yt-pl-item');
  const button = state.doc.querySelector('#yt-auth-check-btn');
  const pending = deferred();
  state.handlers.set('POST /api/v1/youtube/auth/check', () => pending.promise);
  button.click();
  assert.equal(button.disabled, true);
  pending.resolve({authenticated:true, refresh_token_set:true, refresh_status:'reauth_required', refresh_error:'invalid_grant'});
  await until(() => !button.disabled);
  assert.match(state.doc.querySelector('#yt-auth-badge').textContent, /再認証/);
  assert.match(state.doc.querySelector('#yt-oauth-status').textContent, /不明/);
  assert.equal(state.doc.querySelector('.yt-sync-card'), card);
  assert.equal(state.doc.querySelector('.yt-pl-item'), account);
  assert.equal(state.count('GET /api/v1/youtube/playlists'), 1);
});

test('OAuth check network failure restores the check button', async t => {
  const state = await setup(t);
  state.handlers.set('POST /api/v1/youtube/auth/check', () => {throw new Error('offline');});
  const button = state.doc.querySelector('#yt-auth-check-btn');
  button.click();
  await until(() => !button.disabled);
  assert.match(state.doc.querySelector('#yt-oauth-status').textContent, /確認に失敗/);
});
