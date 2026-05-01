# 初期設定（外部サービス連携）

このページは、初期導入時に必要になりやすい外部サービス連携について「どの env に何を入れるか」と「その取得元」をまとめたものです。詳細な操作手順は公式ドキュメントを参照してください。

## Syncthing 連携

### 必須 env

- `SYNCTHING_URL`
- `SYNCTHING_API_KEY`

### 設定値と取得元

- `SYNCTHING_URL`: Syncthing GUI / API の URL（例: `http://localhost:8384`）
- `SYNCTHING_API_KEY`: Syncthing の GUI から取得した API キー

### 参照リンク

- Syncthing 公式: <https://syncthing.net/>
- Syncthing ユーザーガイド（設定全般）: <https://docs.syncthing.net/users/index.html>
- Syncthing GUI の設定項目（API キー含む）: <https://docs.syncthing.net/users/config.html>

## YouTube（Google Cloud OAuth2）連携

### 必須 env（OAuth2 フロー利用時）

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REDIRECT_URI`

### 設定値と取得元

- `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`: Google Cloud の OAuth クライアント情報
- `YOUTUBE_REDIRECT_URI`: アプリ側コールバック URL（既定: `http://localhost:8000/api/v1/youtube/auth/callback`）


### リダイレクト URI の注意（サーバーIP運用）

リモートサーバー（例: `192.168.1.50`）で運用する場合は、`YOUTUBE_REDIRECT_URI` をサーバーのIP/FQDNに合わせて設定します。

```dotenv
YOUTUBE_REDIRECT_URI=http://192.168.1.50:8000/api/v1/youtube/auth/callback
```

Google Cloud 側の OAuth クライアント設定（承認済みリダイレクト URI）にも、**同じ URI を完全一致で登録**してください。

### 参照リンク

- Google Cloud Console: <https://console.cloud.google.com/>
- YouTube Data API の有効化: <https://developers.google.com/youtube/v3/getting-started>
- OAuth 同意画面の設定: <https://support.google.com/cloud/answer/10311615>
- OAuth クライアント ID 作成: <https://support.google.com/cloud/answer/6158849>

## 補足: トークン直接入力方式

UI の「トークンを直接入力」を使う場合は `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` は必須ではありません。

- OAuth 2.0 Playground: <https://developers.google.com/oauthplayground/>

## 関連ドキュメント

- [環境設定リファレンス](../deployment/configuration.md)
- [使い方ガイド（YouTube / Syncthing 操作）](../usage.md)
