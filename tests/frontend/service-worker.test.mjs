import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../../frontend/sw.js', import.meta.url), 'utf8');
function worker(fetch) {
  const handlers = new Map();
  const deleted = [];
  const context = {
    self: {addEventListener: (name, handler) => handlers.set(name, handler), skipWaiting() {}, clients: {claim() {}}},
    URL, Response, JSON, fetch,
    caches: {
      open: async () => ({addAll: async () => {}, put: async () => {}}),
      keys: async () => ['lmp-v2', 'lmp-v3'],
      delete: async key => deleted.push(key), match: async () => undefined,
    },
  };
  runInNewContext(source, context);
  return {handlers, deleted};
}

test('offline API returns a failure status, never an empty successful payload', async () => {
  const {handlers} = worker(async () => {throw new Error('offline');});
  let response;
  handlers.get('fetch')({request: new Request('http://localhost/api/v1/youtube/syncs'), respondWith: promise => response = promise});
  const result = await response;
  assert.equal(result.status, 503);
  assert.ok((await result.json()).detail);
});

test('API response and upstream failure statuses are preserved', async () => {
  const {handlers} = worker(async () => new Response(JSON.stringify({detail: 'upstream unavailable'}), {status: 502}));
  let response;
  handlers.get('fetch')({request: new Request('http://localhost/api/v1/youtube/playlists'), respondWith: promise => response = promise});
  assert.equal((await response).status, 502);
});

test('activation removes the previous shell cache so UI fixes can be loaded', async () => {
  const {handlers, deleted} = worker();
  let activation;
  handlers.get('activate')({waitUntil: promise => activation = promise});
  await activation;
  assert.deepEqual(deleted, ['lmp-v2']);
});
