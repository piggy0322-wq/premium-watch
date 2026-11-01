"""プレミア化候補ウォッチャー（個人利用・1日1回実行）
Yahoo!ショッピングAPIで各ソフトの在庫を確認し、履歴から判定して ntfy に通知する。
"""
import csv, json, os, re, time, random, datetime, urllib.parse, urllib.request, html

# ===== 設定（ここだけ調整すればOK） =====
PAGE_URL = "https://www.saiyasune.com/J{jan}.html"   # 通知のリンク先（人が開く用）
NO_RESULT_DAYS = 3        # 「該当商品なし」が何日続いたら通知するか
SHOP_DROP_RATIO = 0.5     # 直近7日の最大ショップ数に対し、この割合以下で通知
PRICE_RISE_RATIO = 1.2    # 直近7日の最安値に対し、この倍率以上で通知
FAIL_ALERT_RATIO = 0.3    # 取得失敗がこの割合を超えたら「壊れた」通知
RENOTIFY_DAYS = 14        # 同じソフトの再通知を控える日数
# =======================================

TOPIC = os.environ.get("NTFY_TOPIC", "")
HIST = "history.json"
today = datetime.date.today().isoformat()

def check(jan):
    """Yahoo!ショッピングAPIで新品・中古の在庫状況を取得"""
    import yahoo
    new = yahoo.search(jan_code=jan, condition="new", in_stock=True, results=50).get("hits", [])
    used = yahoo.search(jan_code=jan, condition="used", in_stock=True, results=50).get("hits", [])
    np_ = [h["price"] for h in new if h.get("price")]
    up_ = [h["price"] for h in used if h.get("price")]
    sellers = {(h.get("seller") or {}).get("sellerId") or (h.get("seller") or {}).get("name") for h in new}
    return {"found": bool(new), "shops": len(sellers - {None}), "min_price": min(np_) if np_ else None,
            "used_min": min(up_) if up_ else None}

def judge(rows):
    """rows: 日付昇順の履歴。通知理由のリストを返す"""
    reasons, cur, past = [], rows[-1], rows[-8:-1]
    tail = rows[-NO_RESULT_DAYS:]
    if len(tail) == NO_RESULT_DAYS and all(not r["found"] for r in tail):
        reasons.append(f"該当商品なしが{NO_RESULT_DAYS}日連続")
    if cur["found"]:
        ps = [r["shops"] for r in past if r.get("shops")]
        if ps and cur.get("shops") and cur["shops"] <= max(ps) * SHOP_DROP_RATIO:
            reasons.append(f"ショップ数 {max(ps)}→{cur['shops']}に減少")
        pp = [r["min_price"] for r in past if r.get("min_price")]
        if pp and cur.get("min_price") and cur["min_price"] >= min(pp) * PRICE_RISE_RATIO:
            reasons.append(f"最安値 ¥{min(pp):,}→¥{cur['min_price']:,}に上昇")
    up = [r["used_min"] for r in past if r.get("used_min")]
    if up and cur.get("used_min") and cur["used_min"] >= min(up) * PRICE_RISE_RATIO:
        reasons.append(f"中古最安値 ¥{min(up):,}→¥{cur['used_min']:,}に上昇")
    return reasons

def notify(title, body, click=None):
    if not TOPIC:
        print("[通知スキップ]", title, body); return
    h = {"Title": urllib.parse.quote(title), "Priority": "default"}
    if click: h["Click"] = click
    req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=body.encode(), headers=h)
    urllib.request.urlopen(req, timeout=30)

def main():
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {}
    items = [r for r in csv.DictReader(l for l in open("watchlist.csv", encoding="utf-8") if not l.startswith("#")) if r.get("name") and r.get("jan")]
    fails, alerts = 0, []
    for it in items:
        name = it["name"].strip()
        url = PAGE_URL.format(jan=it["jan"].strip())
        try:
            rec = check(it["jan"].strip()); rec["date"] = today
        except Exception as e:
            fails += 1; print("失敗", name, e); continue
        h = hist.setdefault(name, {"url": url, "rows": [], "last_notified": ""})
        h["url"] = url
        h["rows"] = [r for r in h["rows"] if r["date"] != today][-60:] + [rec]
        reasons = judge(h["rows"])
        ln = h.get("last_notified")
        recent = ln and (datetime.date.today() - datetime.date.fromisoformat(ln)).days < RENOTIFY_DAYS
        if reasons and not recent:
            notify(f"プレミア化候補: {name}", " / ".join(reasons), url)
            h["last_notified"] = today
        h["reasons"] = reasons
    if items and fails / len(items) > FAIL_ALERT_RATIO:
        notify("ウォッチャー異常", f"{len(items)}本中{fails}本で取得失敗。サイト仕様変更かブロックの可能性")
    json.dump(hist, open(HIST, "w"), ensure_ascii=False, indent=1)
    write_page(hist)

def write_page(hist):
    os.makedirs("docs", exist_ok=True)
    rows = ""
    for n, h in sorted(hist.items(), key=lambda kv: -len(kv[1].get("reasons", []))):
        c = h["rows"][-1]
        rows += (f"<tr><td><a href='{html.escape(h['url'])}'>{html.escape(n)}</a></td>"
                 f"<td>{'あり' if c['found'] else '該当なし'}</td><td>{c.get('shops') or '-'}</td>"
                 f"<td>{c.get('min_price') or '-'}</td><td>{html.escape(' / '.join(h.get('reasons', [])))}</td></tr>")
    open("docs/index.html", "w", encoding="utf-8").write(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>プレミア候補</title><h3>更新: {today}</h3><div style='overflow-x:auto'>"
        "<table border=1 cellpadding=4><tr><th>ソフト<th>状態<th>店数<th>最安<th>判定</tr>" + rows + "</table></div>")

if __name__ == "__main__":
    main()
