"""ソフト名 → JANコード（Yahoo!ショッピングAPIで検索。初回と新規追加分だけ実行）
titles.csv → jan_map.csv / watchlist.csv（確定分） / review.csv（要確認）
環境変数: YAHOO_APP_ID（必須）, LIMIT（1回の処理本数、既定300）
"""
import csv, os, re, unicodedata, collections
import yahoo

ACCEPT = 0.9
EXCLUDE_WORDS = ["サウンドトラック", "サントラ", "DVD", "Blu-ray", "ブルーレイ", "CD", "攻略", "ガイド", "画集",
                 "設定資料", "Tシャツ", "フィギュア", "アルバム", "コミック", "小説", "ポスター",
                 "ダウンロード", "DLC", "ダウンロードコード", "ケース", "カバー", "フィルム"]
PLAT = {"PS5": ["ps5", "プレイステーション5"], "PS4": ["ps4", "プレイステーション4"], "PS3": ["ps3"],
        "VITA": ["psv", "vita"], "PSP": ["psp"], "3DS": ["3ds"], "NDS": ["nds"], "WII": ["wii"],
        "XBOX": ["xbox"], "SWITCH2": ["switch2", "switch 2", "スイッチ2"], "SWITCH": ["switch", "スイッチ"]}

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\-‐ー–—−―~〜～:：!！?？・'’\"“”\[\]【】()（）/／+＋.,、。]", "", s)

def spaced(s):
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]+", " ", s).strip()

def plat_tags(text):
    t = unicodedata.normalize("NFKC", text).lower()
    found = {p for p in ("SWITCH2", "PS5", "PS4", "PS3", "VITA", "PSP", "3DS", "NDS", "WII", "XBOX")
             if any(k in t for k in PLAT[p])}
    t2 = t
    for k in PLAT["SWITCH2"]: t2 = t2.replace(k, "")
    if any(k in t2 for k in PLAT["SWITCH"]): found.add("SWITCH")
    return found

def plain_title(name):
    s = re.sub(r"[（(][^）)]*[）)]|【[^】]*】|[~〜～].*?[~〜～]", " ", name)
    s = re.sub(r"(?i)for\s*nintendo\s*switch|\s+for\s+switch\s*$", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def matches(title, platform, name):
    """この商品名は、そのソフト(機種)の商品か？"""
    if any(w.lower() in name.lower() for w in EXCLUDE_WORDS): return False
    want = "PS4" if platform == "PS4" else "SWITCH"
    tags = plat_tags(name)
    if want not in tags or tags - {want}: return False
    pt = plain_title(title)
    key = norm(pt)
    if len(key) < 2: return False
    ks = spaced(pt)
    if re.fullmatch(r"[0-9a-z ]+", ks):            # 英数字だけの題名は単語の境界を見る
        ns = re.sub(r"(?i)nintendo\s*switch|switch|ps4|playstation\s*4", " ", spaced(name))
        ns = re.sub(r"\s+", " ", ns)
        m = re.search(r"(?<![0-9a-z])" + re.escape(ks) + r"(?![0-9a-z])", ns)
        if not m: return False
        if " " not in ks:                          # 1単語の英語題名は、直前に別の英単語があれば別作品とみなす
            before = ns[:m.start()].split()
            if before and re.fullmatch(r"[0-9a-z]+", before[-1]): return False
        return True
    nm = norm(name)
    i = nm.find(key)
    if i < 0: return False
    nxt = nm[i + len(key):i + len(key) + 1]
    return not (nxt.isdigit() and not key[-1].isdigit())   # 「アイキス2」などの続編を除く

def pick(title, platform, hits):
    """戻り値: [(件数, JAN, 代表名)] 多い順"""
    cnt, names = collections.Counter(), {}
    for h in hits:
        jan = str(h.get("janCode") or ""); name = h.get("name") or ""
        if not re.fullmatch(r"\d{13}", jan) or jan.startswith(("978", "979")): continue
        if not matches(title, platform, name): continue
        cnt[jan] += 1; names.setdefault(jan, name)
    return [(c, j, names[j]) for j, c in cnt.most_common()]

def resolve(title, platform, search=yahoo.search):
    """戻り値: (status, jan, note)  status: ok / multi(別版あり,JANを;区切り) / kw(JAN不明→キーワード監視) / review"""
    plat = "PS4" if platform == "PS4" else "Switch"
    got = []
    for q in dict.fromkeys([f"{title} {plat}", f"{plain_title(title)} {plat}"]):
        got = pick(title, platform, search(query=q, results=50).get("hits", []))
        if got: break
    if not got:
        return "kw", "", "Yahoo!に該当商品なし（キーワード監視）"
    if len(got) == 1: return "ok", got[0][1], got[0][2][:60]
    if len(got) <= 4: return "multi", ";".join(j for _, j, _ in got), " | ".join(n[:30] for _, _, n in got)
    return "review", "", "候補が多すぎる: " + " | ".join(f"{j}:{n[:30]}" for _, j, n in got[:4])

VER = "2"
def main():
    titles = list(csv.DictReader(open("titles.csv", encoding="utf-8-sig")))
    done = {}
    if os.path.exists("jan_map.csv"):
        done = {(r["name"], r["platform"]): r for r in csv.DictReader(open("jan_map.csv", encoding="utf-8-sig"))}
    limit, n, streak = int(os.environ.get("LIMIT", 300)), 0, 0
    for t in titles:
        key = (t["name"], t["platform"])
        r0 = done.get(key)
        if r0 and (r0["status"] in ("ok", "multi", "kw") or (r0["status"] == "review" and r0.get("ver") == VER)): continue
        if n >= limit: break
        n += 1
        try: st, jan, note = resolve(t["name"], t["platform"])
        except Exception as e: st, jan, note = "error", "", str(e)[:300]
        done[key] = {"name": t["name"], "platform": t["platform"], "jan": jan, "status": st, "note": note, "ver": VER}
        print(st, t["name"], jan, note[:150] if st != "ok" else "")
        streak = streak + 1 if st == "error" else 0
        if streak >= 5:
            print("連続5回エラーのため中断します。上のエラー内容を確認してください。"); break
    rows = list(done.values())
    with open("jan_map.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["name", "platform", "jan", "status", "note", "ver"]); w.writeheader(); w.writerows(rows)
    with open("watchlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name", "platform", "jan", "query"])
        seen = set()
        for r in rows:
            if r["status"] in ("ok", "multi"):
                for k, j in enumerate(r["jan"].split(";")):
                    if j in seen: continue          # 同じJANの重複登録を避ける
                    seen.add(j)
                    w.writerow([r["name"] + (f" [版{k+1}]" if ";" in r["jan"] else ""), r["platform"], j, ""])
            elif r["status"] == "kw":
                w.writerow([r["name"], r["platform"], "", plain_title(r["name"])])
    with open("review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["name", "platform", "status", "note"])
        w.writerows((r["name"], r["platform"], r["status"], r["note"]) for r in rows if r["status"] in ("review", "error"))
    print(f"確定 {sum(r['status'] in ('ok','multi') for r in rows)} / キーワード監視 {sum(r['status']=='kw' for r in rows)} / 要確認 {sum(r['status']=='review' for r in rows)} "
          f"/ エラー {sum(r['status']=='error' for r in rows)} / 未処理 {len(titles)-len(rows)}")

if __name__ == "__main__":
    main()
