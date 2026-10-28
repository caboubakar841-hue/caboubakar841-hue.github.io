# PRONO70 V17 - Pronostics calcules (modele de Poisson) a partir des VRAIS resultats ESPN
# Aucun tirage aleatoire : tout decoule des buts marques/encaisses depuis LOOKBACK_DAYS jours.
import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

LOOKBACK_DAYS = 90    # historique utilise pour mesurer la force des equipes
MAX_BACKFILL_DAYS = 40  # jours d'historique recuperes par run (ESPN refuse les plages : 1 jour = 1 requete)
CACHE = "data/results.json"
MIN_GAMES = 3         # en dessous, l'equipe n'est pas pronostiquee (pas assez de donnees)
PRIOR_GAMES = 4       # lissage : peu de matchs => on reste proche de la moyenne de la ligue
MAX_GOALS = 8         # taille de la grille de scores (0..8)
MAX_MATCHES = 40
MIN_TICKET_PROB = 0.80  # seuil par selection pour entrer dans un ticket
TICKETS = "data/tickets.json"
BACKTEST_DAYS = 14    # jours passes pronostiques apres coup (sans tricher : modele entraine AVANT chaque jour)
HIST = "data/history.json"

# slug ESPN -> nom affiche. Ajoute ou retire des lignes librement.
LEAGUES = {
    "eng.1": "Premier League", "eng.2": "Championship", "eng.3": "League One", "eng.4": "League Two",
    "esp.1": "La Liga", "esp.2": "La Liga 2",
    "ita.1": "Serie A", "ita.2": "Serie B",
    "ger.1": "Bundesliga", "ger.2": "2. Bundesliga",
    "fra.1": "Ligue 1", "fra.2": "Ligue 2",
    "ned.1": "Eredivisie", "por.1": "Liga Portugal", "bel.1": "Pro League",
    "tur.1": "Super Lig", "sco.1": "Scottish Premiership",
    "usa.1": "MLS", "bra.1": "Brasileirao", "arg.1": "Liga Argentina", "mex.1": "Liga MX",
}

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
BAD_STATUS = ("POSTPONED", "CANCEL", "ABANDON", "FORFEIT", "SUSPEND")


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36", "Accept": "application/json"}
ERRORS = []


def fetch(slug, day):
    for _ in range(2):
        try:
            r = requests.get(BASE.format(slug=slug), params={"dates": f"{day:%Y%m%d}"}, headers=HEADERS, timeout=8)
            r.raise_for_status()
            return r.json().get("events", [])
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", "")
            ERRORS.append(f"{slug} {day} -> {type(e).__name__} {code} {str(e)[:120]}")
    return None


def parse_event(ev):
    try:
        comp = ev["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        st = ev["status"]["type"]
        if any(b in str(st.get("name", "")).upper() for b in BAD_STATUS):
            return None
        out = {
            "id": str(ev.get("id")), "detail": st.get("shortDetail") or "",
            "home": home["team"]["displayName"],
            "away": away["team"]["displayName"],
            "state": st.get("state"),
            "iso": ev.get("date", ""),
        }
        if out["state"] in ("in", "post"):
            if out["state"] == "post" and not st.get("completed"):
                return None
            out["gh"] = int(float(home["score"]))
            out["ga"] = int(float(away["score"]))
        return out
    except Exception:
        return None


def fit(results, iters=30):
    """results = [(home, away, buts_dom, buts_ext)] d'une meme ligue.
    Estime attaque/defense de chaque equipe en tenant compte du niveau des adversaires."""
    n = len(results)
    mu_h = sum(r[2] for r in results) / n
    mu_a = sum(r[3] for r in results) / n
    g = (mu_h + mu_a) / 2
    gf, gc, gp = defaultdict(float), defaultdict(float), defaultdict(int)
    for h, a, x, y in results:
        gf[h] += x; gc[h] += y; gp[h] += 1
        gf[a] += y; gc[a] += x; gp[a] += 1
    teams = list(gp)
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    prior = PRIOR_GAMES * g
    for _ in range(iters):
        ea, ed = defaultdict(float), defaultdict(float)
        for h, a, _, _ in results:
            ea[h] += mu_h * dfn[a]
            ea[a] += mu_a * dfn[h]
            ed[h] += mu_a * att[a]
            ed[a] += mu_h * att[h]
        att = {t: (gf[t] + prior) / (ea[t] + prior) for t in teams}
        dfn = {t: (gc[t] + prior) / (ed[t] + prior) for t in teams}
    return {"mu_h": mu_h, "mu_a": mu_a, "att": att, "def": dfn, "gp": gp}


def pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predict(model, home, away):
    lam_h = model["mu_h"] * model["att"][home] * model["def"][away]
    lam_a = model["mu_a"] * model["att"][away] * model["def"][home]
    grid = [[pmf(i, lam_h) * pmf(j, lam_a) for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    tot = sum(map(sum, grid))
    grid = [[p / tot for p in row] for row in grid]
    cells = [(i, j, grid[i][j]) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)]
    p_h = sum(p for i, j, p in cells if i > j)
    p_d = sum(p for i, j, p in cells if i == j)
    p_a = sum(p for i, j, p in cells if i < j)
    p_over = sum(p for i, j, p in cells if i + j >= 3)
    p_btts = sum(p for i, j, p in cells if i >= 1 and j >= 1)

    pick = max((p_h, "H"), (p_d, "D"), (p_a, "A"))[1]
    # match serre : pas de favori net -> on recommande Nul ou l'un des deux (double chance)
    tight = abs(p_h - p_a) < 0.12 and max(p_h, p_a) < 0.45
    dc = max((p_h + p_d, "1X"), (p_d + p_a, "X2")) if tight else \
        max((p_h + p_d, "1X"), (p_d + p_a, "X2"), (p_h + p_a, "12"))
    allowed = {"1X": {"H", "D"}, "X2": {"D", "A"}}[dc[1]] if tight else {pick}
    over_pick, btts_pick = p_over >= 0.5, p_btts >= 0.5
    res = lambda i, j: "H" if i > j else "A" if i < j else "D"
    over_f = lambda i, j: (i + j >= 3) == over_pick
    btts_f = lambda i, j: (i >= 1 and j >= 1) == btts_pick

    def best(*conds):
        c = [x for x in cells if res(x[0], x[1]) in allowed and all(f(x[0], x[1]) for f in conds)]
        return max(c, key=lambda x: x[2]) if c else None

    # le score affiche respecte le resultat, l'over/under ET le BTTS annonces (sinon on relache)
    si, sj, sp = best(over_f, btts_f) or best(btts_f) or best(over_f) or best()
    return dict(lam_h=lam_h, lam_a=lam_a, p_h=p_h, p_d=p_d, p_a=p_a, pick=pick,
                score=f"{si}-{sj}", score_p=sp, dc=dc, p_over=p_over, p_btts=p_btts, tight=tight)


def pct(p):
    return round(p * 100)


def build_card(league, home, away, iso, pr, gp_h, gp_a):
    victoire = {"H": f"Victoire {home}", "A": f"Victoire {away}", "D": "Match Nul"}[pr["pick"]]
    if pr.get("tight"):
        victoire = f"Serré : Nul ou {home if pr['dc'][1] == '1X' else away}"
    over = (f"Over 2.5 {pct(pr['p_over'])}%" if pr["p_over"] >= 0.5
            else f"Under 2.5 {pct(1 - pr['p_over'])}%")
    btts = (f"BTTS OUI {pct(pr['p_btts'])}%" if pr["p_btts"] >= 0.5
            else f"BTTS NON {pct(1 - pr['p_btts'])}%")
    return {
        "league": league, "home": home, "away": away, "status": "today",
        "conf": pct(pr["dc"][0]) if pr.get("tight") else pct(max(pr["p_h"], pr["p_d"], pr["p_a"])),
        "victoire": victoire,
        "score_exact": f"{pr['score']} ({pct(pr['score_p'])}%)",
        "double_chance": f"{pr['dc'][1]} {pct(pr['dc'][0])}%",
        "corner": "N/D",
        "over": over, "btts": btts,
        "analyse": (f"{iso[:10]} | Buts attendus {home} {pr['lam_h']:.1f} - {away} {pr['lam_a']:.1f} | "
                    f"1/N/2 : {pct(pr['p_h'])}/{pct(pr['p_d'])}/{pct(pr['p_a'])}% | "
                    f"base sur {gp_h} et {gp_a} matchs joues | modele Poisson, aucun aleatoire"),
        "_iso": iso,
    }


def result_of(gh, ga):
    return "H" if gh > ga else "A" if ga > gh else "D"


def evaluate(rec):
    gh, ga = rec["res"]
    pr, r = rec["pr"], result_of(gh, ga)
    return {
        "tight": bool(pr.get("tight")),
        "1x2": (r in {"1X": "HD", "X2": "DA"}.get(pr["dc"][1], "")) if pr.get("tight") else pr["pick"] == r,
        "dc": r in {"1X": "HD", "X2": "DA", "12": "HA"}[pr["dc"][1]],
        "over": (gh + ga >= 3) == (pr["p_over"] >= 0.5),
        "btts": (gh > 0 and ga > 0) == (pr["p_btts"] >= 0.5),
        "score": f"{gh}-{ga}" == pr["score"],
    }


def card_from(rec, status):
    c = build_card(rec["league"], rec["home"], rec["away"], rec["iso"], rec["pr"], rec["gp"][0], rec["gp"][1])
    c["status"] = status
    c.pop("_iso", None)
    if rec.get("res"):
        c["live_score"] = f"{rec['res'][0]}-{rec['res'][1]}"
        if status == "finished":
            ev = rec["eval"]
            c["minute"] = "FT"
            c["analyse"] = ("Resultat " + c["live_score"] + " | 1X2 " + ("OK" if ev["1x2"] else "RATE") +
                            " | DC " + ("OK" if ev["dc"] else "RATE") + " | O/U " + ("OK" if ev["over"] else "RATE") +
                            " | BTTS " + ("OK" if ev["btts"] else "RATE") + " | Score " +
                            ("OK" if ev["score"] else "RATE") + " | " + ("pronostic fige avant match" if rec["kind"] == "avant"
                                                                          else "calcule apres coup, sans voir le match"))
    return c


def best_pick(rec):
    """Selection la plus sure du match parmi double chance, over 1.5 et under 3.5."""
    pr, home, away = rec["pr"], rec["home"], rec["away"]
    lam = pr["lam_h"] + pr["lam_a"]
    opts = [
        (pr["p_h"] + pr["p_d"], "1X", f"Double chance 1X ({home} ou nul)"),
        (pr["p_d"] + pr["p_a"], "X2", f"Double chance X2 (nul ou {away})"),
        (pr["p_h"] + pr["p_a"], "12", "Double chance 12 (pas de nul)"),
        (1 - math.exp(-lam) * (1 + lam), "O15", "Over 1.5 buts"),
        (sum(pmf(k, lam) for k in range(4)), "U35", "Under 3.5 buts"),
    ]
    return max(opts)


def leg_ok(code, gh, ga):
    r = result_of(gh, ga)
    return {"1X": r in "HD", "X2": r in "DA", "12": r in "HA", "O15": gh + ga >= 2, "U35": gh + ga <= 3}[code]


def build_tickets(recs, day):
    legs = []
    for r in recs:
        prob, code, label = best_pick(r)
        if prob >= MIN_TICKET_PROB:          # jamais de selection sous le seuil, meme pour remplir
            legs.append({"id": r["id"], "match": f"{r['home']} vs {r['away']}", "league": r["league"], "time": r["iso"][11:16],
                         "pick": label, "code": code, "p": round(prob * 100)})
    legs.sort(key=lambda l: -l["p"])
    top5, next10 = legs[:5], legs[5:15]      # les 5 plus sures vont au ticket de 5, les 10 suivantes au ticket de 10
    mk = lambda name, ls, n: {"name": name, "target": n, "n": len(ls), "legs": ls,
                              "combined": round(100 * math.prod(l["p"] / 100 for l in ls)) if ls else None}
    return {"day": day, "eligible": len(legs), "tickets": [mk("Ticket 10 matchs", next10, 10), mk("Ticket 5 matchs", top5, 5)]}


def settle(entry, results):
    for t in entry["tickets"]:
        for l in t["legs"]:
            r = results.get(l["id"])
            l["ok"] = leg_ok(l["code"], r["gh"], r["ga"]) if r else None
            l["score"] = f"{r['gh']}-{r['ga']}" if r else None
        oks = [l["ok"] for l in t["legs"]]
        t["status"] = "perdu" if False in oks else "gagné" if oks and all(x is True for x in oks) else "en cours"


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    t = now.date()
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    cache.setdefault("days_done", [])
    cache.setdefault("results", {})
    done_days = set(cache["days_done"])
    all_days = [t + timedelta(days=2 - k) for k in range(LOOKBACK_DAYS + 3)]      # t+2 ... t-LOOKBACK
    fresh = [d for d in all_days if d >= t - timedelta(days=1)]                   # toujours rafraichis
    missing = [d for d in all_days if d < t - timedelta(days=1) and d.isoformat() not in done_days][:MAX_BACKFILL_DAYS]
    jobs = [(slug, d) for d in fresh + missing for slug in LEAGUES]
    with ThreadPoolExecutor(max_workers=10) as ex:
        fetched = list(ex.map(lambda j: (j[0], j[1], fetch(*j)), jobs))
    ok = sum(1 for _, _, ev in fetched if ev is not None)
    print(f"ESPN: {ok}/{len(jobs)} requetes OK ({len(fresh)} jours frais, {len(missing)} jours d'historique)")
    for err in ERRORS[:5]:
        print("ERREUR ESPN:", err)
    if ok == 0:
        raise SystemExit("ESPN injoignable : on garde l'ancien matches.json")

    good_slugs = {slug for slug, _, ev in fetched if ev is not None}   # un slug invalide est ignore
    failed_days, fresh_events = set(), []
    for slug, d, evs in fetched:
        if evs is None:
            if slug in good_slugs:
                failed_days.add(d)
            continue
        for ev in evs:
            p = parse_event(ev)
            if not p:
                continue
            if p["state"] == "post" and "gh" in p:
                cache["results"][p["id"]] = {"slug": slug, "id": p["id"], "home": p["home"], "away": p["away"],
                                             "iso": p["iso"], "gh": p["gh"], "ga": p["ga"]}
            elif p["state"] in ("pre", "in"):
                fresh_events.append((slug, p))
    for d in missing:
        if d not in failed_days:
            done_days.add(d.isoformat())
    oldest = (t - timedelta(days=LOOKBACK_DAYS + 5)).isoformat()
    cache["days_done"] = sorted(x for x in done_days if x >= oldest)
    cache["results"] = {k: v for k, v in cache["results"].items() if v["iso"][:10] >= oldest}

    results, events, seen = defaultdict(list), [], set()
    for r in cache["results"].values():
        results[r["slug"]].append((r["home"], r["away"], r["gh"], r["ga"], r["iso"][:10]))
        events.append((r["slug"], {"id": r["id"], "home": r["home"], "away": r["away"], "state": "post",
                                   "iso": r["iso"], "detail": "FT", "gh": r["gh"], "ga": r["ga"]}))
    for slug, p in fresh_events:
        if (slug, p["id"]) not in seen:
            seen.add((slug, p["id"]))
            events.append((slug, p))
    print(f"{sum(map(len, results.values()))} resultats, {len(events)} matchs au total")

    try:
        h = json.load(open(HIST, encoding="utf-8"))
        hist = h["records"] if h.get("v") == 18 else {}   # logique changee : on repart a zero
    except Exception:
        hist = {}
    for k, r in hist.items():
        r.setdefault("id", k)                # anciens enregistrements sans id
    mcache = {}

    def model_before(slug, day):
        if (slug, day) not in mcache:
            train = [r[:4] for r in results[slug] if r[4] < day]
            mcache[(slug, day)] = fit(train) if len(train) >= 10 else None
        return mcache[(slug, day)]

    limit = (t - timedelta(days=BACKTEST_DAYS)).isoformat()
    live, upcoming = [], defaultdict(list)
    for slug, p in events:
        day = p["iso"][:10]
        rec = hist.get(p["id"])
        if p["state"] == "post" and day < limit and not rec:
            continue
        if p["state"] in ("pre", "in") and day < (t - timedelta(days=1)).isoformat():
            continue
        if not rec:
            m = model_before(slug, min(day, today))
            if not m or m["gp"].get(p["home"], 0) < MIN_GAMES or m["gp"].get(p["away"], 0) < MIN_GAMES:
                continue
            pr = predict(m, p["home"], p["away"])
            rec = hist[p["id"]] = {"id": p["id"], "slug": slug, "league": LEAGUES[slug], "home": p["home"], "away": p["away"],
                                   "iso": p["iso"], "pr": pr, "gp": [m["gp"][p["home"]], m["gp"][p["away"]]],
                                   "kind": "avant" if p["state"] == "pre" else "retro", "res": None}
        if p["state"] == "post" and "gh" in p and not rec.get("res"):
            rec["res"] = [p["gh"], p["ga"]]
            rec["eval"] = evaluate(rec)
        if p["state"] == "in":
            c = card_from(rec, "live")
            c["live_score"], c["minute"] = f"{p['gh']}-{p['ga']}", p["detail"]
            live.append(c)
        elif p["state"] == "pre" and day >= today:
            upcoming[day].append(rec)

    today_cards, day_recs = [], []
    if upcoming:
        day_recs = sorted(upcoming[sorted(upcoming)[0]], key=lambda r: r["iso"])
        today_cards = [card_from(rec, "today") for rec in day_recs]
    done = sorted((r for r in hist.values() if r.get("res")), key=lambda r: r["iso"], reverse=True)
    stats = {"n": len(done), "n_avant": sum(1 for r in done if r["kind"] == "avant")}
    if done:
        rate = lambda rs, k: round(100 * sum(r["eval"][k] for r in rs) / len(rs)) if rs else None
        fav = [r for r in done if not r["eval"].get("tight")]
        tig = [r for r in done if r["eval"].get("tight")]
        for k in ("dc", "over", "btts", "score"):
            stats[k] = rate(done, k)
        stats.update({"1x2": rate(fav, "1x2"), "n_fav": len(fav), "serre": rate(tig, "1x2"), "n_serre": len(tig)})
        stats["base_dom"] = round(100 * sum(1 for r in done if r["res"][0] > r["res"][1]) / len(done))
    fin_cards = [card_from(r, "finished") for r in done[:MAX_MATCHES]]

    cards = live + today_cards[:MAX_MATCHES] + fin_cards
    if not live and not today_cards:
        cards.insert(0, {"league": "Info", "home": "Aucun match", "away": "pronostiquable", "status": "today", "conf": 0,
                         "victoire": "Aucun pronostic fiable", "score_exact": "-", "double_chance": "-", "corner": "-",
                         "over": "-", "btts": "-",
                         "analyse": f"Aucun match a venir le {today} | ESPN: {ok}/{len(jobs)} requetes OK | {len(events)} matchs lus | historique en cours de remplissage"})
    keep = sorted(hist.items(), key=lambda kv: kv[1]["iso"], reverse=True)[:600]
    os.makedirs("data", exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump({"v": 18, "records": dict(keep)}, f, ensure_ascii=False)
    try:
        tk = json.load(open(TICKETS, encoding="utf-8"))
    except Exception:
        tk = {}
    tk.setdefault("days", {})
    if day_recs:
        dkey = sorted(upcoming)[0]
        if dkey not in tk["days"]:           # fige : les tickets d'un jour ne changent plus ensuite
            tk["days"][dkey] = build_tickets(day_recs[:MAX_MATCHES], dkey)
    for entry in tk["days"].values():
        settle(entry, cache["results"])
    tk["days"] = dict(sorted(tk["days"].items(), reverse=True)[:14])
    with open(TICKETS, "w", encoding="utf-8") as f:
        json.dump(tk, f, ensure_ascii=False)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    out = {"date": now.strftime("%Y-%m-%d %H:%M") + " UTC", "version": "V17", "stats": stats, "tickets": [tk["days"][d] for d in sorted(tk["days"], reverse=True)], "matches": cards}
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"FINAL: {len(live)} live, {len(today_cards)} a venir, {len(fin_cards)} termines | stats {stats}")


if __name__ == "__main__":
    main()
