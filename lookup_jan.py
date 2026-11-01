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
    return re.sub(r"[\s\-‐ー~〜～:：!！?？・'’\"“”\[\]【】()（）/／+＋]", "", s)

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
    return re.sub(r"\s+", " ", s).strip()

def pick(title, platform, hits):
    """hitsから候補JANを集計。戻り値: [(件数, JAN, 代表名)] 多い順"""
    want = "PS4" if platform == "PS4" else "SWITCH"
    key = norm(plain_title(title))
    cnt, names = collections.Counter(), {}
    for h in hits:
        jan = str(h.get("janCode") or "")
        name = h.get("name") or ""
        if not re.fullmatch(r"\d{13}", jan) or jan.startswith(("978", "979")): continue
        if any(w.lower() in name.lower() for w in EXCLUDE_WORDS): continue
        tags = plat_tags(name)
        if want not in tags or tags - {want}: continue
        if key not in norm(name): continue
        cnt[jan] += 1; names.setdefault(jan, name)
    return [(c, j, names[j]) for j, c in cnt.most_common()]

def resolve(title, platform, search=yahoo.search):
    plat = "PS4" if platform == "PS4" else "Switch"
    got = []
    for q in dict.fromkeys([f"{title} {plat}", f"{plain_title(title)} {plat}"]):
        data = search(query=q, results=50)
        got = pick(title, platform, data.get("hits", []))
        if got: break
    if not got:
        return "review", "", "候補なし"
    if len(got) == 1 or got[0][0] >= 2 * got[1][0]:
        return "ok", got[0][1], got[0][2][:60]
    return "review", "", "曖昧: " + " | ".join(f"{j}:{n[:40]}" for _, j, n in got[:3])

def main():
    titles = list(csv.DictReader(open("titles.csv", encoding="utf-8-sig")))
    done = {}
    if os.path.exists("jan_map.csv"):
        done = {(r["name"], r["platform"]): r for r in csv.DictReader(open("jan_map.csv", encoding="utf-8-sig"))}
    limit, n, streak = int(os.environ.get("LIMIT", 300)), 0, 0
    for t in titles:
        key = (t["name"], t["platform"])
        if key in done and done[key]["status"] in ("ok", "review"): continue
        if n >= limit: break
        n += 1
        try: st, jan, note = resolve(t["name"], t["platform"])
        except Exception as e: st, jan, note = "error", "", str(e)[:300]
        done[key] = {"name": t["name"], "platform": t["platform"], "jan": jan, "status": st, "note": note}
        print(st, t["name"], jan, note[:150] if st != "ok" else "")
        streak = streak + 1 if st == "error" else 0
        if streak >= 5:
            print("連続5回エラーのため中断します。上のエラー内容を確認してください。"); break
    rows = list(done.values())
    with open("jan_map.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["name", "platform", "jan", "status", "note"]); w.writeheader(); w.writerows(rows)
    with open("watchlist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name", "jan"])
        w.writerows((r["name"], r["jan"]) for r in rows if r["status"] == "ok")
    with open("review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["name", "platform", "status", "note"])
        w.writerows((r["name"], r["platform"], r["status"], r["note"]) for r in rows if r["status"] != "ok")
    print(f"確定 {sum(r['status']=='ok' for r in rows)} / 要確認 {sum(r['status']=='review' for r in rows)} "
          f"/ エラー {sum(r['status']=='error' for r in rows)} / 未処理 {len(titles)-len(rows)}")

if __name__ == "__main__":
    main()
