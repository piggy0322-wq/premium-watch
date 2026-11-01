"""ソフト名 → JANコード の自動検索（初回と新規追加分だけ実行）
titles.csv を読み、最安値.comで検索して jan_map.csv に保存、確定分を watchlist.csv に出力。
確定できないものは review.csv に候補つきで出力（人が見て JAN を埋める）。
環境変数 LIMIT で1回の処理本数を制限（既定 250）。
"""
import csv, os, re, time, random, unicodedata, urllib.parse, urllib.request, difflib
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.saiyasune.com/I1W{q}.html"   # 検索結果ページ（実ページのog:urlから確認済み）
UA = "Mozilla/5.0 (personal-use price watcher; one-time lookup)"
ACCEPT = 0.80
EXCLUDE_WORDS = ["サウンドトラック", "サントラ", "DVD", "Blu-ray", "ブルーレイ", "CD", "攻略", "ガイド",
                 "画集", "設定資料", "Tシャツ", "フィギュア", "アルバム", "コミック", "小説", "ポスター"]
# 機種タグ（商品名・パンくずに出る表記）
PLAT = {"PS5": ["ps5", "プレイステーション5"], "PS4": ["ps4", "プレイステーション4"],
        "PS3": ["ps3", "プレイステーション3"], "VITA": ["psv", "vita", "ヴィータ"], "PSP": ["psp"],
        "3DS": ["3ds"], "NDS": ["nds"], "WII": ["wii"], "XBOX": ["xbox"],
        "SWITCH2": ["switch2", "switch 2", "スイッチ2"], "SWITCH": ["switch", "スイッチ"]}

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\-‐ー~〜～:：!！?？・'’\"“”\[\]【】()（）]", "", s)

def plat_tags(text):
    t = unicodedata.normalize("NFKC", text).lower()
    found = set()
    for p in ("SWITCH2", "PS5", "PS4", "PS3", "VITA", "PSP", "3DS", "NDS", "WII", "XBOX"):
        if any(k in t for k in PLAT[p]): found.add(p)
    t2 = t
    for k in PLAT["SWITCH2"]: t2 = t2.replace(k, "")
    if any(k in t2 for k in PLAT["SWITCH"]): found.add("SWITCH")
    return found

def parse_candidates(raw):
    """検索結果ページ → [(商品名, JAN)]（重複・本・書籍は除外）"""
    soup = BeautifulSoup(raw, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/J(\d{13})\.html")):
        jan = re.search(r"J(\d{13})\.html", a["href"]).group(1)
        txt = a.get_text(" ", strip=True)
        if "価格を比較する" not in txt or jan in seen or jan.startswith(("978", "979")):
            continue
        name = re.sub(r"\s*価格を比較する.*$", "", txt).strip()
        seen.add(jan); out.append((name, jan))
    return out

def plain_title(name):
    s = re.sub(r"[（(][^）)]*[）)]|【[^】]*】|[~〜～].*?[~〜～]", " ", name)
    return re.sub(r"\s+", " ", s).strip()

def rank(title, platform, cands):
    """条件に合う候補を類似度順に返す [(score, name, jan)]"""
    want = "PS4" if platform == "PS4" else "SWITCH"
    res = []
    for name, jan in cands:
        if any(w.lower() in name.lower() for w in EXCLUDE_WORDS):
            continue
        tags = plat_tags(name)
        if tags and want not in tags:
            continue                       # 名前に他機種の表記がある
        a, b = norm(plain_title(title)), norm(re.sub(r"(?i)\b(ps4|switch)\b", "", name))
        sc = difflib.SequenceMatcher(None, a, b).ratio()
        if sc >= ACCEPT:
            res.append((sc, name, jan))
    return sorted(res, reverse=True)

def verify_platform(raw, platform):
    """商品ページのパンくず(「ホーム > … > JANコード」)から機種を確認。True/False/None(不明)"""
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style"]): t.decompose()
    text = soup.get_text(" ", strip=True)
    m = re.search(r"ホーム\s*>(.*?)JANコード", text)
    if not m: return None
    tags = plat_tags(m.group(1))
    want = "PS4" if platform == "PS4" else "SWITCH"
    if not tags: return None
    return want in tags and len(tags - {want}) == 0

def resolve(title, platform, get=fetch, pause=lambda: time.sleep(random.uniform(3, 6))):
    """戻り値: (status, jan, note)"""
    queries = [title] + ([plain_title(title)] if plain_title(title) != title else [])
    allc = []
    for q in queries:
        allc = parse_candidates(get(SEARCH_URL.format(q=urllib.parse.quote(q)))); pause()
        ranked = rank(title, platform, allc)
        if ranked: break
    if not ranked:
        return "review", "", "候補なし: " + " | ".join(f"{n}:{j}" for n, j in allc[:5])
    ok = []
    for sc, name, jan in ranked[:3]:
        v = verify_platform(get(f"https://www.saiyasune.com/J{jan}.html"), platform); pause()
        if v is True or (v is None and sc >= 0.95): ok.append((sc, name, jan))
    if len(ok) == 1: return "ok", ok[0][2], ok[0][1]
    if len(ok) > 1 and ok[0][0] - ok[1][0] >= 0.1: return "ok", ok[0][2], ok[0][1]
    return "review", "", "曖昧: " + " | ".join(f"{n}:{j}" for _, n, j in (ok or ranked)[:3])

def main():
    titles = list(csv.DictReader(open("titles.csv", encoding="utf-8-sig")))
    done = {}
    if os.path.exists("jan_map.csv"):
        done = {(r["name"], r["platform"]): r for r in csv.DictReader(open("jan_map.csv", encoding="utf-8-sig"))}
    limit, n = int(os.environ.get("LIMIT", 250)), 0
    for t in titles:
        key = (t["name"], t["platform"])
        if key in done and done[key]["status"] == "ok": continue
        if n >= limit: break
        n += 1
        try: st, jan, note = resolve(t["name"], t["platform"])
        except Exception as e: st, jan, note = "error", "", str(e)[:100]; time.sleep(5)
        done[key] = {"name": t["name"], "platform": t["platform"], "jan": jan, "status": st, "note": note}
        print(st, t["name"], jan)
    rows = list(done.values())
    with open("jan_map.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["name", "platform", "jan", "status", "note"]); w.writeheader(); w.writerows(rows)
    with open("watchlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name", "jan"])
        w.writerows((r["name"], r["jan"]) for r in rows if r["status"] == "ok")
    with open("review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["name", "platform", "status", "note"])
        w.writerows((r["name"], r["platform"], r["status"], r["note"]) for r in rows if r["status"] != "ok")
    print(f"確定 {sum(r['status']=='ok' for r in rows)} / 要確認 {sum(r['status']!='ok' for r in rows)} / 未処理 {len(titles)-len(rows)}")

if __name__ == "__main__":
    main()
