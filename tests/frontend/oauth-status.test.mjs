import test from 'node:test';
import assert from 'node:assert/strict';
import {oauthStatusLines} from '../../frontend/js/oauth-status.js';

test('unknown refresh lifetime is explicit and never presented as unlimited', () => {
  const text = oauthStatusLines({refresh_status:'available', refresh_token_set:true}).join('\n');
  assert.match(text, /不明/);
  assert.match(text, /失効する場合/);
  assert.match(text, /自動更新可能/);
  assert.match(text, /最終更新成功：未確認/);
});
test('testing lifetime is clearly labelled as an estimate', () => {
  const text = oauthStatusLines({refresh_token_set:true, refresh_token_expiry:'2026-10-20T12:00:00Z', refresh_expiry_estimated:true}).join('\n');
  assert.match(text, /7日制限による目安/);
});
test('refresh refusal, configuration failure and temporary outage have distinct remedies', () => {
  assert.match(oauthStatusLines({refresh_status:'reauth_required'})[0], /再認証/);
  assert.match(oauthStatusLines({refresh_status:'configuration_error'})[0], /設定/);
  assert.match(oauthStatusLines({refresh_status:'temporary_error'})[0], /再試行/);
});

test('connection guidance distinguishes valid stored auth, disconnection, reauth and transient failure',async()=>{
  const {connectionGuide}=await import('../../frontend/js/oauth-status.js');
  assert.match(connectionGuide({authenticated:false}).message,/共有URL.*接続なし/);
  assert.equal(connectionGuide({authenticated:false}).action,'設定でYouTubeに接続');
  const connected=connectionGuide({authenticated:true,refresh_status:'available'});
  assert.match(connected.message,/追加できます/);
  assert.doesNotMatch(connected.message,/接続してください|再認証/);
  assert.equal(connectionGuide({authenticated:true,refresh_status:'reauth_required'}).action,'設定で再認証');
  assert.match(connectionGuide({authenticated:true,refresh_status:'configuration_error'}).message,/OAuthクライアント/);
  assert.match(connectionGuide({authenticated:true,refresh_status:'temporary_error'}).message,/通信回復後/);
  assert.doesNotMatch(connectionGuide(null).message,/再認証/);
});
