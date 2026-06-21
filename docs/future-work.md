# 今後の課題・未実装箇所

現在の実装で機能しているが不完全・制限がある箇所、および未実装の機能をまとめます。

## 優先度まとめ

| 課題 | カテゴリ | 影響 | 難度 |
|------|---------|------|------|
| CORS オリジン制限（本番設定） | セキュリティ | 高 | 低 |
| OAuth トークン暗号化 | セキュリティ | 高 | 中 |
| URL バリデーション拡張（YouTube 以外）※詳細は「ダウンローダー機能強化」参照 | API | 中 | 低 |
| `admin/rescan` の双方向対応 | API | 中 | 中 |
| DB バックアップ機能 | 運用 | 中 | 低 |
| ダウンロード完了通知 | UX | 低 | 中 |
| フロントエンドテスト | 品質 | 低 | 高 |
| ダウンロード重複検出の強化（archive方式） | ダウンローダー | 中 | 低 |
| 失敗理由別のリトライ制御 | ダウンローダー | 中 | 低 |
| バッチURL一括登録 | ダウンローダー | 低 | 低 |
| フォーマット選択肢の拡張 | ダウンローダー | 低 | 低 |
| 字幕・歌詞の自動抽出 | ダウンローダー | 低 | 低 |

---

## バックエンド API

### URL バリデーションが YouTube のみ

**場所**: `backend/app/schemas.py:17-19`

```python
if "youtube.com" not in v and "youtu.be" not in v:
    raise ValueError("URL must be a YouTube URL")
```

yt-dlp 自体は SoundCloud・Vimeo・ニコニコ動画等に対応していますが、バリデーションを緩和する変更が必要です。

### `/api/v1/urls` にページネーション・検索がない

**場所**: `backend/app/api/urls.py:33-35`

登録 URL の一覧 API は全件返すのみです。検索・ソート・ページネーションに未対応です。

### トラックの編集可能フィールドが限定的

**場所**: `backend/app/schemas.py:73-77`

`TrackUpdate` で更新できるのは `title`・`artist`・`album` の 3 フィールドのみです。

### ダウンロード済みトラックの重複管理

`url_sources` 経由でダウンロードした `tracks` と、YouTube 同期の `playlist_sync_tracks` は別テーブルで管理されており、同じ動画が両方に存在しうる状態です。統合・deduplication の仕組みがありません。

---

## データベース・ストレージ

### DB バックアップ機能がない

SQLite ファイルのバックアップ・エクスポートを行う API やスクリプトが存在しません。

### `admin/rescan` が一方向のみ

**場所**: `backend/app/main.py:82-98`

`POST /api/v1/admin/rescan` はファイルが存在しないトラックを DB から削除しますが、DB に存在しないが `downloads/` に存在するファイルを取り込む機能はありません。

---

## タスク・ワーカー

### リトライ回数が UI から見えない

`DownloadJob` テーブルにリトライ回数フィールドがなく、何回目のリトライかを UI で確認できません。

### 永続的な失敗の扱いが未定義

最大リトライ（`resolve_url`: 2 回、`download_track`: 3 回）を超えた場合、ジョブは `failed` のままです。デッドレターキューへの移動・アラート通知はありません。

### ダウンロード完了通知がない

~~ダウンロード完了時に Web Notifications API や Webhook 等の通知機能がありません。SSE のキューイベントで確認する必要があります。~~

**実装済み**: Discord Webhook 通知を実装しました。設定画面から Webhook URL と通知イベントを選択できます。

対応イベント:
- ダウンロード完了 (`notify_on_download_complete`、デフォルト: 無効)
- ダウンロード失敗 (`notify_on_download_failed`、デフォルト: 有効)
- DB障害 (`notify_on_db_error`、デフォルト: 有効) — DB 不通時は `DISCORD_WEBHOOK_URL` 環境変数にフォールバック
- YouTube OAuth 認証切れ (`notify_on_youtube_auth_expired`、デフォルト: 有効)
- YouTube OAuth トークン期限切れ間近 (`notify_on_oauth_expiry_warning`、デフォルト: 有効) — 期限の何分前に通知するかを `oauth_expiry_warning_minutes`（デフォルト: 60分）で設定可能。同一トークンへの重複通知はスキップ。

---

## セキュリティ

### CORS がデフォルトで全許可

**場所**: `backend/app/config.py:19`

```python
allowed_origins: list[str] = ["*"]
```

本番環境では `ALLOWED_ORIGINS` 環境変数で適切なオリジンに制限してください。

### YouTube OAuth トークンが暗号化されていない

`YouTubeOAuthToken` テーブルのアクセストークン・リフレッシュトークンはプレーンテキストで SQLite に保存されています。DB ファイルへのアクセスがあれば直接読み取れます。

---

## Syncthing

### Syncthing フォルダの設定が手動

Syncthing でフォルダを共有するには Syncthing Web GUI を別途操作する必要があります。アプリから Syncthing フォルダを設定・管理する機能はありません。

---

## テスト

### フロントエンドのテストがない

`frontend/` 以下に JavaScript のユニットテスト・E2E テストが存在しません。

### Celery タスクの結合テストがない

`backend/tests/` のタスクテストはすべてモックベースです。実際の Redis やファイルシステムを使った結合テストはありません。

### CI で yt-dlp のネットワークテストがない

`.github/workflows/test.yml` のテストは実際の YouTube へのネットワークアクセスを行わず、yt-dlp の動作はモックで代替されています。

---

## ダウンローダー機能強化（類似サービス調査、2026-06-16）

SyncTuneHub の中核価値は「YouTube からのコンテンツ取り込み・自動同期エンジン」であり、
プレイヤー UX よりもこの取り込みパイプラインを強化する方が製品の本質に合う。
類似のダウンローダー系 OSS（TubeArchivist・ytdl-sub・MeTube）と yt-dlp 本体の機能を調査し、
現状の弱点と追加候補を整理する。

### 調査した類似サービス

- **TubeArchivist**: チャンネル/プレイリストの定期自動スキャン、Apprise 経由の多チャネル通知、
  cron ライクな詳細スケジューリング、メタデータ自動バックアップ。
- **ytdl-sub**: `--download-archive` によるダウンロード済み判定での重複防止、
  YAML プリセットでの再利用可能な取り込み設定、命名規則・アートワーク自動生成。
- **MeTube**: チャンネル/プレイリストの新着自動検知、同時ダウンロード数の UI 制御。
- **yt-dlp 本体**: `--download-archive`（重複防止）、`--cookies`（認証必須コンテンツ）、
  `--write-subs`/`--write-auto-subs`（字幕・歌詞抽出）、`--sponsorblock-remove`/`--sponsorblock-mark`
  （スポンサー区間除去）、`-f`（詳細フォーマット選択）、`--limit-rate`/`--concurrent-fragments`（帯域制御）。

### 現状の弱点（コード根拠）

- **URL 検証が YouTube のみ**（`backend/app/schemas.py:21-24`）。
  さらに、ダウンロード実行時は `backend/app/services/ytdlp_service.py:158` で
  `https://www.youtube.com/watch?v={youtube_id}` を組み立て直しているため、
  バリデーションを緩めるだけでは他サイト対応にならない。元 URL を保持して
  ダウンロード時に使う構造に変更する必要がある。
- **重複検出が部分的**。`DownloadJob` は `youtube_id` 単位で重複登録を防いでいる
  （`backend/app/tasks/download.py:56-58`）。`UrlSource` 登録はクエリパラメータ違いや
  `youtu.be` / `youtube.com` 表記違い・トラッキングパラメータ付きの URL でも同一動画として
  検出できるよう、`normalize_youtube_url()`（`backend/app/schemas.py`）で正規化したキーを
  `canonical_url` カラム（一意制約）に保持して比較する方式に変更済み
  （`backend/app/api/urls.py`）。**未解決**: `UrlSource` 経由の `Track` と
  YouTube プレイリスト同期の `PlaylistSyncTrack` は別テーブル管理で、テーブル間の重複は検出されない
  （既存課題、上記「ダウンロード済みトラックの重複管理」参照）。
- **フォーマット選択肢がプリセットのみ**（`backend/app/services/ytdlp_service.py:11-12` の
  `AUDIO_FORMATS`/`VIDEO_FORMATS` 固定リスト）。yt-dlp が動画ごとに持つ詳細なフォーマット一覧
  （`-F` 相当）を活用していない。
- **失敗理由を区別しないリトライ**（`backend/app/tasks/download.py:172-188`）。
  ネットワークエラーも、認証必須エラーも、動画削除済みエラーも同じ
  `self.retry(... countdown=30 * (2 ** retries))` で処理され、最終的に `failed` のまま放置される。
- **Cookie/ログイン認証に未対応**。`ytdlp_service.py` の `ydl_opts` に `cookiefile` 相当の指定がなく、
  年齢制限・メンバー限定動画はダウンロードできない。
- **字幕・スポンサー区間処理が未実装**。`writeinfojson`/`writethumbnail` は明示的に `False`
  （`ytdlp_service.py:132-133`）で、字幕抽出やSponsorBlock関連のオプションは存在しない。
- **チャンネル/プレイリストの「新着監視」のみで、キーワード検索ベースの監視がない**。
  現状はすでに登録した URL の再解決（`resolve_url` タスク）のみ。

### 提案する機能一覧（優先度別）

**A. クイックウィン（低コスト・高効果）**

1. 対応サイトの拡張 — URL 検証を yt-dlp 対応の主要サイト（SoundCloud, Vimeo, Bandcamp,
   ニコニコ動画等）にも広げる。`UrlSource` に元 URL を保持し、`download_track` で
   YouTube watch URL の再構築ではなく元 URL を使うように変更する。
2. バッチ URL 一括登録 — 複数行の URL をまとめて貼り付けて登録できる UI/API。
3. 重複検出の強化 — `UrlSource` 登録時の URL 正規化比較は実装済み（`normalize_youtube_url()`）。
   残るは yt-dlp の `--download-archive` 方式の採用等による `UrlSource`/`PlaylistSyncTrack` 間の
   テーブル間重複の解消。
4. 詳細フォーマット選択 UI — 動画ごとに利用可能なフォーマット一覧を API で返し、
   プリセット以外も選べるようにする。
5. 失敗理由別のリトライ制御 — エラーメッセージを分類（ネットワーク/認証/動画削除済み等）し、
   認証エラーは即時にユーザー通知してリトライしない。
6. 字幕・歌詞の自動抽出 — `--write-subs`/`--write-auto-subs` でダウンロード時に字幕を取得し歌詞として保存。

**B. 中期的な機能**

7. 検索クエリ/キーワード監視によるサブスクリプション — 「このキーワードの新着動画を自動ダウンロード」
   を TubeArchivist 方式で実現。
8. Cookie/ログイン認証対応 — ブラウザからエクスポートした Cookie をアップロードし、
   年齢制限・メンバー限定動画にも対応。
9. SponsorBlock 連携 — スポンサー区間・宣伝部分を自動スキップ/カット。
10. 優先度付きダウンロードキュー — ジョブの手動並び替え、一時停止/再開、割り込み実行。
11. 帯域・時間帯スケジューリングの強化（既存の P2 項目「帯域・時間帯制御」と統合）。
12. 通知の多チャネル化 — Discord に加え Apprise 的な統合で Slack/メール/Pushover 等にも対応。

**C. 長期的な機能**

13. 孤立ファイルの逆引き取り込み — `admin/rescan` の双方向化（既存課題と統合）。
14. 取り込み設定のプリセット化（YAML/JSON） — フォーマット・音質・保存先・命名規則を再利用可能に。
15. ダウンロードジョブ履行ログのバックアップ・エクスポート。
16. マルチユーザー対応のダウンロードキュー分離。

### おすすめの次の一歩

投資対効果が高いのは A グループの中でも **「対応サイト拡張」「重複検出の強化」「失敗理由別リトライ」** の3つ。
いずれも既存の `backend/app/tasks/download.py` と `backend/app/api/urls.py` への変更で実現でき、
新規の外部依存も不要。着手対象を1つ選んだ上で、対象ファイル・DB スキーマ変更・テスト方針を含む
具体的な実装計画を別途作成する。
