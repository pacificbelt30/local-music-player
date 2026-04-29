# プレイヤー (`player.js`)

`frontend/js/player.js` — 画面下部に固定表示されるオーディオプレイヤーです。

## UI 構成

```
┌──────────────────────────────────────────────────────┐
│ [サムネ]  タイトル / アーティスト                     │
│           🔀 ⏮ ▶ ⏭ 🔁    00:00 ──●── 03:33    🔊 ─● │
└──────────────────────────────────────────────────────┘
```

## コントロール

| ボタン | 動作 |
|--------|------|
| 🔀 シャッフル | オン/オフ切り替え（アクティブ時は強調表示） |
| ⏮ 前の曲 | プレイキューの前トラックを再生 |
| ▶ / ⏸ 再生/停止 | `audio.play()` / `audio.pause()` のトグル |
| ⏭ 次の曲 | プレイキューの次トラックを再生 |
| 🔁 リピート | `none` → `all` → `one` のサイクル |
| シークバー | `audio.currentTime` を変更（Range リクエスト対応） |
| 🔊 音量 | `localStorage` に保存（モバイルでは非表示） |

### リピートモード

| モード | 動作 |
|--------|------|
| `none` | キュー末尾で停止 |
| `all` | 末尾で先頭に戻る |
| `one` | 同じトラックを繰り返す |

---

## 再生状態の永続化

以下の状態を `localStorage` に保存し、ページリロード後に復元します（自動再生はしません）。

| キー | 内容 |
|------|------|
| `player_playlist` | 現在のプレイリスト（JSON） |
| `player_index` | 現在のトラックインデックス |
| `player_position` | 再生位置（秒）※2 秒ごとに更新 |
| `player_shuffle` | シャッフルの状態 |
| `player_repeat` | リピートモード |
| `player_volume` | 音量（0〜100） |

---

## 外部インターフェース

```javascript
import { player } from "./player.js";

player.play(tracks, index);  // インデックス指定でプレイリストを再生
player.prev();               // 前のトラック
player.next();               // 次のトラック
```

### イベント連携

`playlists.js` からカスタムイベントでトラックを受け取ります:

```javascript
// playlists.js
window.dispatchEvent(new CustomEvent("play-playlist-track", { detail: track }));

// player.js（受信側）
window.addEventListener("play-playlist-track", (e) => {
  player.play([e.detail], 0);
});
```

### Audio イベント

| イベント | 動作 |
|---------|------|
| `audio.ended` | リピートモードに応じて次/同トラックを再生 |
| `audio.timeupdate` | シークバーと現在時間を更新、位置を保存 |
| `audio.loadedmetadata` | 総再生時間を表示、復元時にシーク位置を設定 |
