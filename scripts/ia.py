# PRONO70 V16 - Pronostics calcules (modele de Poisson) a partir des VRAIS resultats ESPN
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
    return []


def parse_event(ev):
    try:
        comp = ev["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        st = ev["status"]["type"]
        if any(b in str(st.get("name", "")).upper() for b in BAD_STATUS):
            return None
        out = {
            "home": home["team"]["displayName"],
            "away": away["team"]["displayName"],
            "state": st.get("state"),
            "iso": ev.get("date", ""),
        }
        if out["state"] == "post":
            if not st.get("completed"):
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


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    start, end = today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=2)
    windows, d = [], start
    while d <= end:
        e = min(d + timedelta(days=CHUNK_DAYS - 1), end)
        windows.append((d, e))
        d = e + timedelta(days=1)
    jobs = [(slug, s, e) for slug in LEAGUES for s, e in windows]
    with ThreadPoolExecutor(max_workers=10) as ex:
        fetched = list(ex.map(lambda j: (j[0], fetch(*j)), jobs))

    history, upcoming, seen = defaultdict(list), defaultdict(list), set()
    for slug, events in fetched:
        for ev in events:
            p = parse_event(ev)
            if not p:
                continue
            key = (slug, p["home"], p["away"], p["iso"][:10])
            if key in seen:
                continue
            seen.add(key)
            if p["state"] == "post" and "gh" in p:
                history[slug].append((p["home"], p["away"], p["gh"], p["ga"]))
            elif p["state"] == "pre" and p["iso"][:10] >= today.isoformat():
                upcoming[p["iso"][:10]].append((slug, p))
    print(f"Resultats: {sum(map(len, history.values()))} matchs | Ligues avec donnees: {len(history)}")

    models = {slug: fit(res) for slug, res in history.items() if len(res) >= 10}
    cards, skipped = [], 0
    if upcoming:
        day = sorted(upcoming)[0]  # aujourd'hui, ou le prochain jour avec des matchs
        for slug, p in sorted(upcoming[day], key=lambda x: x[1]["iso"]):
            m = models.get(slug)
            if not m or m["gp"].get(p["home"], 0) < MIN_GAMES or m["gp"].get(p["away"], 0) < MIN_GAMES:
                skipped += 1
                continue
            pr = predict(m, p["home"], p["away"])
            cards.append(build_card(LEAGUES[slug], p["home"], p["away"], p["iso"], pr,
                                    m["gp"][p["home"]], m["gp"][p["away"]]))
        print(f"Jour {day}: {len(cards)} pronostics, {skipped} ignores (pas assez de donnees)")

    cards = cards[:MAX_MATCHES]
    for c in cards:
        c.pop("_iso", None)
    if not cards:
        cards = [{
            "league": "Info", "home": "Aucun match", "away": "pronostiquable", "status": "today", "conf": 0,
            "victoire": "Aucun pronostic fiable", "score_exact": "-", "double_chance": "-",
            "corner": "-", "over": "-", "btts": "-",
            "analyse": f"Aucun match trouve le {today} (hors saison, API ESPN indisponible, ou pas assez de donnees)",
        }]

    out = {"date": now.strftime("%Y-%m-%d %H:%M"), "version": "V16 POISSON", "matches": cards}
    os.makedirs("data", exist_ok=True)
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"FINAL: {len(cards)} cartes ecrites")


if __name__ == "__main__":
    main()
