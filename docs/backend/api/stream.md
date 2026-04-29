# ストリーミング API

音声ファイルのストリーミング再生・サムネイル取得・ファイルダウンロードを提供します。

## エンドポイント

### GET `/api/v1/stream/{track_id}` — 音声ストリーミング

音声ファイルをブラウザにストリーミングします。HTTP Range リクエストに対応しており、シーク操作が可能です。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `track_id` | トラック ID |

**リクエストヘッダー（オプション）**

```
Range: bytes=1048576-2097151
```

**レスポンス**

| 条件 | ステータス | 説明 |
|------|-----------|------|
| Range なし | `200 OK` | ファイル全体をストリーミング |
| Range あり | `206 Partial Content` | 指定バイト範囲のみ返却 |

**レスポンスヘッダー**

```
Content-Type: audio/mpeg
Accept-Ranges: bytes
Content-Length: 5120000
Cache-Control: public, max-age=3600
Content-Range: bytes 1048576-2097151/5120000  (Range リクエスト時のみ)
```

**Content-Type マッピング**

| 拡張子 | Content-Type |
|--------|-------------|
| `.mp3` | `audio/mpeg` |
| `.flac` | `audio/flac` |
| `.aac` | `audio/aac` |
| `.ogg` | `audio/ogg` |
| `.m4a` | `audio/mp4` |

**副作用**

- `Track.play_count` をインクリメント
- `Track.last_played_at` を現在時刻（UTC）に更新

**エラー**

| コード | 条件 |
|--------|------|
| `404` | トラックが DB に存在しない |
| `404` | ファイルがディスク上に存在しない |

---

### GET `/api/v1/thumbnails/{track_id}` — サムネイル取得

トラックのサムネイル画像を返します。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `track_id` | トラック ID |

**レスポンスヘッダー**

```
Cache-Control: public, max-age=86400
```

**Content-Type マッピング**

| 拡張子 | Content-Type |
|--------|-------------|
| `.jpg` | `image/jpeg` |
| `.png` | `image/png` |
| `.webp` | `image/webp` |

**エラー**

| コード | 条件 |
|--------|------|
| `404` | トラックが存在しない、またはサムネイルパスが未設定 |
| `404` | サムネイルファイルがディスク上に存在しない |

---

### GET `/api/v1/files/{track_id}/download` — ファイルダウンロード

音声ファイルをダウンロード用にレスポンスします。Range リクエスト対応。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `track_id` | トラック ID |

**レスポンスヘッダー（追加）**

```
Content-Disposition: attachment; filename="Never Gonna Give You Up.mp3"
```

ファイル名は `{title}.{file_format}` の形式。ダブルクォートはシングルクォートにエスケープされます。

**エラー**

| コード | 条件 |
|--------|------|
| `404` | トラックが存在しない、またはファイルがない |

## 実装詳細

### チャンクサイズ

```python
CHUNK_SIZE = 1024 * 1024  # 1 MB
```

1 MB ずつ非同期で読み込み（`aiofiles`）してストリーミングします。

### Range リクエスト処理

```
Range: bytes={start}-{end}
```

- `end` が省略された場合は `file_size - 1` を使用
- `end` はファイルサイズを超えないよう `min(end, file_size - 1)` でクリップ
