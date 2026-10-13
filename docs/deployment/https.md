# LAN 内で固定ホスト名と HTTPS を使う

同じ PC の `http://localhost:8000` で OAuth を使う場合は、この構成は不要です。
別 PC やスマホから LAN 内のサーバーを使い、認証後の localhost を IP に書き換える手間をなくしたい場合に使います。

追加の Compose ファイルで Caddy を起動し、HTTPS の入口と OAuth の戻り先を同じ固定ホスト名に揃えます。
サーバーの外部公開・ルーターのポート転送・ドメイン購入は不要です。

## 1. ホスト名を決める

サーバーの LAN 内 IP を固定するか、ルーターで DHCP の固定割り当てを設定します。
例えば IP が `192.168.1.50` なら、`192-168-1-50.nip.io` はその IP に名前解決されます。
所有ドメインがある場合は、そのサブドメインをローカル DNS または hosts で同じ IP に向けても構いません。

`nip.io` は外部 DNS サービスです。名前解決にはインターネット接続が必要で、
ルーターの DNS リバインディング保護によってプライベート IP への応答がブロックされることがあります。
その場合は同じホスト名をルーターのローカル DNS に登録するか、PC の hosts に登録します。
リゾルバのソフトウェアを書き換える必要はありません。

`.local`、`.lan`、IP そのものは Google の Web アプリ向けリダイレクト先に使えません。
Google の HTTPS・公開 TLD の要件を満たす名前を使ってください。
`nip.io` は第三者所有のドメインなので、所有権確認を求められる Google の本番審査には適しません。
この構成の追加では、Google 側の審査やテストモードの7日制限は変わりません。

## 2. HTTPS を起動する

リポジトリの `.env` に追加します（IP は実際のものに置き換えてください）。

```dotenv
HTTPS_HOSTNAME=192-168-1-50.nip.io
```

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

443 番ポートで HTTPS を提供します。既存の IP:8000 でのアクセスも引き続き使えます。
HTTPS 構成を使うと API の `YOUTUBE_REDIRECT_URI` は固定ホスト名の HTTPS URL に上書きされます。
`.env` に残っている localhost の値より優先されるため、毎回書き換える必要はありません。

443 が他のアプリで使用中なら `.env` に両方設定します。

```dotenv
HTTPS_PORT=8443
HTTPS_URL_PORT=:8443
```

この場合のアクセス先と Google の登録先には `:8443` を付けます。
必要なら `HTTPS_BIND_IP=192.168.1.50` で HTTPS を LAN インターフェイスだけにバインドできます。

## 3. 証明書を端末で信頼する（初回のみ）

Caddy がローカル CA とサーバー証明書を自動作成します。
ブラウザを使う各端末に、その CA のルート証明書を信頼する設定が必要です。
証明書の警告を無視して進む方法ではなく、信頼ストアに登録してください。

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml cp \
  https:/data/caddy/pki/authorities/local/root.crt ./https-root.crt
```

Windows はユーザーの「信頼されたルート証明機関」、macOS はキーチェーンに登録して信頼を設定します。
iOS はプロファイルとしてインストールしたあと「証明書信頼設定」で完全な信頼を有効にします。
Android は設定の「CA 証明書のインストール」を使用します。ブラウザや端末の管理ポリシーによって操作は異なります。
Firefox が OS の信頼ストアを使わない設定なら、Firefox の証明書設定にもインポートします。

**配布するのは `root.crt` のみです。CA の秘密鍵を配布しないでください。**
作業後に `https-root.crt` を削除しても、Caddy 内の CA は維持されます。
`https-data` ボリュームを削除すると CA が変わるため、端末での登録をやり直す必要があります。
通常のコンテナ再作成や `docker compose down` では維持されます。`down -v` は使用しないでください。

ブラウザで `https://192-168-1-50.nip.io` を開き、証明書の警告なしに表示できることを確認します。

## 4. Google に登録して認証する

Google Cloud の OAuth クライアント（ウェブ アプリケーション）の「承認済みリダイレクト URI」に追加します。

```text
https://192-168-1-50.nip.io/api/v1/youtube/auth/callback
```

HTTPS の画面から「YouTubeアカウントに接続」または「再認証（OAuth）」を押します。
認証後は同じ HTTPS ホスト名へ戻ります。Google の登録値はスキーム・ホスト・ポート・パスまで完全一致させてください。
ホスト名を Google に登録できない場合は、localhost を使う SSH 転送方式を使うか、所有ドメインを用意してください。

HTTPS の通信とコンテナ再作成は回帰テストで確認しています。
Google Cloud への実際の URI 登録・認証と、各端末の信頼設定は利用環境で確認してください。

## 更新・停止

HTTPS を使い始めた後は、更新時にも両方の Compose ファイルを指定します。

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

Caddy は自動でサーバー証明書を更新します。ローカル CA の更新・変更時には端末側の信頼設定も確認してください。
既存の HTTPS リバースプロキシがある場合は追加の Caddy は不要です。
そこから `api:8000` またはサーバーの `8000` 番ポートへ転送し、
`.env` の `YOUTUBE_REDIRECT_URI` を実際の HTTPS URL に合わせてください。
