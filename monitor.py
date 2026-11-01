"""プレミア化候補ウォッチャー（個人利用・1日1回実行）
最安値ドットコムの各ソフトを確認し、履歴から判定して ntfy に通知する。
※ サイト構造は未検証。初回は debug_parse.py（README参照）で必ず確認すること。
"""
import csv, json, os, re, time, random, datetime, urllib.parse, urllib.request, html

# ===== 設定（ここだけ調整すればOK） =====
PAGE_URL = "https://www.saiyasune.com/J{jan}.html"   # JANコードからURLを作る（実ページで確認済みの形式）
PRICE_RE = re.compile(r"[¥￥]\s*([\d,]+)")
NO_RESULT_DAYS = 3        # 「該当商品なし」が何日続いたら通知するか
SHOP_DROP_RATIO = 0.5     # 直近7日の最大ショップ数に対し、この割合以下で通知
PRICE_RISE_RATIO = 1.2    # 直近7日の最安値に対し、この倍率以上で通知
FAIL_ALERT_RATIO = 0.3    # 取得失敗がこの割合を超えたら「壊れた」通知
RENOTIFY_DAYS = 14        # 同じソフトの再通知を控える日数
# =======================================

TOPIC = os.environ.get("NTFY_TOPIC", "")
UA = "Mozilla/5.0 (personal-use price watcher; 1 access/day)"
HIST = "history.json"
today = datetime.date.today().isoformat()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def to_text(raw):
    """HTMLを表示される文字列に変換（タグ・script・styleを除去）"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return soup.get_text(" ", strip=True)

def parse(raw):
    """最安値.comのJANページから読み取る。
    found=新品の最安値あり / shops=新品在庫のある主要モール数(Amazon,楽天,Yahoo,Qoo10) / used_min=中古最安値
    ページ形式が想定と違う(ブロック画面など)場合は例外にして、誤判定を防ぐ。"""
    text = to_text(raw)
    if "JANコード価格比較" not in text or "大手通販モールの最安値" not in text:
        raise ValueError("想定外のページ（ブロックまたは仕様変更）")
    head, rest = text.split("大手通販モールの最安値", 1)
    seg = head.split("最安値：")[-1]          # 「最安値：」から「大手通販モール…」まで
    if "該当商品なし" in seg:
        new_min = None
    else:
        pm = PRICE_RE.search(seg)
        if not pm:
            raise ValueError("新品最安値の価格が読み取れない")
        new_min = int(pm.group(1).replace(",", ""))
    mall, _, used_part = rest.partition("中古品最安値")
    shops = 0 if "満たす商品はありませんでした" in mall else 1   # Amazon
    for name in ("楽天市場", "Yahoo!ショッピング", "Qoo10"):
        mm = re.search(re.escape(name) + r"\s*(該当商品なし|[¥￥])", mall)
        if mm and mm.group(1) != "該当商品なし":
            shops += 1
    up = PRICE_RE.search(used_part.split("オークション")[0])
    return {"found": new_min is not None, "shops": shops, "min_price": new_min,
            "used_min": int(up.group(1).replace(",", "")) if up else None}

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
    items = [r for r in csv.DictReader(l for l in open("watchlist.csv", encoding="utf-8") if not l.startswith("#")) if r.get("name") and (r.get("jan") or r.get("url"))]
    fails, alerts = 0, []
    for it in items:
        name = it["name"].strip()
        url = (it.get("url") or "").strip() or PAGE_URL.format(jan=it["jan"].strip())
        try:
            rec = parse(fetch(url)); rec["date"] = today
        except Exception as e:
            fails += 1; print("失敗", name, e); time.sleep(random.uniform(3, 6)); continue
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
        time.sleep(random.uniform(3, 6))   # 相手サイトへの配慮
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
