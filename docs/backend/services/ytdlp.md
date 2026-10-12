# yt-dlp サービス

## 稼働中の自動更新

設定画面の「yt-dlp 自動更新」で、確認間隔、60秒以内の公開動画、少数の動画を含む公開プレイリストを保存します。チャンネル解析も使う場合は、検証用チャンネルを指定します。初期値は24時間ごとの確認です。検証用動画・プレイリストが未設定の場合は、新版が見つかっても採用しません。「今すぐ確認」は保存済みの設定を使います。

Celery Beatが5分ごとに `app.tasks.ytdlp_update.check` を `updates` キューへ送り、専用ワーカーが設定した間隔を判定します。PyPIのstable版を確認し、新しい版とその依存パッケージを `DATA_PATH/ytdlp-runtime/installations/` の専用ディレクトリへ導入します。アプリのPython環境を上書きしません。

候補版を採用する前に、現行版と候補版でそれぞれ以下を実行します。

- ローカルで生成した短い素材を使い、本物のyt-dlpとFFmpegで全7形式のAPI・後処理・出力名・進捗を確認。
- 本番と同じ `resolve_url()`、`get_playlist_info()` により、動画・プレイリストと任意のチャンネルの戻り値を確認。
- 指定動画を音声5形式（mp3/flac/aac/ogg/m4a）と動画2形式（mp4/webm）で取得。保存済みの音量・無音処理・FFmpegリソース設定を使い、メタデータ、実ファイル、音声・映像ストリーム、音声コーデック、再生時間、進捗イベントを確認。

検証は一時ディレクトリで行い、DB登録・Syncthing同期・Discord通知は発生させません。各版の検証は15分、候補版のインストールは5分でタイムアウトします。タイムアウトした検証プロセスはFFmpegを含めて終了させます。ネットワークとCPUを使うため、検証用には低解像度の短い動画と小さなプレイリストを使ってください。

| 現行版 | 候補版 | 結果 |
|---|---|---|
| 成功 | 成功 | 候補版を採用 |
| 失敗 | 成功 | 候補版を採用（現行版の不具合を修復できる可能性） |
| 成功 | 失敗 | 候補版を拒否、現行版を維持 |
| 失敗 | 失敗 | 判定保留、現行版を維持 |

採用版は `state.json` の原子的な置換で切り替えます。各処理は開始時に版を選択して専用子プロセスで実行するため、稼働中のダウンロードは選択済みの旧版で完了し、次の処理から新版を使います。ファイルロックで更新・設定変更・切り戻しの競合を防ぎます。更新履歴のディレクトリは稼働中の処理を保護するため自動削除しません。失敗した候補版は削除します。ワーカーが異常終了した場合は、設定画面で中断として表示し、次の更新確認で再試行できます。

「前の版に戻す」は採用版と直前の版を交換し、自動更新を停止します。再開する場合は設定画面で有効にしてください。API・ダウンロードワーカー・更新ワーカーでは、同じPythonバージョン、アプリイメージ、絶対パスの `DATA_PATH` を使い、そのディレクトリを共有する必要があります。再ビルドによりアプリ同梱版が変わった場合、切り戻し先の「同梱版」は新しいイメージの同梱版になります。

Docker Composeには `updater` サービスを追加しています。DockerイメージにはYouTubeの署名処理に使うDenoと `yt-dlp[default]` の依存パッケージを含めています。Dockerを使わない場合はFFmpeg/ffprobeとDenoをPATHに用意し、`start.sh` で更新ワーカーを起動します。ネットワーク制限がある場合、PyPI・Pythonパッケージ配布先・YouTubeと動画配信先への通信が必要です。

| API | 用途 |
|---|---|
| `GET /api/v1/ytdlp` | 採用版・設定・状態・現行版と候補版のテスト結果 |
| `PATCH /api/v1/ytdlp/config` | 自動更新・間隔・検証用URLの保存（設定全体を送信） |
| `POST /api/v1/ytdlp/check` | 非同期の手動確認（202、タスクIDを返す） |
| `POST /api/v1/ytdlp/rollback` | 直前の版へ切り戻し、自動更新を停止 |

これらのAPIにも既存の `SECRET_TOKEN` 認証が適用されます。更新中の設定変更・切り戻し・手動確認は409を返します。

開発用テストは `backend` で `python -m pytest tests/ -q` を実行します。テストではインメモリのCeleryブローカーと結果バックエンドを使い、更新の成否、重複実行、切り戻し、実プロセスでの版固定、タイムアウト、ローカル素材の全7形式を確認します。CIではFFmpegのインストールが必要です。YouTubeとの接続確認は稼働時の検証用URLを使うため、通常のpytestには含めません。

`backend/app/services/ytdlp_service.py` — yt-dlp を使った URL 解決と音声ダウンロードを提供します。

## 関数

### `resolve_url(url: str) -> list[dict]`

YouTube URL をダウンロードせずに解析し、動画 ID のリストを返します。

**引数**

| 引数 | 型 | 説明 |
|------|-----|------|
| `url` | str | YouTube URL（動画・プレイリスト・チャンネル） |

**返り値**

各要素は以下の構造の辞書のリスト:

```python
{
    "id": "dQw4w9WgXcQ",       # YouTube 動画 ID
    "title": "Never Gonna...", # 動画タイトル
    "url_type": "video",       # "video" | "playlist" | "channel"
    "playlist_title": None,    # プレイリスト名（単体動画は None）
}
```

**yt-dlp オプション**

```python
{
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,   # メタデータのみ取得（ダウンロードしない）
    "dump_single_json": True,
}
```

**動作**

- `_type` が `playlist` または `channel` の場合: `entries` を展開して複数エントリを返す
- それ以外（単体動画）: 1 エントリのリストを返す

---

### `download_track(youtube_id, audio_format, audio_quality, progress_hook, base_path) -> dict`

YouTube 動画 ID を指定して音声をダウンロードし、メタデータを返します。

**引数**

| 引数 | 型 | 説明 |
|------|-----|------|
| `youtube_id` | str | YouTube 動画 ID |
| `audio_format` | str | `mp3` / `flac` / `aac` / `ogg` |
| `audio_quality` | str | `192` / `320` / `best` |
| `progress_hook` | callable \| None | ダウンロード進捗コールバック |
| `base_path` | Path \| None | 保存先ディレクトリ（デフォルト: `settings.downloads_path`） |

**返り値**

```python
{
    "youtube_id": "dQw4w9WgXcQ",
    "title": "Never Gonna Give You Up",
    "artist": "Rick Astley",                    # uploader / channel
    "album": None,                              # playlist_title
    "duration_secs": 213,
    "file_path": "/downloads/Rick Astley/Never Gonna Give You Up.mp3",
    "file_format": "mp3",
    "file_size_bytes": 5120000,
    "thumbnail_path": "/downloads/Rick Astley/Never Gonna Give You Up.jpg",
}
```

**yt-dlp オプション**

```python
{
    "format": "bestaudio/best",
    "outtmpl": "{base_path}/%(uploader)s/%(title)s.%(ext)s",
    "postprocessors": [...],    # フォーマット変換
    "writeinfojson": True,      # .info.json を保存
    "writethumbnail": True,     # サムネイルを保存
    "noplaylist": True,         # プレイリストは処理しない
}
```

**フォーマット変換 (postprocessors)**

| フォーマット | postprocessor |
|------------|--------------|
| `mp3` | `FFmpegExtractAudio` codec=mp3 quality={192\|320\|0} |
| `flac` | `FFmpegExtractAudio` codec=flac |
| `aac` | `FFmpegExtractAudio` codec=aac |
| `ogg` | `FFmpegExtractAudio` codec=vorbis |

MP3 の quality: `192`→`192`、`320`→`320`、`best`→`0`（最高品質）

**ファイル保存先**

```
{base_path}/{safe_uploader}/{safe_title}.{ext}
```

`yt_dlp.utils.sanitize_filename()` でファイル名を安全化します。

**サムネイル検索**

ダウンロード後、`.jpg` → `.png` → `.webp` の順にサムネイルファイルを探します。

**progress_hook**

ダウンロード中に yt-dlp から呼ばれるコールバック。以下の形式で進捗を受け取ります:

```python
def progress_hook(d: dict) -> None:
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
        downloaded = d.get("downloaded_bytes", 0)
        pct = round(downloaded / total * 100, 1)
        # Redis に保存など
```
