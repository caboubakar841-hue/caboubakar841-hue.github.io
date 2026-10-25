# PRONO70 V17 - Pronostics calcules (modele de Poisson) a partir des VRAIS resultats ESPN
# Aucun tirage aleatoire : tout decoule des buts marques/encaisses depuis LOOKBACK_DAYS jours.
import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

LOOKBACK_DAYS = 120   # historique utilise pour mesurer la force des equipes
CHUNK_DAYS = 30       # ESPN est interroge par tranches de 30 jours
MIN_GAMES = 3         # en dessous, l'equipe n'est pas pronostiquee (pas assez de donnees)
PRIOR_GAMES = 4       # lissage : peu de matchs => on reste proche de la moyenne de la ligue
MAX_GOALS = 8         # taille de la grille de scores (0..8)
MAX_MATCHES = 40
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


def fetch(slug, start, end):
    params = {"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": 1000}
    for _ in range(2):
        try:
            r = requests.get(BASE.format(slug=slug), params=params, timeout=8)
            r.raise_for_status()
            return r.json().get("events", [])
        except Exception:
            continue
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
    # score le plus probable PARMI ceux qui respectent le resultat pronostique (coherence)
    ok = {"H": lambda i, j: i > j, "D": lambda i, j: i == j, "A": lambda i, j: i < j}[pick]
    si, sj, sp = max(((i, j, p) for i, j, p in cells if ok(i, j)), key=lambda c: c[2])
    dc = max((p_h + p_d, "1X"), (p_d + p_a, "X2"), (p_h + p_a, "12"))
    return dict(lam_h=lam_h, lam_a=lam_a, p_h=p_h, p_d=p_d, p_a=p_a, pick=pick,
                score=f"{si}-{sj}", score_p=sp, dc=dc, p_over=p_over, p_btts=p_btts)


def pct(p):
    return round(p * 100)


def build_card(league, home, away, iso, pr, gp_h, gp_a):
    victoire = {"H": f"Victoire {home}", "A": f"Victoire {away}", "D": "Match Nul"}[pr["pick"]]
    over = (f"Over 2.5 {pct(pr['p_over'])}%" if pr["p_over"] >= 0.5
            else f"Under 2.5 {pct(1 - pr['p_over'])}%")
    btts = (f"BTTS OUI {pct(pr['p_btts'])}%" if pr["p_btts"] >= 0.5
            else f"BTTS NON {pct(1 - pr['p_btts'])}%")
    return {
        "league": league, "home": home, "away": away, "status": "today",
        "conf": pct(max(pr["p_h"], pr["p_d"], pr["p_a"])),
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
        "1x2": pr["pick"] == r,
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


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    t = now.date()
    start, end = t - timedelta(days=LOOKBACK_DAYS), t + timedelta(days=2)
    windows, d = [], start
    while d <= end:
        e = min(d + timedelta(days=CHUNK_DAYS - 1), end)
        windows.append((d, e))
        d = e + timedelta(days=1)
    jobs = [(slug, s, e) for slug in LEAGUES for s, e in windows]
    with ThreadPoolExecutor(max_workers=10) as ex:
        fetched = list(ex.map(lambda j: (j[0], fetch(*j)), jobs))
    ok = sum(1 for _, ev in fetched if ev is not None)
    print(f"ESPN: {ok}/{len(jobs)} requetes OK")
    if ok == 0:
        raise SystemExit("ESPN injoignable : on garde l'ancien matches.json")

    results, events, seen = defaultdict(list), [], set()
    for slug, evs in fetched:
        for ev in evs or []:
            p = parse_event(ev)
            key = (slug, p["id"]) if p else None
            if not p or key in seen:
                continue
            seen.add(key)
            events.append((slug, p))
            if p["state"] == "post" and "gh" in p:
                results[slug].append((p["home"], p["away"], p["gh"], p["ga"], p["iso"][:10]))
    print(f"{sum(map(len, results.values()))} resultats, {len(events)} matchs au total")

    try:
        hist = json.load(open(HIST, encoding="utf-8"))["records"]
    except Exception:
        hist = {}
    cache = {}

    def model_before(slug, day):
        if (slug, day) not in cache:
            train = [r[:4] for r in results[slug] if r[4] < day]
            cache[(slug, day)] = fit(train) if len(train) >= 10 else None
        return cache[(slug, day)]

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
            rec = hist[p["id"]] = {"slug": slug, "league": LEAGUES[slug], "home": p["home"], "away": p["away"],
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

    today_cards = []
    if upcoming:
        for rec in sorted(upcoming[sorted(upcoming)[0]], key=lambda r: r["iso"]):
            today_cards.append(card_from(rec, "today"))
    done = sorted((r for r in hist.values() if r.get("res")), key=lambda r: r["iso"], reverse=True)
    stats = {"n": len(done), "n_avant": sum(1 for r in done if r["kind"] == "avant")}
    if done:
        for k in ("1x2", "dc", "over", "btts", "score"):
            stats[k] = round(100 * sum(r["eval"][k] for r in done) / len(done))
        stats["base_dom"] = round(100 * sum(1 for r in done if r["res"][0] > r["res"][1]) / len(done))
    fin_cards = [card_from(r, "finished") for r in done[:MAX_MATCHES]]

    cards = live + today_cards[:MAX_MATCHES] + fin_cards
    if not live and not today_cards:
        cards.insert(0, {"league": "Info", "home": "Aucun match", "away": "pronostiquable", "status": "today", "conf": 0,
                         "victoire": "Aucun pronostic fiable", "score_exact": "-", "double_chance": "-", "corner": "-",
                         "over": "-", "btts": "-",
                         "analyse": f"Aucun match a venir le {today} | ESPN: {ok}/{len(jobs)} requetes OK | {len(events)} matchs lus"})
    keep = sorted(hist.items(), key=lambda kv: kv[1]["iso"], reverse=True)[:600]
    os.makedirs("data", exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump({"records": dict(keep)}, f, ensure_ascii=False)
    out = {"date": now.strftime("%Y-%m-%d %H:%M") + " UTC", "version": "V17", "stats": stats, "matches": cards}
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"FINAL: {len(live)} live, {len(today_cards)} a venir, {len(fin_cards)} termines | stats {stats}")


if __name__ == "__main__":
    main()
