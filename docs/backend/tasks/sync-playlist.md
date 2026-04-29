# プレイリスト同期タスク

`backend/app/tasks/sync_playlist.py` と `scheduler.py` — YouTube プレイリストの同期と定期スケジューリングです。

## `sync_youtube_playlist`

```python
@celery_app.task(name="app.tasks.sync_playlist.sync_youtube_playlist", bind=True, max_retries=2)
def sync_youtube_playlist(self, playlist_sync_id: int) -> None
```

**キュー**: `downloads`  
**最大リトライ**: 2 回（失敗時 60 秒後）

**処理フロー**

1. `YoutubePlaylistSync` を取得（`enabled=False` なら終了）
2. `youtube_api_service.get_fresh_access_token(db)` でトークン取得（なければ終了）
3. `youtube_api_service.get_playlist_items()` でリモートの動画リストを取得
4. DB の `PlaylistSyncTrack` と差分比較:
   - **新規**: `PlaylistSyncTrack` 作成 → `download_playlist_sync_track.apply_async`
   - **復活**（`status=removed` が再追加）: `status=pending` にリセット → `download_playlist_sync_track.apply_async`
   - **既存**: `position` を更新
   - **削除**（リモートに存在しない）: ファイルを削除 → `status=removed`
5. `YoutubePlaylistSync.last_synced` を更新

---

## `download_playlist_sync_track`

```python
@celery_app.task(name="app.tasks.sync_playlist.download_playlist_sync_track", bind=True, max_retries=3)
def download_playlist_sync_track(self, track_id: int) -> None
```

**キュー**: `downloads`  
**最大リトライ**: 3 回（失敗時 30・60・120 秒後）

**保存先**

```
{PLAYLISTS_PATH}/{playlist_id}/{uploader}/{title}.{ext}
```

ディレクトリが存在しない場合は自動作成します。

**処理フロー**

1. `PlaylistSyncTrack` を取得（`complete` または `removed` なら終了）
2. 親 `YoutubePlaylistSync` から `audio_format`・`audio_quality` を取得
3. `track.status = "downloading"`
4. 進捗フック: `pstrack:{track_id}:progress`（TTL 300 秒）を Redis に書き込み
5. `ytdlp_service.download_track(..., base_path=playlists/{playlist_id}/)` でダウンロード
6. `PlaylistSyncTrack` のメタデータ（title・artist・duration_secs・file_path 等）を更新
7. `track.status = "complete"`、`downloaded_at` を設定

---

## `_delete_sync_track_file`

```python
def _delete_sync_track_file(track: PlaylistSyncTrack) -> None
```

音声ファイル・サムネイル・`.info.json` サイドカーを削除します。

---

## スケジューラ (`scheduler.py`)

Beat が 5 分ごとに以下の 2 タスクを起動します。各タスクは `app_settings` の間隔設定を確認してから実行するかどうかを決定します。

### `periodic_playlist_refresh`

```python
@celery_app.task(name="app.tasks.scheduler.periodic_playlist_refresh")
def periodic_playlist_refresh() -> None
```

**動作**

1. `app_settings["url_sync_interval_minutes"]` を取得（デフォルト: 60 分）
2. `url_sync_last_run` から経過時間を計算
3. 間隔が経過していれば:
   - `url_sync_last_run` を現在時刻で更新
   - `sync_enabled=True` かつ `url_type` が `playlist` または `channel` の全 `UrlSource` に `resolve_url` を投入

### `periodic_youtube_playlist_sync`

```python
@celery_app.task(name="app.tasks.scheduler.periodic_youtube_playlist_sync")
def periodic_youtube_playlist_sync() -> None
```

**動作**

1. `app_settings["youtube_sync_interval_minutes"]` を取得（デフォルト: 60 分）
2. `youtube_sync_last_run` から経過時間を計算
3. 間隔が経過していれば:
   - `youtube_sync_last_run` を現在時刻で更新
   - `enabled=True` の全 `YoutubePlaylistSync` に `sync_youtube_playlist` を投入

### 間隔の無効化

`url_sync_interval_minutes` または `youtube_sync_interval_minutes` を `0` に設定すると、その同期は無効になります。
