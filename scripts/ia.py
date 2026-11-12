# PRONO70 V17 - Pronostics calcules (modele de Poisson) a partir des VRAIS resultats ESPN
# Aucun tirage aleatoire : tout decoule des buts marques/encaisses depuis LOOKBACK_DAYS jours.
import json
import re
import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

LOOKBACK_DAYS = 100   # historique utilise pour mesurer la force des equipes
MAX_BACKFILL_DAYS = 30  # jours d'historique recuperes par run (ESPN refuse les plages : 1 jour = 1 requete)
CACHE = "data/results.json"
MIN_GAMES = 3         # en dessous, l'equipe n'est pas pronostiquee (pas assez de donnees)
PRIOR_GAMES = 5       # lissage : peu de matchs => on reste proche de la moyenne de la ligue
MAX_GOALS = 8         # taille de la grille de scores (0..8)
MAX_MATCHES = 40
MIN_TICKET_PROB = 0.80  # ticket SUR : seuil par selection
RISKY_MIN, RISKY_MAX, RISKY_TARGET = 0.60, 0.79, 0.70  # ticket RISQUE : zone de proba visee par selection
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
    "gre.1": "Super League (GRE)", "aut.1": "Bundesliga (AUT)", "sui.1": "Super League (SUI)", "den.1": "Superliga (DEN)",
    "usa.1": "MLS", "bra.1": "Brasileirao", "arg.1": "Liga Argentina", "mex.1": "Liga MX",
    # championnats de REMPLISSAGE (affiches en dernier, seulement s'il reste de la place sous la limite de 40 matchs)
    "par.1": "Primera Paraguay", "col.1": "Liga Colombia", "bol.1": "Liga Bolivie",
    "afc.champions": "AFC Champions League", "afc.cup": "AFC Champions League Two",
    "per.1": "Liga Perou", "uru.1": "Liga Uruguay", "ecu.1": "Liga Equateur", "ven.1": "Liga Venezuela", "chi.1": "Liga Chili",
    "jpn.1": "J1 League", "aus.1": "A-League", "kor.1": "K League 1", "sau.1": "Saudi Pro League",
    "conmebol.libertadores": "Copa Libertadores", "conmebol.sudamericana": "Copa Sudamericana",
}

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
COMPS = {  # competitions de CONTEXTE (calendrier, repos) : jamais pronostiquees
    "uefa.champions": "Ligue des champions", "uefa.europa": "Ligue Europa", "uefa.europa.conf": "Conference League",
    "eng.fa": "FA Cup", "eng.league_cup": "Coupe de la Ligue (ENG)", "esp.copa_del_rey": "Coupe du Roi",
    "ita.coppa_italia": "Coupe d'Italie", "ger.dfb_pokal": "Coupe d'Allemagne", "fra.coupe_de_france": "Coupe de France",
}
INTL = {  # selections nationales : CAN, Coupe du monde, Euro, Nations League, Copa America, Gold Cup, amicaux
    "caf.nations": "CAN (Coupe d'Afrique)", "caf.nations.qual": "CAN - qualifications",
    "fifa.world": "Coupe du monde", "fifa.worldq.conmebol": "Qualif. Coupe du monde - CONMEBOL",
    "fifa.worldq.uefa": "Qualif. Coupe du monde - UEFA", "fifa.worldq.caf": "Qualif. Coupe du monde - CAF",
    "fifa.worldq.afc": "Qualif. Coupe du monde - AFC", "fifa.worldq.concacaf": "Qualif. Coupe du monde - CONCACAF",
    "fifa.worldq.ofc": "Qualif. Coupe du monde - OFC", "fifa.worldq.playoffs": "Barrages Coupe du monde",
    "uefa.euro": "Euro", "uefa.euro_qual": "Qualif. Euro", "uefa.nations": "Ligue des nations (UEFA)",
    "conmebol.america": "Copa America", "concacaf.gold": "Gold Cup", "concacaf.nations.league": "Ligue des nations (CONCACAF)",
    "afcon.qual": "AFC Asian Cup - qualifications", "afc.asian.cup": "AFC Asian Cup",
    "fifa.friendly": "Matchs amicaux internationaux",
}
ALL_COMPS = {**LEAGUES, **COMPS, **INTL}
INTL_PRIORITY = {"caf.nations": 1, "fifa.world": 1, "uefa.euro": 1, "uefa.nations": 1, "conmebol.america": 1,
                 "concacaf.gold": 1, "afc.asian.cup": 1}   # tournois finaux et Ligue des nations : tout en haut
CAF_COMPS = {"caf.nations", "caf.nations.qual", "fifa.worldq.caf"}      # CAN, qualifications CAN, qualifications Coupe du monde (Afrique)
AFRICAN_TEAMS = {  # selections africaines (noms ESPN) : leurs matchs passent TOUJOURS en premier, quelle que soit la competition
    "Morocco", "Senegal", "Nigeria", "Egypt", "Algeria", "Tunisia", "Ivory Coast", "Cote d'Ivoire", "Côte d'Ivoire", "Cameroon",
    "Ghana", "Mali", "Burkina Faso", "South Africa", "DR Congo", "Congo DR", "Congo", "Republic of the Congo", "Guinea",
    "Cape Verde", "Cape Verde Islands", "Cabo Verde", "Gabon", "Zambia", "Zimbabwe", "Angola", "Benin", "Mauritania", "Namibia",
    "Mozambique", "Madagascar", "Uganda", "Kenya", "Tanzania", "Sudan", "Libya", "Equatorial Guinea", "Comoros", "Guinea-Bissau",
    "Gambia", "The Gambia", "Sierra Leone", "Liberia", "Togo", "Niger", "Chad", "Central African Republic", "Rwanda", "Burundi",
    "Ethiopia", "Malawi", "Botswana", "Lesotho", "Eswatini", "Swaziland", "Djibouti", "Somalia", "South Sudan", "Eritrea",
    "Seychelles", "Mauritius", "Sao Tome and Principe", "São Tomé and Príncipe"}
EURO_COMPS = {"uefa.champions", "uefa.europa", "uefa.europa.conf"}
# ordre d'affichage : 0 = tout en haut. Coupes d'Europe, puis 5 grands championnats, puis le reste.
PRIORITY = {"uefa.champions": 0, "uefa.europa": 1, "uefa.europa.conf": 2,
            "eng.1": 3, "esp.1": 3, "ita.1": 3, "ger.1": 3, "fra.1": 3,
            # remplissage : toujours apres tout le reste
            "mex.1": 12, "par.1": 12, "col.1": 12, "bol.1": 12, "afc.champions": 12, "afc.cup": 12,
            "per.1": 12, "uru.1": 12, "ecu.1": 12, "ven.1": 12, "chi.1": 12, "jpn.1": 12, "aus.1": 12, "kor.1": 12,
            "sau.1": 12, "conmebol.libertadores": 12, "conmebol.sudamericana": 12}
for _k in INTL:
    PRIORITY.setdefault(_k, INTL_PRIORITY.get(_k, 2))
# Pour comparer deux clubs de championnats differents (matchs europeens) : force relative ESTIMEE (1.0 = meilleur
# championnat). Ordres de grandeur de la hierarchie europeenne, PAS des valeurs mesurees : ajuste-les si besoin.
LEAGUE_STRENGTH = {"eng.1": 1.00, "esp.1": 0.98, "ger.1": 0.95, "ita.1": 0.95, "fra.1": 0.90, "por.1": 0.85, "ned.1": 0.85,
                   "bel.1": 0.78, "tur.1": 0.78, "sco.1": 0.72, "gre.1": 0.75, "aut.1": 0.75, "sui.1": 0.72, "den.1": 0.72,
                   "eng.2": 0.75, "ger.2": 0.70, "esp.2": 0.70, "ita.2": 0.68, "fra.2": 0.66}
NEUTRAL_STRENGTH = 0.6   # club d'un championnat non couvert (match europeen) : estimation neutre, tres incertaine
# classement fiable seulement si la saison est comprise dans la fenetre d'historique (saisons europeennes)
EURO_SEASON = {"eng.1", "eng.2", "eng.3", "eng.4", "esp.1", "esp.2", "ita.1", "ita.2", "ger.1", "ger.2", "fra.1", "fra.2",
               "ned.1", "por.1", "bel.1", "tur.1", "sco.1", "gre.1", "aut.1", "sui.1", "den.1"}
ROTATION_EFFECT = 0.05   # match europeen dans les 4 jours : -5 % d'attaque, +5 % de buts encaisses (HEURISTIQUE)
STAKES_EFFECT = 0.03     # a 3 pts d'une zone cle (apres 15 matchs) : +3 % d'intensite (HEURISTIQUE)
FIX_AHEAD_DAYS = 14      # calendrier a venir recupere sur 14 jours
FIX_REFRESH_H = 6        # ... et rafraichi toutes les 6 h
ABSENCES = "data/absences.json"   # blesses/suspendus : saisis a la main (ESPN n'a pas de flux fiable)
# Decouverte automatique : ESPN nomme les divisions "<pays>.<niveau>" (ita.1 = Serie A, ita.2 = Serie B, ita.3 = Serie C...).
# Si moins de MAX_MATCHES matchs sont trouves, on sonde ces codes, du niveau 1 au niveau 4, et on garde ceux qui ont des matchs.
EXTRA_COUNTRIES = [
    "eng", "esp", "ita", "ger", "fra", "ned", "por", "bel", "tur", "sco", "gre", "aut", "sui", "den", "nor", "swe", "pol",
    "cze", "rus", "ukr", "cro", "srb", "rou", "bul", "hun", "isr", "cyp", "irl", "wal", "nir", "svk", "svn", "fin", "isl",
    "alb", "bih", "mne", "mkd", "geo", "arm", "aze", "kaz", "blr", "lux", "mlt", "est", "lva", "ltu",
    "bra", "arg", "col", "chi", "uru", "par", "per", "ecu", "bol", "ven", "mex", "usa", "can", "crc", "hon", "gua", "slv", "pan", "jam",
    "jpn", "kor", "chn", "aus", "nzl", "ind", "sau", "uae", "qat", "kuw", "irn", "irq", "tha", "idn", "mys", "vie", "sin", "hkg", "uzb",
    "egy", "rsa", "mar", "alg", "tun", "nga", "gha", "ken", "uga", "tza", "zam", "zim", "ang", "cmr", "civ", "sen"]
EXTRA_LEVELS = (1, 2, 3, 4)
DYN_MAX = 80             # nombre max de championnats decouverts gardes en memoire
DISC_EVERY_MIN = 30      # la decouverte ne tourne qu'une fois toutes les 30 min, et seulement s'il manque des matchs
LEAGUE_NAMES = {}        # noms de championnats lus dans les reponses ESPN
ALL_SAMPLE = {}          # exemple brut du filet "tous les matchs" (affiche dans le diagnostic pour comprendre le format ESPN)
H2H_FILE = "data/h2h.json"
H2H_MIN = 3             # il faut au moins 3 confrontations pour que le face-a-face influence le pronostic
H2H_PRIOR = 20          # poids du modele face au face-a-face (en "matchs equivalents") : 20 = le face-a-face pese peu
H2H_LAST = 8            # on garde les 8 dernieres confrontations
H2H_MAX_PAIRS = 120     # paires interrogees par run (matchs du jour d'abord)
H2H_REFRESH_DAYS = 14
BAD_STATUS = ("POSTPONED", "CANCEL", "ABANDON", "FORFEIT", "SUSPEND")


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36", "Accept": "application/json"}
ERRORS = []


def fetch(slug, day):
    for _ in range(2):
        try:
            r = requests.get(BASE.format(slug=slug), params={"dates": f"{day:%Y%m%d}"}, headers=HEADERS, timeout=8)
            r.raise_for_status()
            j = r.json()
            try:
                LEAGUE_NAMES[slug] = j["leagues"][0]["name"]
            except Exception:
                pass
            return j.get("events", [])
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", "")
            ERRORS.append(f"{slug} {day} -> {type(e).__name__} {code} {str(e)[:120]}")
    return None


def fetch_all(day):
    """Filet de securite : scoreboard 'tous les matchs de football' d'ESPN (competitions non listees comprises)."""
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
    for params in ({"dates": f"{day:%Y%m%d}", "limit": 500}, {"dates": f"{day:%Y%m%d}"}):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            r.raise_for_status()
            j = r.json()
            names = {}
            for l in j.get("leagues", []):
                if isinstance(l, dict) and l.get("name"):
                    m_ = re.search(r"l:(\d+)", str(l.get("uid", "")))
                    for key in (str(l.get("id")), m_.group(1) if m_ else None):
                        if key:
                            names[key] = l["name"]
            out = []
            for ev in j.get("events", []):
                m = re.search(r"l:(\d+)", str(ev.get("uid", "")))
                lid = m.group(1) if m else "x"
                slug = f"all.{lid}"
                comp0 = (ev.get("competitions") or [{}])[0]
                nm = names.get(lid) or (ev.get("league") or {}).get("name") or (comp0.get("league") or {}).get("name")
                if nm:
                    LEAGUE_NAMES[slug] = nm
                if not ALL_SAMPLE:
                    ALL_SAMPLE.update({"haut": sorted(j.keys())[:12], "nb_leagues": len(j.get("leagues", [])),
                                       "event_cles": sorted(ev.keys())[:20], "uid": str(ev.get("uid"))})
                out.append((slug, ev))
            return out
        except Exception as e:
            ERRORS.append(f"all {day} -> {type(e).__name__} {str(e)[:100]}")
    return []


def resolve_league_name(event_id):
    """Dernier recours : demande a ESPN la fiche d'un match pour lire le nom de sa competition."""
    try:
        r = requests.get("https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary", params={"event": event_id},
                         headers=HEADERS, timeout=8)
        r.raise_for_status()
        j = r.json()
        for path in (("header", "league", "name"), ("league", "name"), ("leagues", 0, "name")):
            cur = j
            try:
                for k in path:
                    cur = cur[k]
                if isinstance(cur, str) and cur:
                    return cur
            except Exception:
                continue
    except Exception as e:
        ERRORS.append(f"summary {event_id} -> {type(e).__name__} {str(e)[:80]}")
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
            "hid": str(home["team"].get("id", "")), "aid": str(away["team"].get("id", "")),
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


def predict(model, home, away, adj=None, h2h=None):
    lam_h = model["mu_h"] * model["att"][home] * model["def"][away]
    lam_a = model["mu_a"] * model["att"][away] * model["def"][home]
    if adj:                                   # contexte : rotation, enjeu, absences
        lam_h, lam_a = lam_h * adj[0], lam_a * adj[1]
    grid = [[pmf(i, lam_h) * pmf(j, lam_a) for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    tot = sum(map(sum, grid))
    grid = [[p / tot for p in row] for row in grid]
    if h2h and h2h[0] >= H2H_MIN:             # face-a-face : on rapproche les probas 1/N/2 de l'historique, avec un poids faible
        n_, hw_, d_, aw_ = h2h
        cls = lambda i, j: "H" if i > j else "A" if i < j else "D"
        p0 = {"H": 0.0, "D": 0.0, "A": 0.0}
        for i in range(MAX_GOALS + 1):
            for j in range(MAX_GOALS + 1):
                p0[cls(i, j)] += grid[i][j]
        tgt = {k: (c + H2H_PRIOR * p0[k]) / (n_ + H2H_PRIOR) for k, c in (("H", hw_), ("D", d_), ("A", aw_))}
        grid = [[grid[i][j] * tgt[cls(i, j)] / p0[cls(i, j)] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    cells = [(i, j, grid[i][j]) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)]
    p_h = sum(p for i, j, p in cells if i > j)
    p_d = sum(p for i, j, p in cells if i == j)
    p_a = sum(p for i, j, p in cells if i < j)
    p_over = sum(p for i, j, p in cells if i + j >= 3)
    p_btts = sum(p for i, j, p in cells if i >= 1 and j >= 1)
    p_o15 = sum(p for i, j, p in cells if i + j >= 2)
    p_u35 = sum(p for i, j, p in cells if i + j <= 3)

    pick = max((p_h, "H"), (p_d, "D"), (p_a, "A"))[1]
    # aucun camp n'atteint 50 % : on ne designe pas de vainqueur, on couvre (1X, X2 ou 12 selon le plus probable)
    tight = max(p_h, p_a) < 0.50
    dc = max((p_h + p_d, "1X"), (p_d + p_a, "X2"), (p_h + p_a, "12"))
    allowed = {"1X": {"H", "D"}, "X2": {"D", "A"}, "12": {"H", "A"}}[dc[1]] if tight else {pick}
    over_pick, btts_pick = p_over >= 0.5, p_btts >= 0.5
    res = lambda i, j: "H" if i > j else "A" if i < j else "D"
    over_f = lambda i, j: (i + j >= 3) == over_pick
    btts_f = lambda i, j: (i >= 1 and j >= 1) == btts_pick

    def best(*conds):
        c = [x for x in cells if res(x[0], x[1]) in allowed and all(f(x[0], x[1]) for f in conds)]
        return max(c, key=lambda x: x[2]) if c else None

    # le score affiche respecte le resultat, l'over/under ET le BTTS annonces (sinon on relache)
    si, sj, sp = best(over_f, btts_f) or best(btts_f) or best(over_f) or best()
    gp = {(i, j): p for i, j, p in cells}
    if si != sj and res(sj, si) in allowed:
        second = (sj, si)                                    # score inverse (ex. 2-1 / 1-2)
    else:                                                    # sinon meilleur score d'un autre resultat couvert
        pool = [x for x in cells if res(x[0], x[1]) in allowed and (x[0], x[1]) != (si, sj)]
        pool = [x for x in pool if res(x[0], x[1]) != res(si, sj)] or pool
        pool = [x for x in pool if over_f(x[0], x[1]) and btts_f(x[0], x[1])] or pool
        second = max(pool, key=lambda x: x[2])[:2]
    return dict(lam_h=lam_h, lam_a=lam_a, p_h=p_h, p_d=p_d, p_a=p_a, pick=pick,
                score=f"{si}-{sj}", score_p=sp, score2=f"{second[0]}-{second[1]}", score2_p=gp[second],
                dc=dc, p_over=p_over, p_btts=p_btts, tight=tight, p_o15=p_o15, p_u35=p_u35)


def pct(p):
    return round(p * 100)


def build_card(league, home, away, iso, pr, gp_h, gp_a):
    victoire = {"H": f"Victoire {home}", "A": f"Victoire {away}", "D": "Match Nul"}[pr["pick"]]
    if pr.get("tight"):
        victoire = {"1X": f"Serré : Nul ou {home}", "X2": f"Serré : Nul ou {away}",
                    "12": "Serré : pas de nul (12)"}[pr["dc"][1]]
    sc = f"{pr['score']} ({pct(pr['score_p'])}%)"
    if pr.get("score2"):
        sc += f" · {pr['score2']} ({pct(pr['score2_p'])}%)"
    over = (f"Over 2.5 {pct(pr['p_over'])}%" if pr["p_over"] >= 0.5
            else f"Under 2.5 {pct(1 - pr['p_over'])}%")
    btts = (f"BTTS OUI {pct(pr['p_btts'])}%" if pr["p_btts"] >= 0.5
            else f"BTTS NON {pct(1 - pr['p_btts'])}%")
    return {
        "league": league, "home": home, "away": away, "status": "today",
        "conf": pct(pr["dc"][0]) if pr.get("tight") else pct(max(pr["p_h"], pr["p_d"], pr["p_a"])),
        "victoire": victoire,
        "score_exact": sc,
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
        "1x2": (r in {"1X": "HD", "X2": "DA", "12": "HA"}.get(pr["dc"][1], "")) if pr.get("tight") else pr["pick"] == r,
        "dc": r in {"1X": "HD", "X2": "DA", "12": "HA"}[pr["dc"][1]],
        "over": (gh + ga >= 3) == (pr["p_over"] >= 0.5),
        "btts": (gh > 0 and ga > 0) == (pr["p_btts"] >= 0.5),
        "score": f"{gh}-{ga}" in (pr["score"], pr.get("score2")),
    }


def rec_prio(rec):
    """Priorite d'affichage (plus petit = plus haut). Afrique = -1 : toujours en premier, y compris amicaux et qualifications."""
    if rec["slug"] in CAF_COMPS:
        return -1
    if rec["slug"] in INTL or rec["slug"].startswith("all."):
        if rec["home"] in AFRICAN_TEAMS or rec["away"] in AFRICAN_TEAMS:
            return -1
    return PRIORITY.get(rec["slug"], 9)


def card_from(rec, status):
    c = build_card(rec["league"], rec["home"], rec["away"], rec["iso"], rec["pr"], rec["gp"][0], rec["gp"][1])
    c["status"] = status
    c["contexte"] = rec.get("ctx", "")
    c["day"] = rec["iso"][:10]
    c["prio"] = rec_prio(rec)
    if rec.get("neutral"):
        c["contexte"] = ("⚠️ Peu ou pas de données pour : " + ", ".join(rec["neutral"]) +
                         " (estimation neutre, très incertaine). ") + c["contexte"]
    if rec.get("nopred"):
        c.update({"victoire": "Pas de pronostic", "score_exact": "-", "double_chance": "-", "over": "-", "btts": "-",
                  "conf": 0, "nopred": True,
                  "analyse": "Aucune donnée sur ces deux équipes : match affiché pour information, sans pronostic."})
    if rec["slug"] in EURO_COMPS:
        c["contexte"] = "⚠️ Coupe d'Europe : forces comparées via des coefficients de championnat estimés (moins fiable). " + c["contexte"]
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


SAFE_CODES = {"1X", "X2", "12", "O15", "U35"}


def all_picks(rec):
    """Toutes les selections possibles d'un match : (proba, code, libelle)."""
    pr, home, away = rec["pr"], rec["home"], rec["away"]
    lam = pr["lam_h"] + pr["lam_a"]
    return [
        (pr["p_h"], "H", f"Victoire {home}"),
        (pr["p_a"], "A", f"Victoire {away}"),
        (pr["p_h"] + pr["p_d"], "1X", f"Double chance 1X ({home} ou nul)"),
        (pr["p_d"] + pr["p_a"], "X2", f"Double chance X2 (nul ou {away})"),
        (pr["p_h"] + pr["p_a"], "12", "Double chance 12 (pas de nul)"),
        (pr.get("p_o15", 1 - math.exp(-lam) * (1 + lam)), "O15", "Over 1.5 buts"),
        (pr["p_over"], "O25", "Over 2.5 buts"),
        (1 - pr["p_over"], "U25", "Under 2.5 buts"),
        (pr.get("p_u35", sum(pmf(k, lam) for k in range(4))), "U35", "Under 3.5 buts"),
        (pr["p_btts"], "BY", "BTTS OUI"),
        (1 - pr["p_btts"], "BN", "BTTS NON"),
    ]


def leg_ok(code, gh, ga):
    r, t, both = result_of(gh, ga), gh + ga, gh > 0 and ga > 0
    return {"H": r == "H", "A": r == "A", "1X": r in "HD", "X2": r in "DA", "12": r in "HA",
            "O15": t >= 2, "O25": t >= 3, "U25": t <= 2, "U35": t <= 3, "BY": both, "BN": not both}[code]


def build_tickets(recs, day):
    recs = [r for r in recs if not r.get("neutral")]
    # Ticket SUR (5) : les 5 selections les plus sures, 80 % minimum, une par match
    safe = []
    for r in recs:
        p, code, label = max(x for x in all_picks(r) if x[1] in SAFE_CODES)
        if p >= MIN_TICKET_PROB:
            safe.append((p, r, code, label))
    safe.sort(key=lambda x: -x[0])
    safe5 = safe[:5]
    used = {x[1]["id"] for x in safe5}
    # Ticket RISQUE (10) : AUTRES matchs, selection la plus proche de RISKY_TARGET => cotes plus hautes
    risky = []
    for r in recs:
        opts = [x for x in all_picks(r) if RISKY_MIN <= x[0] <= RISKY_MAX]
        if r["id"] not in used and opts:
            p, code, label = min(opts, key=lambda x: abs(x[0] - RISKY_TARGET))
            risky.append((p, r, code, label))
    risky.sort(key=lambda x: -x[0])
    risky10 = risky[:10]

    def mk(name, rule, items, n):
        legs = [{"id": r["id"], "match": f"{r['home']} vs {r['away']}", "league": r["league"], "time": r["iso"][11:16],
                 "pick": label, "code": code, "p": round(p * 100)} for p, r, code, label in items]
        return {"name": name, "rule": rule, "target": n, "n": len(legs), "legs": legs,
                "combined": round(100 * math.prod(x[0] for x in items), 1) if items else None}

    return {"v": 2, "day": day, "eligible": len(safe), "tickets": [
        mk("Ticket 10 matchs (risqué)", f"{round(RISKY_MIN * 100)} à {round(RISKY_MAX * 100)} %", risky10, 10),
        mk("Ticket 5 matchs (sûr)", "80 % ou plus", safe5, 5)]}


def settle(entry, results):
    for t in entry["tickets"]:
        for l in t["legs"]:
            r = results.get(l["id"])
            l["ok"] = leg_ok(l["code"], r["gh"], r["ga"]) if r else None
            l["score"] = f"{r['gh']}-{r['ga']}" if r else None
        oks = [l["ok"] for l in t["legs"]]
        t["status"] = "perdu" if False in oks else "gagné" if oks and all(x is True for x in oks) else "en cours"


def num(x):
    if isinstance(x, dict):
        x = x.get("value", x.get("displayValue"))
    return int(float(x))


def fetch_schedule(slug, team_id, season):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule"
    for _ in range(2):
        try:
            r = requests.get(url, params={"season": season}, headers=HEADERS, timeout=8)
            r.raise_for_status()
            return r.json().get("events", [])
        except Exception as e:
            ERRORS.append(f"schedule {slug} {team_id} {season} -> {type(e).__name__} {str(e)[:100]}")
    return None


def fetch_pair(slug, hid, aid, seasons):
    """Matchs deja joues entre deux equipes (calendrier de l'equipe a domicile, plusieurs saisons)."""
    games, ok = {}, 0
    for season in seasons:
        evs = fetch_schedule(slug, hid, season)
        if evs is None:
            continue
        ok += 1
        for ev in evs:
            try:
                comp = ev["competitions"][0]
                cs = comp["competitors"]
                tid = lambda c: str(c.get("team", {}).get("id", c.get("id")))
                if {tid(c) for c in cs} != {str(hid), str(aid)}:
                    continue
                st = (ev.get("status") or comp.get("status") or {}).get("type", {})
                if not (st.get("completed") or st.get("state") == "post"):
                    continue
                h = next(c for c in cs if c["homeAway"] == "home")
                a = next(c for c in cs if c["homeAway"] == "away")
                games[ev["date"][:10]] = [ev["date"], tid(h), tid(a), num(h["score"]), num(a["score"])]
            except Exception:
                continue
    return list(games.values()) if ok else None


def h2h_stats(games, home, away, hid, before_iso):
    rows = sorted((g for g in games if g[0] < before_iso), key=lambda g: g[0])[-H2H_LAST:]
    hw = d = aw = 0
    sc = Counter()
    for _, gh_id, ga_id, x, y in rows:
        if str(gh_id) == str(hid):
            pass
        elif str(ga_id) == str(hid):
            x, y = y, x
        else:
            continue
        r = result_of(x, y)
        hw += r == "H"; d += r == "D"; aw += r == "A"
        sc[f"{x}-{y}"] += 1
    n = hw + d + aw
    if n == 0:
        return None
    top = ", ".join(f"{k} x{v}" if v > 1 else k for k, v in sc.most_common(3))
    return {"n": n, "hw": hw, "d": d, "aw": aw,
            "text": f"Face-à-face ({n} confrontation{'s' if n > 1 else ''}) : {home} {hw}V · {d}N · {away} {aw}V (scores : {top})"
                    + ("" if n >= H2H_MIN else " - trop peu pour influer")}


def parse_iso(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def days_between(a, b):
    return round((parse_iso(b) - parse_iso(a)).total_seconds() / 86400)


def table(res):
    """Classement calcule depuis les vrais resultats : points, difference de buts."""
    pts, gp, gd = defaultdict(int), defaultdict(int), defaultdict(int)
    for h, a, x, y, _ in res:
        gp[h] += 1; gp[a] += 1; gd[h] += x - y; gd[a] += y - x
        if x > y:
            pts[h] += 3
        elif y > x:
            pts[a] += 3
        else:
            pts[h] += 1; pts[a] += 1
    order = sorted(gp, key=lambda t: (-pts[t], -gd[t], t))
    n = len(order)
    info = {t: {"rank": i + 1, "pts": pts[t], "gp": gp[t], "of": n} for i, t in enumerate(order)}
    return {"info": info, "top": pts[order[3]] if n >= 8 else None, "bot": pts[order[n - 4]] if n >= 8 else None}


def load_absences():
    """Cherche absences.json dans data/ puis dans n'importe quel dossier du depot."""
    import glob
    for path in [ABSENCES] + sorted(glob.glob("**/absences.json", recursive=True)):
        if not os.path.exists(path):
            continue
        try:
            raw = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"ATTENTION : {path} illisible ({e}) - verifie les virgules et les guillemets")
            continue
        print(f"absences lues dans {path}")
        return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}
    print("aucun absences.json trouve (optionnel)")
    return {}


def team_ctx(team, slug, kick, tabs, team_fx, team_games, absences):
    """(multiplicateur attaque, multiplicateur buts encaisses, texte) pour une equipe."""
    att = dfn = 1.0
    parts = []
    tb = tabs.get(slug)
    if tb and team in tb["info"]:
        i = tb["info"][team]
        parts.append(f"{i['rank']}e/{i['of']} ({i['pts']} pts en {i['gp']} m.)")
        if i["gp"] >= 15 and tb["top"] is not None and (abs(i["pts"] - tb["top"]) <= 3 or abs(i["pts"] - tb["bot"]) <= 3):
            att *= 1 + STAKES_EFFECT; dfn *= 1 - STAKES_EFFECT
            parts.append("enjeu fort (proche d'une zone cle)")
    last = [g for g in team_games.get(team, []) if g < kick]
    if last:
        parts.append(f"repos {days_between(max(last), kick)} j")
    nxt = [f for f in team_fx.get(team, []) if f["iso"] > kick][:3]
    if any(f["slug"] in EURO_COMPS and days_between(kick, f["iso"]) <= 4 for f in nxt):
        att *= 1 - ROTATION_EFFECT; dfn *= 1 + ROTATION_EFFECT
        parts.append("match europeen proche : rotation possible")
    ab = absences.get(team)
    if ab:
        try:
            att *= 1 + float(ab.get("att", 0)) / 100; dfn *= 1 + float(ab.get("def", 0)) / 100
        except (TypeError, ValueError):
            pass
        parts.append("absences : " + str(ab.get("note", "?")))
    if nxt:
        parts.append("prochains : " + ", ".join(f"{f['opp']} ({ALL_COMPS.get(f['slug'], f['slug'])}, {days_between(kick, f['iso'])} j)" for f in nxt))
    clamp = lambda v: min(1.2, max(0.8, v))
    return clamp(att), clamp(dfn), f"{team} : " + " | ".join(parts) if parts else team


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    t = now.date()
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    if cache.get("v") != 6:                  # v3 : nouveaux championnats
        cache["days_done"], cache["v"] = [], 6
    cache.setdefault("days_done", [])
    cache.setdefault("results", {})
    cache.setdefault("fixtures", {})
    cache.setdefault("dyn", {})
    cache.setdefault("lnames", {})
    LEAGUE_NAMES.update(cache["lnames"])
    cache.setdefault("skip", {})
    for sl_, v_ in cache["dyn"].items():     # championnats decouverts lors des runs precedents : traites comme les autres
        LEAGUES[sl_] = ALL_COMPS[sl_] = v_["name"]
        PRIORITY.setdefault(sl_, 8 + v_["level"])
    done_days = set(cache["days_done"])
    all_days = [t + timedelta(days=2 - k) for k in range(LOOKBACK_DAYS + 3)]      # t+2 ... t-LOOKBACK
    fresh = [d for d in all_days if d >= t - timedelta(days=1)]                   # toujours rafraichis
    missing = [d for d in all_days if d < t - timedelta(days=1) and d.isoformat() not in done_days][:MAX_BACKFILL_DAYS]
    try:
        stale = (now - datetime.fromisoformat(cache["fx_updated"])).total_seconds() > FIX_REFRESH_H * 3600
    except Exception:
        stale = True
    future = [t + timedelta(days=k) for k in range(3, FIX_AHEAD_DAYS + 1)] if stale else []
    jobs = [(slug, d) for d in fresh + missing + future for slug in ALL_COMPS]
    with ThreadPoolExecutor(max_workers=10) as ex:
        fetched = list(ex.map(lambda j: (j[0], j[1], fetch(*j)), jobs))
    ok = sum(1 for _, _, ev in fetched if ev is not None)
    print(f"ESPN: {ok}/{len(jobs)} requetes OK ({len(fresh)} jours frais, {len(missing)} jours d'historique)")
    for err in ERRORS[:5]:
        print("ERREUR ESPN:", err)
    if ok == 0:
        raise SystemExit("ESPN injoignable : on garde l'ancien matches.json")

    # --- decouverte : s'il manque des matchs, on sonde d'autres championnats (niveau 1 d'abord, puis 2, 3, 4...)
    def playable(lst):
        c = 0
        for _, d_, evs_ in lst:
            if evs_ and d_ in (t, t + timedelta(days=1)):
                c += sum(1 for ev_ in evs_ if (parse_event(ev_) or {}).get("state") in ("pre", "in"))
        return c

    try:
        last_disc = datetime.fromisoformat(cache["disc_at"])
    except Exception:
        last_disc = None
    n_found = playable(fetched)
    n_new = 0
    if n_found < MAX_MATCHES and (last_disc is None or (now - last_disc).total_seconds() > DISC_EVERY_MIN * 60):
        cands = [f"{cc}.{lv}" for lv in EXTRA_LEVELS for cc in EXTRA_COUNTRIES
                 if f"{cc}.{lv}" not in ALL_COMPS and cache["skip"].get(f"{cc}.{lv}", "") < now.isoformat()]
        jobs2 = [(sl_, d_) for sl_ in cands for d_ in (t, t + timedelta(days=1))]
        with ThreadPoolExecutor(max_workers=10) as ex:
            disc = list(ex.map(lambda j: (j[0], j[1], fetch(*j)), jobs2))
        has_ev = {sl_ for sl_, _, evs_ in disc if evs_}
        valid = {sl_ for sl_, _, evs_ in disc if evs_ is not None}
        for sl_ in cands:
            if sl_ not in valid:
                cache["skip"][sl_] = (now + timedelta(days=7)).isoformat()      # code inconnu : on reessaie dans 7 jours
            elif sl_ not in has_ev:
                cache["skip"][sl_] = (now + timedelta(hours=6)).isoformat()     # code valide mais aucun match : dans 6 h
        for sl_ in sorted(has_ev, key=lambda x: int(x.split(".")[1])):
            if sl_ not in cache["dyn"] and len(cache["dyn"]) < DYN_MAX:
                lv_ = int(sl_.split(".")[1])
                name_ = LEAGUE_NAMES.get(sl_) or f"{sl_.split('.')[0].upper()} - division {lv_}"
                cache["dyn"][sl_] = {"name": name_, "level": lv_}
                LEAGUES[sl_] = ALL_COMPS[sl_] = name_
                PRIORITY.setdefault(sl_, 8 + lv_)
                n_new += 1
        fetched = fetched + [x for x in disc if x[0] in cache["dyn"]]
        cache["disc_at"] = now.isoformat()
    print(f"Decouverte : {n_found} matchs connus, {n_new} nouveaux championnats ajoutes ({len(cache['dyn'])} au total)")

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
            fkey = f"{slug}:{p['id']}"
            if p["state"] == "pre":
                cache["fixtures"][fkey] = {"slug": slug, "home": p["home"], "away": p["away"], "iso": p["iso"]}
            else:
                cache["fixtures"].pop(fkey, None)
    known_ids = {q["id"] for _, q in fresh_events} | set(cache["results"])
    n_all = 0
    all_post = []
    for d_ in (t - timedelta(days=1), t, t + timedelta(days=1), t + timedelta(days=2)):
        for sl_, ev_ in fetch_all(d_):
            q = parse_event(ev_)
            if not q or q["id"] in known_ids:
                continue
            known_ids.add(q["id"])
            PRIORITY.setdefault(sl_, 13)         # tout en bas : seulement pour completer
            if q["state"] == "post":
                all_post.append((sl_, q))        # match fini : sert a l'historique (si on a des donnees dessus)
            elif q["state"] in ("pre", "in"):
                fresh_events.append((sl_, q))
                n_all += 1
    first_ev = {}
    for sl_, q in fresh_events:
        if sl_.startswith("all.") and sl_ not in LEAGUE_NAMES and sl_ != "all.x":
            first_ev.setdefault(sl_, q["id"])
    for sl_, eid in list(first_ev.items())[:12]:
        nm_ = resolve_league_name(eid)
        if nm_:
            LEAGUE_NAMES[sl_] = cache["lnames"][sl_] = nm_
    for d in missing:
        if d not in failed_days:
            done_days.add(d.isoformat())
    oldest = (t - timedelta(days=LOOKBACK_DAYS + 5)).isoformat()
    cache["days_done"] = sorted(x for x in done_days if x >= oldest)
    cache["results"] = {k: v for k, v in cache["results"].items() if v["iso"][:10] >= oldest}
    cache["fixtures"] = {k: v for k, v in cache["fixtures"].items() if v["iso"][:10] >= today}
    if stale:
        cache["fx_updated"] = now.isoformat()

    results, events, seen = defaultdict(list), [], set()
    for r in cache["results"].values():
        results[r["slug"]].append((r["home"], r["away"], r["gh"], r["ga"], r["iso"][:10]))
        events.append((r["slug"], {"id": r["id"], "home": r["home"], "away": r["away"], "state": "post",
                                   "iso": r["iso"], "detail": "FT", "gh": r["gh"], "ga": r["ga"]}))
    for slug, p in fresh_events:
        if (slug, p["id"]) not in seen:
            seen.add((slug, p["id"]))
            events.append((slug, p))
    events.extend(all_post)
    print(f"{sum(map(len, results.values()))} resultats, {len(events)} matchs au total")
    tabs = {sl: table(rs) for sl, rs in results.items() if sl in EURO_SEASON and len(rs) >= 10}
    team_fx, team_games = defaultdict(list), defaultdict(list)
    for f in cache["fixtures"].values():
        team_fx[f["home"]].append({"iso": f["iso"], "slug": f["slug"], "opp": f["away"]})
        team_fx[f["away"]].append({"iso": f["iso"], "slug": f["slug"], "opp": f["home"]})
    for v in team_fx.values():
        v.sort(key=lambda x: x["iso"])
    for r in cache["results"].values():
        team_games[r["home"]].append(r["iso"]); team_games[r["away"]].append(r["iso"])
    absences = load_absences()
    print(f"contexte : {len(cache['fixtures'])} matchs a venir connus, {len(tabs)} classements, {len(absences)} equipes avec absences")

    try:
        h = json.load(open(HIST, encoding="utf-8"))
        hist = h["records"] if h.get("v") == 19 else {}   # logique changee : on repart a zero
    except Exception:
        hist = {}
    for k, r in hist.items():
        r.setdefault("id", k)                # anciens enregistrements sans id
    mcache = {}

    intl_pool = [r for sl_ in INTL for r in results.get(sl_, [])]     # selections : tous les matchs, toutes competitions

    def model_before(slug, day):
        if (slug, day) not in mcache:
            train = [r[:4] for r in (intl_pool if slug in INTL else results[slug]) if r[4] < day]
            mcache[(slug, day)] = fit(train) if len(train) >= 10 else None
        return mcache[(slug, day)]

    seen_today = defaultdict(int)
    for sl, p in fresh_events:
        if p["iso"][:10] == today:
            seen_today[sl] += 1
    print("Matchs a venir/en cours aujourd'hui par competition :", dict(sorted(seen_today.items())))
    print("Codes ESPN sans aucune reponse (inconnus ?) :", sorted(set(ALL_COMPS) - good_slugs))
    # --- matchs europeens : forces domestiques des deux clubs, ramenees a une echelle commune
    team_slug = {}
    for sl in LEAGUES:
        for h, a, *_ in results.get(sl, []):
            team_slug[h] = sl
            team_slug[a] = sl
    eu = [r for r in cache["results"].values() if r["slug"] in EURO_COMPS]
    mu_eu = (sum(r["gh"] for r in eu) / len(eu), sum(r["ga"] for r in eu) / len(eu)) if len(eu) >= 20 else (1.5, 1.2)

    def euro_model(home, away, day):
        try:
            att, dfn, gp, neutral = {}, {}, {}, []
            for tm in (home, away):
                sl = team_slug.get(tm)
                mm = model_before(sl, day) if sl else None
                if mm and tm in mm["att"]:
                    st_ = LEAGUE_STRENGTH.get(sl, 0.7)
                    att[tm], dfn[tm], gp[tm] = mm["att"][tm] * st_, mm["def"][tm] / st_, mm["gp"][tm]
                else:
                    pm = model_before("fifa.friendly", day)          # selection nationale connue par ses matchs recents ?
                    if pm and tm in pm["att"]:
                        att[tm], dfn[tm], gp[tm] = pm["att"][tm], pm["def"][tm], pm["gp"][tm]
                    else:                            # inconnu : estimation neutre, signalee
                        att[tm], dfn[tm], gp[tm] = NEUTRAL_STRENGTH, 1 / NEUTRAL_STRENGTH, 0
                        neutral.append(tm)
            return {"mu_h": mu_eu[0], "mu_a": mu_eu[1], "att": att, "def": dfn, "gp": gp, "neutral": neutral}
        except Exception:
            return None

    def thin_model(slug, home, away, day):
        """Peu ou pas de donnees : equipes 'moyennes' (ajustees si on a deja quelques matchs). Toujours signale."""
        train = [r[:4] for r in (intl_pool if slug in INTL else results.get(slug, [])) if r[4] < day]
        mm = fit(train) if len(train) >= 4 else None
        mu = (sum(r[2] for r in train) / len(train), sum(r[3] for r in train) / len(train)) if len(train) >= 4 else mu_eu
        att, dfn, gp = {home: 1.0, away: 1.0}, {home: 1.0, away: 1.0}, {home: 0, away: 0}
        for tm in (home, away):
            if mm and tm in mm["att"]:
                att[tm], dfn[tm], gp[tm] = mm["att"][tm], mm["def"][tm], mm["gp"][tm]
        return {"mu_h": mu[0], "mu_a": mu[1], "att": att, "def": dfn, "gp": gp,
                "neutral": [tm for tm in (home, away) if gp[tm] < MIN_GAMES]}

    try:
        h2h_cache = json.load(open(H2H_FILE, encoding="utf-8"))
    except Exception:
        h2h_cache = {}
    cur = t.year if t.month >= 7 else t.year - 1
    seasons = [cur - k for k in range(5)]
    pair_of = lambda sl, q: f"{sl}:" + "-".join(sorted([q["hid"], q["aid"]]))
    need = {}
    # matchs a venir de tous les championnats, coupes d'Europe et remplissage ; les matchs du jour passent en premier
    cands = sorted((x for x in events if x[1]["state"] == "pre" and x[1].get("hid") and x[1].get("aid")
                    and x[1]["iso"][:10] >= today and (x[0] in ALL_COMPS)),
                   key=lambda x: (x[1]["iso"][:10] != today, x[1]["iso"]))
    for sl, q in cands:
        k = pair_of(sl, q)
        if k in need:
            continue
        old = h2h_cache.get(k)
        fresh = old and (now - datetime.fromisoformat(old["t"])).days < H2H_REFRESH_DAYS
        if not fresh and len(need) < H2H_MAX_PAIRS:
            need[k] = (sl, q["hid"], q["aid"])
    if need:
        with ThreadPoolExecutor(max_workers=8) as ex:
            got = list(ex.map(lambda kv: (kv[0], fetch_pair(*kv[1], seasons)), need.items()))
        for k, games in got:
            if games is not None:
                h2h_cache[k] = {"t": now.isoformat(), "games": games}
    n_today = sum(1 for sl, q in cands if q["iso"][:10] == today)
    print(f"Face-a-face : {n_today} matchs du jour, {len(need)} paires interrogees, "
          f"{sum(1 for k in need if h2h_cache.get(k, {}).get('games'))} avec au moins une confrontation")

    limit = (t - timedelta(days=BACKTEST_DAYS)).isoformat()
    live, upcoming = [], defaultdict(list)
    for slug, p in events:
        if slug not in LEAGUES and slug not in EURO_COMPS and slug not in INTL and not slug.startswith("all."):   # coupes nationales : contexte uniquement
            continue
        day = p["iso"][:10]
        rec = hist.get(p["id"])
        if p["state"] == "post" and day < limit and not rec:
            continue
        if p["state"] in ("pre", "in") and (day < (t - timedelta(days=1)).isoformat() or day > (t + timedelta(days=2)).isoformat()):
            continue
        refresh = bool(rec) and p["state"] == "pre" and rec.get("kind") == "avant"
        if not rec or refresh:               # modifiable jusqu'au coup d'envoi (contexte, absences), fige ensuite
            cross = slug in EURO_COMPS or slug.startswith("all.")
            m = euro_model(p["home"], p["away"], min(day, today)) if cross else model_before(slug, min(day, today))
            if not m or (not cross and (m["gp"].get(p["home"], 0) < MIN_GAMES or m["gp"].get(p["away"], 0) < MIN_GAMES)):
                if p["state"] == "post":
                    continue                         # on ne recalcule pas apres coup un match sans donnees
                m = thin_model(slug, p["home"], p["away"], min(day, today))   # a venir / en cours : on l'affiche quand meme
            nopred = all(m["gp"].get(tm, 0) == 0 for tm in (p["home"], p["away"]))   # aucune donnee sur aucune des deux equipes
            if p["state"] == "post" and nopred:
                continue                             # match fini sans aucune donnee : rien a evaluer, on n'encombre pas l'historique
            pr = pr0 = predict(m, p["home"], p["away"])
            ctx_text, base_p, noh2h_p = "", None, None
            if p["state"] in ("pre", "in"):  # le contexte n'a de sens que pour un match a venir (jamais apres coup)
                ah, dh, th = team_ctx(p["home"], team_slug.get(p["home"], slug), p["iso"], tabs, team_fx, team_games, absences)
                aa, da, ta = team_ctx(p["away"], team_slug.get(p["away"], slug), p["iso"], tabs, team_fx, team_games, absences)
                adj = (ah * da, aa * dh)
                ctx_text = th + "  ||  " + ta
                if abs(adj[0] - 1) > 1e-9 or abs(adj[1] - 1) > 1e-9:
                    pr = predict(m, p["home"], p["away"], adj)
                    base_p = [pr0["p_h"], pr0["p_d"], pr0["p_a"]]   # reference sans contexte, pour mesurer l'apport reel
                hs = None
                if p.get("hid") and p.get("aid") and p["state"] == "pre":
                    hs = h2h_stats(h2h_cache.get(pair_of(slug, p), {}).get("games", []), p["home"], p["away"], p["hid"], p["iso"])
                if hs:
                    ctx_text = hs["text"] + "  ||  " + ctx_text
                    if hs["n"] >= H2H_MIN:
                        noh2h_p = [pr["p_h"], pr["p_d"], pr["p_a"]]   # pronostic AVANT face-a-face, pour mesurer son apport
                        pr = predict(m, p["home"], p["away"], adj, (hs["n"], hs["hw"], hs["d"], hs["aw"]))
                        if base_p is None:
                            base_p = [pr0["p_h"], pr0["p_d"], pr0["p_a"]]
            rec = hist[p["id"]] = {"id": p["id"], "slug": slug, "league": ALL_COMPS.get(slug) or LEAGUE_NAMES.get(slug) or "Autre compétition", "home": p["home"], "away": p["away"],
                                   "iso": p["iso"], "pr": pr, "gp": [m["gp"][p["home"]], m["gp"][p["away"]]],
                                   "kind": "avant" if p["state"] == "pre" else "retro", "res": None,
                                   "ctx": ctx_text, "base_p": base_p, "noh2h_p": noh2h_p, "neutral": m.get("neutral", []), "nopred": nopred}
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
        days_sorted = sorted(upcoming)
        order_key = lambda r: (rec_prio(r), 1 if r.get("neutral") else 0, r["iso"])
        day_recs = sorted(upcoming[days_sorted[0]], key=order_key)       # les tickets ne portent que sur le premier jour
        ordered = list(day_recs)
        for dd in days_sorted[1:]:                                       # jours suivants : seulement pour completer
            if len(ordered) >= MAX_MATCHES:
                break
            ordered += sorted(upcoming[dd], key=order_key)
        today_cards = [card_from(rec, "today") for rec in ordered]
    done_all = sorted((r for r in hist.values() if r.get("res")), key=lambda r: r["iso"], reverse=True)
    done = [r for r in done_all if not r.get("neutral")]
    stats = {"n": len(done), "n_avant": sum(1 for r in done if r["kind"] == "avant")}
    if done:
        rate = lambda rs, k: round(100 * sum(r["eval"][k] for r in rs) / len(rs)) if rs else None
        fav = [r for r in done if not r["eval"].get("tight")]
        tig = [r for r in done if r["eval"].get("tight")]
        for k in ("dc", "over", "btts", "score"):
            stats[k] = rate(done, k)
        stats.update({"1x2": rate(fav, "1x2"), "n_fav": len(fav), "serre": rate(tig, "1x2"), "n_serre": len(tig)})
        stats["base_dom"] = round(100 * sum(1 for r in done if r["res"][0] > r["res"][1]) / len(done))
        eu_done = [r for r in done if r["slug"] in EURO_COMPS]
        if eu_done:
            stats["n_euro"], stats["dc_euro"] = len(eu_done), rate(eu_done, "dc")
        cr = [r for r in done if r.get("base_p")]       # matchs ou le contexte a vraiment change le pronostic
        if cr:
            def brier(ps, res):
                o = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}[result_of(*res)]
                return sum((a - b) ** 2 for a, b in zip(ps, o))
            stats["n_ctx"] = len(cr)
            stats["brier_ctx"] = round(sum(brier((r["pr"]["p_h"], r["pr"]["p_d"], r["pr"]["p_a"]), r["res"]) for r in cr) / len(cr), 3)
            stats["brier_base"] = round(sum(brier(r["base_p"], r["res"]) for r in cr) / len(cr), 3)
            hr = [r for r in cr if r.get("noh2h_p")]          # matchs ou le face-a-face a modifie le pronostic
            if hr:
                stats["n_h2h"] = len(hr)
                stats["brier_h2h"] = round(sum(brier((r["pr"]["p_h"], r["pr"]["p_d"], r["pr"]["p_a"]), r["res"]) for r in hr) / len(hr), 3)
                stats["brier_noh2h"] = round(sum(brier(r["noh2h_p"], r["res"]) for r in hr) / len(hr), 3)
    fin_cards = [card_from(r, "finished") for r in done_all[:MAX_MATCHES]]

    live.sort(key=lambda c: c.get("prio", 9))
    cards = live + today_cards[:MAX_MATCHES] + fin_cards
    if not live and not today_cards:
        cards.insert(0, {"league": "Info", "home": "Aucun match", "away": "pronostiquable", "status": "today", "conf": 0,
                         "victoire": "Aucun pronostic fiable", "score_exact": "-", "double_chance": "-", "corner": "-",
                         "over": "-", "btts": "-",
                         "analyse": f"Aucun match a venir le {today} | ESPN: {ok}/{len(jobs)} requetes OK | {len(events)} matchs lus | historique en cours de remplissage"})
    eu_seen = sum(1 for sl, p in events if sl in EURO_COMPS and p["state"] in ("pre", "in") and p["iso"][:10] == today)
    eu_cards = sum(1 for c in cards if c.get("prio", 9) <= 2 and c["status"] in ("today", "live"))
    fill = sum(1 for c in today_cards[:MAX_MATCHES] if c.get("prio", 9) == 12)
    print(f"Europe aujourd'hui : {eu_cards} cartes pour {eu_seen} matchs vus | remplissage affiche : {fill}")
    afr = sum(1 for c in cards if c.get("prio") == -1 and c["status"] in ("today", "live"))
    top = sorted(((k, v) for k, v in seen_today.items() if not k.startswith("all.")), key=lambda kv: -kv[1])[:12]
    diag = [f"Compétitions suivies : {len(ALL_COMPS)} dont {len(cache['dyn'])} découvertes automatiquement",
            "Matchs trouvés aujourd'hui par compétition : " + (", ".join(f"{k} {v}" for k, v in top) or "aucun"),
            f"Matchs africains affichés (à venir / live) : {afr}",
            f"Matchs ajoutés par le filet « tous les matchs ESPN » : {n_all}",
            f"Cartes à venir affichées : {len(today_cards[:MAX_MATCHES])} (jours : {', '.join(sorted(upcoming)) or 'aucun'})",
            "Filet ESPN - format reçu : " + json.dumps(ALL_SAMPLE, ensure_ascii=False)[:300],
            "Compétitions sans nom : " + (", ".join(sorted({sl_ for sl_, _ in fresh_events if sl_.startswith("all.") and sl_ not in LEAGUE_NAMES})[:8]) or "aucune"),
            "Codes sans réponse : " + (", ".join(sorted(set(ALL_COMPS) - good_slugs)[:12]) or "aucun")]
    keep = sorted(hist.items(), key=lambda kv: kv[1]["iso"], reverse=True)[:600]
    os.makedirs("data", exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump({"v": 19, "records": dict(keep)}, f, ensure_ascii=False)
    try:
        tk = json.load(open(TICKETS, encoding="utf-8"))
    except Exception:
        tk = {}
    tk.setdefault("days", {})
    if day_recs:
        dkey = sorted(upcoming)[0]
        old = tk["days"].get(dkey)
        started = bool(old) and any(l.get("ok") is not None for t in old["tickets"] for l in t["legs"])
        if not old or (old.get("v") != 2 and not started):   # fige ensuite (refait 1 fois si ancienne regle)
            tk["days"][dkey] = build_tickets(day_recs[:MAX_MATCHES], dkey)
    for entry in tk["days"].values():
        settle(entry, cache["results"])
    tk["days"] = dict(sorted(tk["days"].items(), reverse=True)[:14])
    with open(TICKETS, "w", encoding="utf-8") as f:
        json.dump(tk, f, ensure_ascii=False)
    with open(H2H_FILE, "w", encoding="utf-8") as f:
        json.dump(h2h_cache, f, ensure_ascii=False)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    out = {"date": now.strftime("%Y-%m-%d %H:%M") + " UTC", "version": "V17", "stats": stats, "diag": diag, "tickets": [tk["days"][d] for d in sorted(tk["days"], reverse=True)], "matches": cards}
    with open("data/matches.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"FINAL: {len(live)} live, {len(today_cards)} a venir, {len(fin_cards)} termines | stats {stats}")


if __name__ == "__main__":
    main()
