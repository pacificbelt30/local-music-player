# LAN 内の HTTPS・hosts・DNS 設定

HTTPS のホスト名は利用者が指定します。外部の IP 変換 DNS サービスは利用しません。
Caddy がローカル CA から証明書を発行し、LAN 内のサーバーへ HTTPS で接続できます。

## ホスト名と OAuth の関係

- 所有ドメインがない場合：ホームネットワーク用の `music.home.arpa` などを hosts またはローカル DNS に登録します。LAN 内の HTTPS 用です。
- 所有ドメインがある場合：そのサブドメインを同じ方法でサーバーの LAN 内 IP に向けられます。公開 DNS に LAN 内 IP を載せる必要はありません。
- 同じ PC の `http://localhost:8000` で利用する場合：HTTPS の追加は不要です。

**名前解決と Google の OAuth 登録条件は別です。** hosts やルーターの DNS に登録しても、
`.home.arpa`、`.local`、`.lan` や IP アドレスが Google の Web アプリ向けリダイレクト先として使えるようにはなりません。
LAN 内での HTTPS は所有ドメインなしでも使えますが、OAuth の戻り先は既存の localhost 設定を維持するのが既定です。
Google の固定 HTTPS 戻り先を使いたい場合は、Google が登録を受け付ける公開ドメイン配下の名前を用意してください。
本番審査で所有権確認が必要な場合は、所有ドメインが必要です。

## 1. 設定を生成する

まずサーバーの LAN 内 IP を固定するか、ルーターで DHCP の固定割り当てを設定します。
リポジトリのルートで実行します。Python 3 の標準ライブラリだけを使い、追加インストールは不要です。

```bash
python scripts/configure_https.py \
  --hostname music.home.arpa \
  --server-ip 192.168.1.50
```

`https-setup/` に次のファイルを生成します。

| ファイル | 用途 |
|---|---|
| `https.env` | Compose の HTTPS 設定と OAuth の戻り先 |
| `hosts.txt` | クライアント端末の hosts に追加する1行 |
| `dnsmasq.conf` | dnsmasq を使う DNS サーバーのホストレコード |
| `router-dns.txt` | ルーターに登録するホスト名・A/AAAA・IP |

端末の hosts やルーター、稼働中の `.env` は変更しません。
既存の生成ファイルは上書きしないため、設定を作り直す場合は `--output-dir https-setup-new` などを指定してください。
IPv4・IPv6 に対応します。IPv6 は利用環境の接続性も確認してください。

所有ドメインのサブドメインを OAuth の戻り先としても使う場合は `--oauth-mode https` を指定します。
以下のホスト名は例なので、実際の所有ドメインに置き換えてください。

```bash
python scripts/configure_https.py \
  --hostname music.your-domain.com --server-ip 192.168.1.50 \
  --oauth-mode https --output-dir https-setup
```

443 が使用中なら `--port 8443` を指定できます。
ツールが `HTTPS_PORT=8443` と `HTTPS_URL_PORT=:8443` をセットで生成し、HTTPS の OAuth 戻り先にも同じポートを付けます。
localhost モードの OAuth は通常の API ポート 8000 を使います。API の公開ポートを変えている場合は生成した戻り先も合わせてください。

## 2. hosts またはローカル DNS に登録する

どちらかを選びます。サーバー自身だけでなく、**ブラウザを使う端末で名前解決できること**が必要です。

### PC ごとの hosts

生成した `hosts.txt` の行を、既存の hosts を消さずに追加します。

```text
192.168.1.50 music.home.arpa
```

- Windows：`C:\Windows\System32\drivers\etc\hosts` を管理者権限のエディターで編集
- macOS / Linux：`/etc/hosts` を管理者権限で編集

これは DNS サーバーの変更を必要としません。スマホでは hosts の編集が難しいため、通常は次の DNS 方式を使います。

### ルーターなどのローカル DNS

ルーターの管理画面に「ローカル DNS」「ホスト名登録」「DNS ホストレコード」などの機能があれば、
`router-dns.txt` にある名前と IP を登録します。IPv4 は A、IPv6 は AAAA レコードです。
機種によってホスト名 `music` とローカルドメイン `home.arpa` を分けて設定する場合があります。
DHCP の固定割り当てだけでは DNS レコードを作らない機種もあるため、名前解決まで確認してください。

ブラウザを使う端末には、DHCP の DNS 配布設定などでそのルーター／DNS サーバーを利用させます。
ブラウザのセキュア DNS、端末のプライベート DNS、VPN が別の DNS を使う場合は、ローカル名を解決できる設定にしてください。
端末から解決できない場合、PC の hosts 方式も選択できます。

dnsmasq を管理している場合は、生成した `dnsmasq.conf` をその環境の設定ディレクトリに配置し、
`dnsmasq --test` で確認してから設定を再読み込みします。ルーターへのファイル配置や再読み込み方法は機種ごとに異なります。

**アプリから端末やルーターの設定を自動適用する機能はありません。**
コンテナ内の `/etc/hosts` を変更してもブラウザ端末には反映されず、ルーターの管理 API も共通ではないためです。
設定の生成まではツールで行い、適用は各端末・ルーターの管理機能で行います。

## 3. HTTPS を起動する

通常の `.env` を用意します。既存ファイルはそのまま使い、ない場合だけ `.env.example` からコピーして編集します。
生成した設定を追加で読み込みます。複数の `--env-file` に対応する Docker Compose v2 を使用してください。

```bash
docker compose --env-file .env --env-file https-setup/https.env \
  -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

後に指定した `https.env` の設定が優先されます。既存の IP:8000 でのアクセスも引き続き使えます。
`--output-dir` を変えた場合は `--env-file` のパスも変えてください。

ツールを使わず `.env` で設定することもできます。

```dotenv
HTTPS_HOSTNAME=music.home.arpa
HTTPS_PORT=443
HTTPS_URL_PORT=
# 未指定なら既存の YOUTUBE_REDIRECT_URI を維持します。
HTTPS_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/youtube/auth/callback
```

必要なら `HTTPS_BIND_IP=192.168.1.50` で HTTPS を LAN インターフェイスだけにバインドできます。
Google 向けのドメインを使う場合は `HTTPS_OAUTH_REDIRECT_URI` をその HTTPS URL に変更します。
この設定は公開ステータスや7日の更新トークン制限を変更しません。

## 4. 証明書を端末で信頼する（初回のみ）

Caddy がローカル CA とサーバー証明書を自動作成します。使う各端末で CA を信頼する設定が必要です。

```bash
docker compose --env-file .env --env-file https-setup/https.env \
  -f docker-compose.yml -f docker-compose.https.yml cp \
  https:/data/caddy/pki/authorities/local/root.crt ./https-root.crt
```

Windows はユーザーの「信頼されたルート証明機関」、macOS はキーチェーンに登録して信頼を設定します。
iOS はプロファイルとしてインストールしたあと「証明書信頼設定」で完全な信頼を有効にします。
Android は「CA 証明書のインストール」を使います。ブラウザ・端末の管理ポリシーによって操作は異なります。
Firefox が OS の信頼ストアを使わない場合は、Firefox にもインポートします。
証明書の警告を無視して進まず、正しい CA を登録してください。

配布するのは `root.crt` のみで、CA の秘密鍵は配布しません。
CA の秘密鍵は `https-data` に保存されるため、このボリュームも保護してください。
通常のコンテナ再作成や `docker compose down` では CA を維持します。
`down -v` などで `https-data` を削除すると、端末側の信頼設定をやり直す必要があります。

`https://music.home.arpa` をブラウザで開き、証明書の警告なしに表示できることを確認します。

## 5. OAuth の戻り先を確認する

### 所有ドメインなし・localhost モード

HTTPS で通常利用し、認証時だけ SSH 転送で既存の localhost 戻り先を使えます。

```bash
ssh -N -L 8000:localhost:8000 user@192.168.1.50
```

接続中に手元のブラウザで `http://localhost:8000` を開いて認証します。
Google の登録先は `http://localhost:8000/api/v1/youtube/auth/callback` です。
認証後に SSH を切り、通常の HTTPS 画面へ戻って再読み込みできます。
スマホから直接認証したい場合は、Google が登録を受け付ける HTTPS ホスト名を用意してください。

### HTTPS の OAuth モード

生成された `HTTPS_OAUTH_REDIRECT_URI` と完全一致する URL を、Google Cloud の OAuth クライアントの
「承認済みリダイレクト URI」に登録します。例：

```text
https://music.your-domain.com/api/v1/youtube/auth/callback
```

HTTPS 画面から接続・再認証すると、そのホスト名へ戻ります。
Google への実際の URI 登録と認証は利用環境で確認してください。

## 更新

更新時にも生成した環境ファイルと両方の Compose ファイルを指定します。

```bash
git pull
docker compose --env-file .env --env-file https-setup/https.env \
  -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

既存の HTTPS リバースプロキシを利用する場合は追加の Caddy は不要です。
そのプロキシから API へ転送し、`.env` の `YOUTUBE_REDIRECT_URI` を実際に使用する戻り先に合わせてください。
