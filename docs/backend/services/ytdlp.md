# yt-dlp サービス

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
