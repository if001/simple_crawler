# search-scrape-server

DuckDuckGo を用いて検索し、取得したページの本文を Markdown として返すシンプルなスクレイプサーバーです。

* FastAPI ベースの HTTP API
* Playwright による JS 必須ページ対応（オプション）
* 同一ドメイン並列制限
* Bot / rate limit / 非200レスポンスの一時キャッシュ
* Docker + uv によるシンプルな起動

---

# 機能

* 検索 → ページ取得 → 本文抽出 → Markdown 変換
* POST `/search` で query を受け取り結果を返却
* DuckDuckGo 検索
* HTTP fetch → 必要に応じて Playwright 昇格
* Bot / 429 / 503 などは一時キャッシュして再アクセスしない
* 同一ドメインの並列アクセス制限

対象:

* テキストページのみ
* PDF / 動画 / 画像は扱いません
* リンクは辿りません

# Docker 起動

## build

```bash
docker build -t search-scrape-server .
```

## run

```bash
docker run --rm -p 8000:8000 search-scrape-server
```

---

# API

## POST /search

検索を実行します。

### request

```json
{
  "q": "python httpx tutorial",
  "k": 5,
  "region": "jp-jp",
  "time_range": "m",
  "enable_browser": true
}
```

| field          | type   | description         |
| -------------- | ------ | ------------------- |
| q              | string | 検索クエリ               |
| k              | int    | 取得件数（1–50）          |
| region         | string | DuckDuckGo region   |
| time_range     | string | any / d / w / m / y |
| enable_browser | bool   | Playwright 昇格を許可    |

---

### response

```json
{
  "query": "python httpx tutorial",
  "k": 5,
  "docs": [
    {
      "url": "...",
      "title": "...",
      "markdown": "..."
    }
  ]
}
```

---

# curl example

```bash
curl -X POST http://localhost:8000/search \
  -H "content-type: application/json" \
  -d '{
    "q": "python httpx tutorial",
    "k": 5
  }'
```

---

# 環境変数

任意。

| variable               | default   | description   |
| ---------------------- | --------- | ------------- |
| GLOBAL_CONCURRENCY     | 8         | 全体並列数         |
| PER_DOMAIN_CONCURRENCY | 2         | 同一ドメイン並列数     |
| NEG_CACHE_DIR          | .negcache | 非200キャッシュ保存先  |
| NEG_CACHE_TTL_S        | 1800      | キャッシュ有効時間     |
| FETCH_TIMEOUT_S        | 20        | fetch timeout |
| MIN_MARKDOWN_CHARS     | 400       | 最低本文サイズ       |

例:

```bash
docker run -p 8000:8000 \
  -e GLOBAL_CONCURRENCY=4 \
  -e PER_DOMAIN_CONCURRENCY=1 \
  search-scrape-server
```

---

# ローカル実行（Dockerなし）

uv を使用します。

## uv install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## install dependencies

```bash
uv sync
uv run playwright install
```

## run

```bash
uv run uvicorn main:app --reload
```

---

# 動作概要

```
client
  ↓ POST /search
server
  ↓ DuckDuckGo search
  ↓ fetch (httpx)
     ↓ bot / non-200 → cache → skip
     ↓ HTML ok → extract
     ↓ small → playwright escalation
  ↓ markdown convert
  ↓ response
```

---

# キャッシュ

以下がキャッシュされます:

* 429
* 503
* 403 / bot detection
* network error

保存先:

```
.negcache/
```

TTL 経過後は再アクセス可能になります。



server.pyでは、/searchエンドポイントが存在します。
queryで検索し、取得したlistに対して、各ページの内容をfetchしmarkdownのlistで返す実装です。

/listエンドポイントを追加してください。
/searchのうち、listを取得する機能のみのものを取り出したものです。
url, title, snippet
