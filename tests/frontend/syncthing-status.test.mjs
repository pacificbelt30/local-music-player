import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../../frontend/js/syncthing-status.js', import.meta.url), 'utf8');
const {badgePresentation, folderPresentation} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

for (const state of ['error', 'disconnected', 'unknown', 'unshared', 'paused']) {
  test(`${state} never displays Synced even with cached 100%`, () => {
    const view = badgePresentation({available: true, state, completion_pct: 100, syncing: false, errors: ['folder path missing']});
    assert.notEqual(view.text, 'Synced');
    assert.ok(!view.className.endsWith(' ok'));
    assert.match(view.title, /folder path missing/);
    assert.notEqual(folderPresentation({state, completion_pct: 100}).color, 'success');
  });
}

test('confirmed completion is displayed as Synced', () => {
  assert.equal(badgePresentation({available: true, state: 'synced', connected_devices: 1, total_devices: 1}).text, 'Synced');
});
test('pending deletions with zero needed bytes still display synchronization', () => {
  assert.match(badgePresentation({available: true, state: 'syncing', completion_pct: 100, need_bytes: 0, need_items: 2}).text, /同期中/);
});
test('unknown percentage is not shown as 100%', () => {
  assert.ok(!folderPresentation({state: 'unknown', completion_pct: null}).label.includes('100'));
});
test('unreachable service is not shown as completed', () => {
  assert.equal(badgePresentation({available: false, state: 'unavailable'}).text, 'Syncthing: off');
});
