# ファイルサービス

`backend/app/services/file_service.py` — ファイルシステム操作を提供します。

## 関数

### `delete_track_files(file_path, thumbnail_path=None) -> None`

トラックに関連するファイルをディスクから削除します。

**引数**

| 引数 | 型 | 説明 |
|------|-----|------|
| `file_path` | str | 音声ファイルの絶対パス |
| `thumbnail_path` | str \| None | サムネイル画像の絶対パス（省略可） |

**削除対象**

1. 音声ファイル（`file_path`）
2. サムネイル画像（`thumbnail_path` が指定されている場合）
3. `.info.json` サイドカーファイル（`{stem}.info.json` が存在する場合）

**例**

```
/downloads/Rick Astley/Never Gonna Give You Up.mp3  ← 削除
/downloads/Rick Astley/Never Gonna Give You Up.jpg  ← 削除
/downloads/Rick Astley/Never Gonna Give You Up.info.json  ← 削除（存在すれば）
```

**注意**

- 存在しないファイルはスキップ（エラーなし）
- 親ディレクトリは削除しない

## 利用箇所

| 呼び出し元 | タイミング |
|-----------|-----------|
| `api/urls.py` | URL 削除時に `delete_files=true` が指定された場合 |
| `api/tracks.py` | トラック削除時に `delete_file=true` が指定された場合 |
| `tasks/sync_playlist.py` | プレイリストから削除されたトラックのファイル削除 |
