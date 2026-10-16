const date = value => value ? new Date(value).toLocaleString('ja-JP') : '未確認';
export function oauthStatusLines(status) {
  const labels = {
    check_required: '更新トークンの期限目安を過ぎました。接続を確認してください',
    available: '自動更新可能（API利用時に更新）',
    unavailable: '自動更新不可：更新トークンなし',
    reauth_required: '再認証が必要です',
    configuration_error: '自動更新の設定を確認してください（OAuthクライアント）',
    temporary_error: '更新確認に失敗しました。通信回復後に再試行できます',
  };
  return [
    labels[status.refresh_status] || '更新状態は未確認です',
    `アクセストークン期限：${date(status.access_token_expiry)}${status.access_token_expired ? '（期限切れ）' : ''}`,
    status.refresh_token_set
      ? `更新トークン期限：${status.refresh_token_expiry ? date(status.refresh_token_expiry) + (status.refresh_expiry_estimated ? '（テストモードの7日制限による目安）' : '') : '不明（Googleから期限情報なし。失効する場合があります）'}`
      : '更新トークン：なし',
    `最終更新成功：${date(status.last_refresh_at)}`,
  ];
}


export function connectionGuide(status) {
  if (!status) return {message:'YouTubeの接続状態を取得できません。設定から確認してください。', action:'接続状態を確認'};
  if (!status.authenticated) return {message:'アカウントから追加するにはYouTubeへの接続が必要です。共有URLからの同期は接続なしで追加できます。', action:'設定でYouTubeに接続'};
  const guides = {
    reauth_required: {message:'アカウントから追加するには、設定でYouTubeを再認証してください。共有URLからの同期は引き続き利用できます。', action:'設定で再認証'},
    configuration_error: {message:'YouTubeの自動更新設定に問題があります。設定でOAuthクライアントを確認してください。', action:'接続設定を確認'},
    temporary_error: {message:'YouTubeの更新確認に失敗しました。通信回復後に接続を確認してください。', action:'接続を確認'},
    check_required: {message:'更新トークンの期限の目安を過ぎています。設定から接続を確認してください。', action:'接続を確認'},
    unavailable: {message:'YouTubeの認証情報がありますが、自動更新には更新トークンが必要です。', action:'接続設定を確認'},
    available: {message:'YouTubeの認証情報があります。アカウントのプレイリストから同期を追加できます。', action:'接続設定を開く'},
  };
  return guides[status.refresh_status] || {message:'YouTubeの認証情報があります。接続状態は設定で確認できます。', action:'接続状態を確認'};
}
