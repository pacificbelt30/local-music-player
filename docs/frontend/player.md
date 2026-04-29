# プレイヤー (`player.js`)

`frontend/js/player.js` — 画面下部に固定表示されるオーディオプレイヤーを担当します。

## UI 構成

```
┌──────────────────────────────────────────────────────────────────┐
│ [サムネイル]  タイトル     🔀 ⏮ ▶ ⏭ 🔁   00:00 ──●── 03:33  🔊 ──● │
│              アーティスト                                         │
└──────────────────────────────────────────────────────────────────┘
```

## 主な機能

### トラック再生

外部モジュール（`library.js`）またはカスタムイベント（`play-playlist-track`）からトラックオブジェクトを受け取って再生を開始します。

**再生時の動作**

1. `track.stream_url`（`/api/v1/stream/{id}`）を `<audio>` 要素の `src` に設定
2. `audio.play()` を呼び出す
3. サムネイル・タイトル・アーティストを表示更新
4. `localStorage` に再生状態を保存

### コントロール

| ボタン | 動作 |
|--------|------|
| シャッフル (🔀) | シャッフルのオン/オフ切り替え。アクティブ時はボタンが強調表示 |
| 前の曲 (⏮) | プレイキュー内の前のトラックを再生（シャッフル考慮） |
| 再生/一時停止 (▶/⏸) | `audio.play()` / `audio.pause()` のトグル |
| 次の曲 (⏭) | プレイキュー内の次のトラックを再生（シャッフル考慮） |
| リピート (🔁/🔂) | `none` → `all`（全曲リピート）→ `one`（1曲リピート）のサイクル |

### シークバー

`<input type="range">` で現在位置を操作します。

- `audio.timeupdate` イベントで現在位置を更新
- ドラッグ操作で `audio.currentTime` を変更
- バックエンドが HTTP Range リクエストに対応しているためシーク可能

### ボリューム調整

プレイヤーバー右端に音量スライダーを配置しています。

- 値は `localStorage` に保存され、ページリロード後も維持
- モバイル（600px 以下）では非表示

### シャッフル

```
シャッフルON: ランダムな順序でトラックを再生
シャッフルOFF: 元のプレイリスト順で再生
```

Fisher-Yates シャッフルアルゴリズムでシャッフル順序を生成します。シャッフル切り替え時は現在のトラックを先頭に維持します。

### リピート

| モード | 動作 |
|--------|------|
| `none` | キュー末尾で停止 |
| `all` | キュー末尾で先頭に戻る |
| `one` | 同じトラックを繰り返す |

### 再生状態の永続化

以下の状態を `localStorage` に保存し、ページリロード後に復元します:

| キー | 内容 |
|-----|------|
| `player_playlist` | 現在のプレイリスト（JSON） |
| `player_index` | 現在のトラックインデックス |
| `player_position` | 再生位置（秒）※2秒ごとに更新 |
| `player_shuffle` | シャッフルの状態 |
| `player_repeat` | リピートモード |
| `player_volume` | 音量（0〜100） |

**注意**: 復元時は自動再生しません（ブラウザのAutoPlay Policy対策）。

### プレイリストパネルとの連携

`playlists.js` が `play-playlist-track` カスタムイベントをディスパッチすると、プレイヤーが受け取って単一トラックを再生します。

```javascript
// playlists.js 側
window.dispatchEvent(new CustomEvent("play-playlist-track", { detail: track }));

// player.js 側（リスナー）
window.addEventListener("play-playlist-track", (e) => {
  play([e.detail], 0);
});
```

## イベント

| イベント | 動作 |
|---------|------|
| `audio.ended` | リピートモードに応じて次のトラックまたは同じトラックを再生 |
| `audio.timeupdate` | シークバーと現在時間を更新、位置を localStorage に保存 |
| `audio.loadedmetadata` | 総再生時間を表示、復元時にシーク位置を設定 |

## 外部インターフェース

他のモジュールから以下の関数を呼び出します:

```javascript
import { player } from "./player.js";

player.play(tracks, index);  // インデックス指定でプレイリストを再生
player.prev();               // 前のトラック
player.next();               // 次のトラック
```
