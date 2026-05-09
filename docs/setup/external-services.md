# 初期設定（外部サービス連携）

このページは、初期導入時に必要になりやすい外部サービス連携について「どの env に何を入れるか」と「その取得元」をまとめたものです。詳細な設定値の意味は公式ドキュメントを参照してください。

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

---

## YouTube（Google Cloud OAuth2）連携

### 前提条件

!!! warning "YouTube チャンネルの開設が必要"
    **認証に使う Google アカウントに YouTube チャンネルが存在していること**が必要です。  
    Google アカウントを持っていても、YouTube チャンネルを作成していないアカウントでは
    API 呼び出しがエラーになります。  
    チャンネルを持っていない場合は先に作成してください。  
    → [YouTube チャンネルを作成する（Google サポート）](https://support.google.com/youtube/answer/1646861)

- Google アカウント（YouTube チャンネル付き）
- Google Cloud アカウント（無料枠で可）

---

### Google Cloud プロジェクトのセットアップ

#### 1. プロジェクト作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 画面上部のプロジェクトセレクター → **「新しいプロジェクト」** をクリック
3. プロジェクト名を入力して **「作成」**

#### 2. YouTube Data API v3 を有効化

1. 左メニュー → **「APIとサービス」** → **「ライブラリ」**
2. 検索ボックスに「YouTube Data API v3」と入力
3. 表示されたカードをクリック → **「有効にする」**

#### 3. OAuth 同意画面を設定

1. 左メニュー → **「APIとサービス」** → **「OAuth 同意画面」**
2. ユーザーの種類: **「外部」** を選択（個人利用でもこちらを選ぶ）
3. アプリ名・サポートメールアドレスを入力して **「保存して次へ」**
4. スコープの追加は不要（そのまま **「保存して次へ」**）

!!! warning "テストユーザーの登録（よくある見落とし）"
    同意画面のステータスが **「テスト」** の状態（Google の審査を受けていない状態）では、
    **テストユーザーとして登録されたアカウントしか認証できません。**

    「テストユーザー」の入力欄に、認証に使う Google アカウントのメールアドレスを追加してください。

    追加しないと、Google のログイン後に「このアプリは Google で確認されていません」という
    警告画面が表示され、「続行」を押しても認証がブロックされます。

    個人利用では「テスト」のまま運用して問題ありません。

#### 4. OAuth クライアント ID を作成

1. 左メニュー → **「APIとサービス」** → **「認証情報」**
2. **「認証情報を作成」** → **「OAuth クライアント ID」**
3. アプリケーションの種類: **「ウェブ アプリケーション」** を選択
4. **承認済みリダイレクト URI** の欄に、後述のリダイレクト URI を入力して **「追加」**
5. **「作成」** をクリック
6. 表示される **クライアント ID** と **クライアント シークレット** をコピーして `.env` に設定

---

### 必須 env（OAuth2 フロー利用時）

- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REDIRECT_URI`

### 設定値と取得元

- `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`: Google Cloud Console の OAuth クライアント情報
- `YOUTUBE_REDIRECT_URI`: アプリ側のコールバック URL（運用環境に合わせて変更が必要）

---

### リダイレクト URI の設定（環境別）

リダイレクト URI は、Google の認証後にブラウザが返ってくる URL です。  
**`.env` の値** と **Google Cloud Console に登録した値** が完全一致していないと認証に失敗します。

また、リダイレクト URI はブラウザが実際にアクセスできる URL でなければなりません。  
ブラウザ（クライアント）からアクセスできないホスト名や IP を指定しても動作しません。

#### パターン 1: localhost で動かす場合（デフォルト）

```dotenv
YOUTUBE_REDIRECT_URI=http://localhost:8000/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に同じ URI を追加してください。

#### パターン 2: LAN の IP アドレスで動かす場合

サーバーの IP アドレスが `192.168.1.50` の場合:

```dotenv
YOUTUBE_REDIRECT_URI=http://192.168.1.50:8000/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に **同じ URI を完全一致で** 追加してください。

!!! note "IP アドレスのリダイレクト URI について"
    Google Cloud では、HTTP の IP アドレス指定はテスト用途で許可されています。  
    ただし、Google のセキュリティポリシーの変更によって将来的に制限される可能性があります。
    長期運用にはドメイン名の使用を推奨します。

#### パターン 3: ホスト名（カスタムドメイン・mDNS）で動かす場合

`http://synctunehub.local:8000` のようなホスト名で運用する場合:

```dotenv
YOUTUBE_REDIRECT_URI=http://synctunehub.local:8000/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に同じ URI を追加します。

さらに、**ブラウザを動かしているマシン**（スマートフォン・PC など）の `/etc/hosts`（Windows の場合は `C:\Windows\System32\drivers\etc\hosts`）にホスト名を追記してください。

```
# /etc/hosts（ブラウザを動かすマシン側）
192.168.1.50  synctunehub.local
```

!!! warning "hosts ファイルはブラウザ側のマシンに設定する"
    `/etc/hosts` はサーバー側ではなく、**認証フローを踏むブラウザが動いているマシン**に設定します。  
    複数のデバイスからアクセスする場合は、それぞれのデバイスに設定が必要です。

!!! warning "Google Cloud はプライベートホスト名を承認済み URI として登録できない場合がある"
    `.local` や社内専用のホスト名は、Google Cloud Console での登録が拒否される場合があります。  
    その場合は IP アドレス（パターン 2）または実在するドメイン名（パターン 4）を使用してください。

#### パターン 4: 公開ドメインで動かす場合（本番環境）

```dotenv
YOUTUBE_REDIRECT_URI=https://example.com/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に同じ URI を追加してください。

!!! tip "本番環境では HTTPS を推奨"
    外部からアクセス可能なサーバーで運用する場合、Google は HTTPS のリダイレクト URI を推奨しています。

---

### 参照リンク

- Google Cloud Console: <https://console.cloud.google.com/>
- YouTube Data API v3 の有効化: <https://developers.google.com/youtube/v3/getting-started>
- OAuth 同意画面の設定: <https://support.google.com/cloud/answer/10311615>
- OAuth クライアント ID の作成: <https://support.google.com/cloud/answer/6158849>
- YouTube チャンネルの作成: <https://support.google.com/youtube/answer/1646861>

---

## 補足: トークン直接入力方式

UI の「トークンを直接入力」を使う場合は `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` は必須ではありません。  
ただし、Access Token の有効期限が通常 1 時間のため、定期的な再入力が必要です。

- OAuth 2.0 Playground: <https://developers.google.com/oauthplayground/>

## 関連ドキュメント

- [環境設定リファレンス](../deployment/configuration.md)
- [使い方ガイド（YouTube / Syncthing 操作）](../usage.md)
