"""Yahoo!ショッピング 商品検索API(v3) の薄いラッパー（公式API・1秒に1回まで）"""
import os, json, time, urllib.parse, urllib.request, urllib.error

URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
_last = [0.0]

def search(**params):
    app_id = os.environ.get("YAHOO_APP_ID", "")
    if not app_id:
        raise RuntimeError("YAHOO_APP_ID が設定されていません（GitHubのSecretsに登録してください）")
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    q = {"appid": app_id}
    q.update({k: ("true" if v is True else v) for k, v in params.items() if v not in (None, "")})
    try:
        with urllib.request.urlopen(f"{URL}?{urllib.parse.urlencode(q)}", timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200].replace("\n", " ")
        raise RuntimeError(f"HTTP {e.code} {e.reason} | {body}")
    finally:
        _last[0] = time.time()
    return data
