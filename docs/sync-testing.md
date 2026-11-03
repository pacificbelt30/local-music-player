# 同期の並行実行・コンテナ検証

通常のバックエンドテストに、重複同期・重複DL・処理中の一時停止／削除・リース更新／失効の回帰テストを含めています。フロントエンドでは自動更新中の行・詳細・エラー展開・フォーカス・スクロールの維持、非表示時の通信停止、通信失敗からの復帰を確認します。

## 実コンテナの検証

```sh
docker build -t local-music-player:sync-test .
cd backend
SYNC_DOCKER_TESTS=1 SYNC_APP_TEST_IMAGE=local-music-player:sync-test python -m pytest tests/integration/test_sync_lifecycle.py -v
```

実際のAPI・Celery（並列ワーカー）・Redis・永続SQLite・FFmpegを使い、以下を確認します。

- 同じ同期とDLを同時に依頼しても、長いDL中に重複取得しない
- 一時停止中の待機DLを保留し、再開後に取得できる。手動の1回分は停止中も取得できる
- API／ワーカーを破棄・再作成しても設定が残り、ロック失効後の通常の手動同期でDLを復旧できる
- DL途中でファイル削除を指定すると、ファイルとDB行が復活しない
- 進捗配信中にRedisを5秒待たせても、別のAPIが応答し、進捗配信も再開する

YouTubeの一覧取得・メディア取得境界だけはコンテナ専用の固定アダプターに置き換え、FFmpegで短い音声を生成します。YouTubeの外部仕様への互換性を保証するテストではありません。アダプターは通常のアプリ起動では読み込みません。

テスト専用のコンテナ・ネットワークと一時ディレクトリだけを作成し、終了時に削除します。既存の稼働コンテナや保存データには触れません。CIでも同じコンテナテストを実行します。


## 新しいワークフローの回帰テスト

通常のテストには、20件までの一括確認と重複検出、追加キュー登録の再開、プロファイルのスナップショットと適用確認、原因別の復旧、一時停止中の再認証、保留・復元・保持解除、保存領域外と共有参照ファイルの保護、ナノ秒精度のSyncthingファイル確認、既存DBの移行・巻き戻しを含めています。

`test_sync_lifecycle.py` は一括追加→実際のFFmpeg生成→同期元の差分→復元→プロファイル変更もAPIから検証します。

Syncthingの実Peer間でもファイル情報とオフライン判定を確認できます。

```sh
docker pull syncthing/syncthing:2.1.6
cd backend
SYNCTHING_DOCKER_TESTS=1 python -m pytest tests/integration/test_syncthing_recreate.py::test_file_level_delivery_evidence_confirms_the_selected_peer -v
```

ブラウザではPC・390px・320px幅の同期、一括確認、原因別案内、プロファイル、履歴・復元を表示し、横はみ出しと実行時エラーを確認します。
