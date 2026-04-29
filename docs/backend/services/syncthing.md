# Syncthing サービス

`backend/app/services/syncthing_service.py` — Syncthing の REST API を使って同期状態を取得します。

## 関数

### `get_syncthing_status() -> dict`

Syncthing デーモンのシステム状態と同期完了率を返します。

**動作条件**

`SYNCTHING_API_KEY` が設定されていない場合は即座に以下を返します:

```json
{
  "available": false,
  "reason": "SYNCTHING_API_KEY not configured"
}
```

**正常時のレスポンス**

```json
{
  "available": true,
  "my_id": "XXXX-YYYY-ZZZZ-...",
  "completion_pct": 100.0,
  "syncing": false
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `available` | boolean | Syncthing が応答しているか |
| `my_id` | string | デバイス ID |
| `completion_pct` | number | 同期完了率（0〜100） |
| `syncing` | boolean | 現在同期中かどうか（`globalBytes != localBytes`） |

**エラー時のレスポンス**

```json
{
  "available": false,
  "reason": "Syncthing not reachable"
}
```

| エラー | reason |
|--------|--------|
| 接続できない / タイムアウト | `"Syncthing not reachable"` |
| HTTP エラー | `"HTTP {status_code}"` |

## API 呼び出し

| エンドポイント | 説明 |
|------------|------|
| `GET {SYNCTHING_URL}/rest/system/status` | デバイス ID などのシステム情報 |
| `GET {SYNCTHING_URL}/rest/db/completion` | フォルダ同期完了率 |

**リクエストヘッダー**

```
X-API-Key: {SYNCTHING_API_KEY}
```

**タイムアウト**: 5 秒（`httpx.AsyncClient(timeout=5.0)`）
