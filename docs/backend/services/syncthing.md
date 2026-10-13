# Syncthing サービス

`backend/app/services/syncthing_service.py` — Syncthing の REST API を使って同期状態を取得します。

## コンテナ再作成と接続復旧

`docker-compose.yml` では `/var/syncthing` を `./syncthing-state/` に永続化し、既存の設定・鍵の
`./syncthing-config/` と曲の `./downloads/` のマウントも維持します。これにより、既存のデバイスIDとペアリングを保ったまま、
`/var/syncthing/Sync` などの共有領域とフォルダマーカーも保持できます。
旧構成から移す際は、旧コンテナの共有フォルダを削除前にコピーする必要があります。手順はREADMEのSyncthing連携を参照してください。

Syncthing REST APIはDocker名・プライベートIP向けの通信を環境のHTTPプロキシへ転送しません。
外部のカスタムURLではプロキシ設定を維持します。読み取りは通信エラーまたは502/503/504で1回だけ再試行し、
403などの認証エラーと再スキャンPOSTは再試行しません。保存済みAPIキーを使う接続テストも、画面で入力したURLへ接続します。

## 同期状態の判定

システム状態、フォルダ設定、デバイス接続状態を取得し、フォルダごとのローカル状態と共有先デバイスの進捗を確認します。
`/rest/db/completion` には必ず `folder` と `device` を指定します。未指定の応答は全体の同期完了を示しません。
フォルダのパス・マーカー欠落、取り込みエラー、切断、リモートインデックスの未取得、削除待ちも判定します。

| `state` | 意味 |
|---|---|
| `synced` | 対象の共有先が接続中で、ローカルと共有先に未完了項目や障害がない |
| `syncing` | データ・項目・削除が未完了、またはスキャン・同期を実行中 |
| `disconnected` | 共有先の一部または全部が未接続 |
| `error` | フォルダパス欠落などの同期障害 |
| `unknown` | 進捗・接続状態を確認できない、またはリモート状態が未取得 |
| `paused` | 全フォルダが一時停止中 |
| `unshared` | フォルダや共有先が未設定 |
| `unavailable` | システムAPIへ接続できない、認証失敗、または不正な応答 |

`available` はシステムAPIへの接続可否であり、同期先への接続成功とは別です。
進捗が未取得なら `completion_pct` は `null` とし、100%で補完しません。
`need_bytes` と `need_items` はローカルと共有先それぞれの未完了分の合計、`global_bytes` はフォルダ単位の全体サイズの合計です。
複数デバイスに同じファイルを送る場合、必要転送量はファイルサイズの合計より大きくなります。
デバイス一覧から自分自身を除外し、最終接続日時は `/rest/stats/device` を使います。
画面は切断・障害・取得失敗を「同期完了」と表示せず、設定パネルを開いている間は5秒ごとに再取得します。

## 検証

通常の回帰テストは `backend` で `python -m pytest tests/ -q`、表示ロジックはリポジトリ直下で
`node --test tests/frontend/*.test.mjs` を実行します。

実コンテナでの検証はDockerが使える環境で次を実行します。

```bash
docker pull syncthing/syncthing:2.1.6
docker build -t local-music-player:syncthing-recovery-test .
cd backend
SYNCTHING_DOCKER_TESTS=1 SYNCTHING_APP_TEST_IMAGE=local-music-player:syncthing-recovery-test \
  python -m pytest tests/integration/test_syncthing_recreate.py -v
```

一時ディレクトリと専用ネットワークの2台だけを使い、既存のコンテナや設定には触れません。
旧構成のフォルダ欠落を再現するテスト、修正構成でIPアドレスを変えて再作成し、デバイスID・ペアリング・既存ファイル・フォルダマーカー・双方向の同期・削除の同期を確認するテスト、実アプリのコンテナが接続設定を変えずにサービスDNS経由で復旧するテストがあります。
グローバル探索とリレーは検証用ネットワークでは無効にします。スマホのバックグラウンド制限や、利用者のルーター・ファイアウォール・外部リレーを通る通信まではこのテストでは検証しません。

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
| `completion_pct` | number / null | 全フォルダのサイズで重み付けした進捗。未取得ならnull |
| `syncing` | boolean | `state` が `syncing` かどうか |
| `state` | string | 同期・切断・障害・未取得などの状態 |
| `errors` | string[] | フォルダ障害や取得失敗の詳細 |

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
| `GET {SYNCTHING_URL}/rest/config/folders` | 共有フォルダと共有先 |
| `GET {SYNCTHING_URL}/rest/system/connections` | デバイスの接続状態 |
| `GET {SYNCTHING_URL}/rest/db/status?folder=...` | ローカルの同期状態とフォルダ障害 |
| `GET {SYNCTHING_URL}/rest/db/completion?folder=...&device=...` | フォルダ・共有先ごとの進捗 |
| `GET {SYNCTHING_URL}/rest/stats/device` | デバイスの最終接続日時 |

**リクエストヘッダー**

```
X-API-Key: {SYNCTHING_API_KEY}
```

**タイムアウト**: 5 秒（`httpx.AsyncClient(timeout=5.0)`）
