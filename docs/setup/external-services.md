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

#### パターン 2: LAN の VM にセルフホストする場合（同一 LAN からアクセス）

!!! danger "LAN の IP アドレスはリダイレクト URI に登録できない"
    Google Cloud Console は、`localhost` および `127.0.0.1` 以外の **IP アドレスをリダイレクト URI として登録できません**。  
    `http://192.168.1.50:8000/...` を入力してもエラーになります。

以下の 3 つの方法で回避できます。

---

##### 方法 A: カスタムホスト名 + /etc/hosts（推奨）

**概要**: 任意のホスト名を決めて `/etc/hosts` でサーバーの IP に向け、そのホスト名をリダイレクト URI として登録する。

!!! tip "OAuth 認証フローは初回セットアップ時の一度だけ"
    トークンは DB に保存されるため、OAuth フローを踏むのはセットアップ時の 1 回だけです。  
    **認証を行う PC 1 台にだけ `/etc/hosts` を設定すれば十分**です。  
    その後は他のデバイスから IP アドレスで普通にアクセスできます。

**手順:**

1. **ホスト名を決める**（例: `synctunehub.home`。TLD は何でも可）

2. **`.env` を設定する**

    ```dotenv
    YOUTUBE_REDIRECT_URI=http://synctunehub.home:8000/api/v1/youtube/auth/callback
    ```

3. **Google Cloud Console に登録する**  
    「承認済みリダイレクト URI」に上記と同じ URI を追加する。  
    ホスト名形式であれば HTTP でも登録できます（「テスト」モードのアプリの場合）。

4. **認証を行う PC の `/etc/hosts` にエントリを追加する**

    === "Linux / macOS"

        ```bash
        # /etc/hosts に追記（sudo が必要）
        192.168.1.50  synctunehub.home
        ```

    === "Windows"

        `C:\Windows\System32\drivers\etc\hosts` をメモ帳（管理者権限）で開き、以下を追記します。

        ```
        192.168.1.50  synctunehub.home
        ```

5. **OAuth フローを実行する**  
    ブラウザで `http://synctunehub.home:8000` にアクセスし、「YouTubeアカウントに接続」をクリックします。  
    認証完了後は、他のデバイスから `http://192.168.1.50:8000` で通常どおりアクセスできます。

---

##### 方法 B: nip.io（ワイルドカード DNS サービス）

**概要**: `nip.io` という公開 DNS サービスを使う。`<IP>.nip.io` 形式のドメイン名が自動的にその IP に解決されるため、`/etc/hosts` の設定が不要。

```dotenv
# 192.168.1.50 の場合
YOUTUBE_REDIRECT_URI=http://192.168.1.50.nip.io:8000/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に上記 URI を追加します。

!!! note "nip.io の要件"
    - DNS 解決にインターネット接続が必要です（LAN 内のみのエアギャップ環境では使用不可）
    - 認証フロー時に `http://192.168.1.50.nip.io:8000` にブラウザでアクセスする必要があります  
      （Google がブラウザをリダイレクトするため、名前解決できないと認証が完了しません）

---

##### 方法 C: SSH ローカルポートフォワーディング

**概要**: SSH でサーバーのポートを手元の `localhost` に転送し、`localhost` 宛てのリダイレクト URI（デフォルト設定）をそのまま使う。**Google Cloud の設定変更は不要**。

```bash
# 認証フローを踏む前に実行し、セッションを維持する
ssh -N -L 8000:localhost:8000 user@192.168.1.50
```

`.env` はデフォルトのまま使えます。

```dotenv
YOUTUBE_REDIRECT_URI=http://localhost:8000/api/v1/youtube/auth/callback
```

ブラウザで `http://localhost:8000` を開いて OAuth フローを実行します。  
認証完了後は SSH セッションを切断し、以後は IP アドレスで通常どおりアクセスできます。

!!! note "SSH が必要な場面"
    ポートフォワーディングは **OAuth フロー実行中だけ** 維持すれば十分です。  
    認証後のトークンは DB に保存されているため、SSH は不要になります。

---

#### パターン 3: 公開ドメインで動かす場合（本番環境）

```dotenv
YOUTUBE_REDIRECT_URI=https://example.com/api/v1/youtube/auth/callback
```

Google Cloud Console の「承認済みリダイレクト URI」に同じ URI を追加してください。

!!! tip "本番環境では HTTPS が必須"
    外部からアクセス可能なサーバーで運用する場合、Google は HTTPS の URI のみを承認します。

---

### 参照リンク

- Google Cloud Console: <https://console.cloud.google.com/>
- YouTube Data API v3 の有効化: <https://developers.google.com/youtube/v3/getting-started>
- OAuth 同意画面の設定: <https://support.google.com/cloud/answer/10311615>
- OAuth クライアント ID の作成: <https://support.google.com/cloud/answer/6158849>
- YouTube チャンネルの作成: <https://support.google.com/youtube/answer/1646861>

---

## YouTube API 401 エラー チェックシート

### エラーの種類を特定する

まず画面またはブラウザの開発者ツール（Network タブ）でレスポンスを確認し、エラー種別を特定します。

| 表示 | 意味 |
|------|------|
| `401 Not authenticated with YouTube` | アプリの DB にトークンが存在しない |
| `502 YouTube API error: … 401 …` | トークンはあるが Google API に拒否された |
| `502 YouTube API error: … invalid_grant …` | リフレッシュトークンが失効している |
| プレイリスト一覧が空（エラーなし） | 認証アカウントに YouTube チャンネルがない |
| 認証フロー自体が開始できない / `redirect_uri_mismatch` | リダイレクト URI の設定ミス（LAN IP を登録しようとしている場合は[パターン 2](#パターン-2-lan-の-vm-にセルフホストする場合同一-lan-からアクセス) を参照） |

---

### チェックリスト

以下を上から順に確認してください。

#### □ 1. トークンが DB に保存されているか

```bash
curl http://localhost:8000/api/v1/youtube/auth/status
# → {"authenticated": true, ...} であれば保存済み
# → {"authenticated": false} であれば未認証
```

`false` の場合は **UI から「YouTubeアカウントに接続」または「トークンを直接入力」** で認証を行ってください。

---

#### □ 2.【最多】リフレッシュトークンが 7 日で失効していないか

!!! warning "OAuth 同意画面が「テスト」モードの場合、リフレッシュトークンは 7 日で失効します"
    Google Cloud Console の OAuth 同意画面のステータスが **「テスト」** のままの場合、
    発行されたリフレッシュトークンは **発行から 7 日後に自動的に無効化** されます。

    これによりアプリは毎週 `502 YouTube API error: … invalid_grant …` を返すようになります。

    **対処**: UI から一度「YouTubeとの接続を解除」し、再度「YouTubeアカウントに接続」で
    OAuth フローをやり直してください（7 日ごとに繰り返す必要があります）。

    個人利用で繰り返しが煩わしい場合は、Google アカウントに Google Cloud の「オーナー」権限を付与した状態で OAuth 同意画面を **「本番」** に公開することで制限を解除できますが、Google の審査プロセスが必要です。

---

#### □ 3. Google アカウントのセキュリティ設定でアクセスを手動削除していないか

Google アカウントのセキュリティページ（`myaccount.google.com/security`）→
「サードパーティ アプリとサービス」でアプリのアクセス権が残っているか確認します。

「アクセスを削除」した場合はリフレッシュトークンが即座に無効化されます。
→ UI から再認証してください。

---

#### □ 4. `YOUTUBE_CLIENT_SECRET` が最新か

Google Cloud Console で OAuth クライアントのシークレットを**ローテーション（再生成）**すると、
旧シークレットで取得したリフレッシュトークンはすべて無効になります。

- `.env` の `YOUTUBE_CLIENT_SECRET` が Google Cloud Console の現在の値と一致しているか確認
- Docker の場合は `.env` 変更後に `docker compose restart` が必要

---

#### □ 5. YouTube Data API v3 が有効か

[Google Cloud Console](https://console.cloud.google.com/) →
「APIとサービス」→「有効にしたAPI」で **YouTube Data API v3** が一覧にあるか確認します。

無効になっていた場合は「ライブラリ」から再度有効化してください。

---

#### □ 6. OAuth クライアントが削除・無効化されていないか

「APIとサービス」→「認証情報」で該当の OAuth クライアント ID が存在するか確認します。
削除されていた場合は再作成し、`.env` を更新して再認証が必要です。

---

#### □ 7. 認証アカウントに YouTube チャンネルがあるか

API 呼び出しは成功（200）するが**プレイリスト一覧が空**の場合、
認証に使った Google アカウントに YouTube チャンネルが存在しない可能性があります。

→ [YouTube チャンネルを作成する](https://support.google.com/youtube/answer/1646861) 後、
プレイリスト一覧を再取得してください。

---

#### □ 8.【直接入力方式のみ】アクセストークンの有効期限が切れていないか

「トークンを直接入力」でリフレッシュトークンを入力しなかった場合、
アクセストークンの有効期限（通常 **1 時間**）が過ぎると自動更新されません。

- 期限切れ後はアプリが `502` または `401` を返します
- UI の **「トークンを更新」** から [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) で新しいアクセストークンを取得して再入力してください

---

### 再認証の手順

上記チェックで「再認証が必要」と判断した場合:

1. Playlists パネルの **「YouTubeとの接続を解除」** をクリック（DBのトークンを削除）
2. **「YouTubeアカウントに接続」** をクリックして OAuth フローをやり直す
3. `GET /api/v1/youtube/auth/status` で `authenticated: true` を確認

---

## 補足: トークン直接入力方式

UI の「トークンを直接入力」を使う場合は `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` は必須ではありません。  
ただし、Access Token の有効期限が通常 1 時間のため、定期的な再入力が必要です。

- OAuth 2.0 Playground: <https://developers.google.com/oauthplayground/>

## 関連ドキュメント

- [環境設定リファレンス](../deployment/configuration.md)
- [使い方ガイド（YouTube / Syncthing 操作）](../usage.md)
