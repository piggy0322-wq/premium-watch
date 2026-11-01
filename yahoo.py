"""Yahoo!ショッピング 商品検索API(v3) の薄いラッパー（公式API）
公式の目安は1クエリ/秒。制限の条件は非公開のため、間隔を広げ、429なら待って再試行する。
"""
import os, json, time, urllib.parse, urllib.request, urllib.error

URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
MIN_INTERVAL = float(os.environ.get("MIN_INTERVAL", "3.0"))   # 秒
BACKOFF = [60, 120, 240]                                       # 429のときの待ち時間(秒)
_last = [0.0]

def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def search(**params):
    app_id = os.environ.get("YAHOO_APP_ID", "")
    if not app_id:
        raise RuntimeError("YAHOO_APP_ID が設定されていません（GitHubのSecretsに登録してください）")
    q = {"appid": app_id}
    q.update({k: ("true" if v is True else v) for k, v in params.items() if v not in (None, "")})
    url = f"{URL}?{urllib.parse.urlencode(q)}"
    for attempt in range(len(BACKOFF) + 1):
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            return _get(url)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200].replace("\n", " ")
            if e.code in (429, 500, 503) and attempt < len(BACKOFF):
                print(f"  (HTTP {e.code}: {BACKOFF[attempt]}秒待って再試行 {attempt + 1}/{len(BACKOFF)})", flush=True)
                time.sleep(BACKOFF[attempt])
                continue
            raise RuntimeError(f"HTTP {e.code} {e.reason} | {body}")
        finally:
            _last[0] = time.time()
