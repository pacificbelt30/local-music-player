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
