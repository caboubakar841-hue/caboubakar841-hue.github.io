import os, requests, json, time
from datetime import datetime, timedelta
API_KEY = os.getenv("API_KEY") or os.getenv("API_FOOTBALL_KEY")
headers = {"x-apisports-key": API_KEY}
today_dt = datetime.today().date()
today = today_dt.isoformat()
tomorrow = (today_dt + timedelta(days=1)).isoformat()
TEAM_CACHE = {}

def get_fixtures(date_str=None, live=False):
    try:
        if live:
            url = "https://v3.football.api-sports.io/fixtures?live=all"
        else:
            url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response', [])
    except:
        return []

def get_team_last5(team_id):
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]
    try:
        url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json().get('response', [])
        if not data:
            raise Exception("vide")
        scored = 0
        conceded = 0
        wins = 0
        draws = 0
        losses = 0
        btts_count = 0
        form = ""
        played = 0
        for f in data:
            is_home = f['teams']['home']['id'] == team_id
            gf = f['goals']['home'] if is_home else f['goals']['away']
            ga = f['goals']['away'] if is_home else f['goals']['home']
            if gf is None or ga is None:
                continue
            played = played + 1
            scored = scored + gf
            conceded = conceded + ga
            if f['goals']['home'] > 0 and f['goals']['away'] > 0:
                btts_count = btts_count + 1
            if gf > ga:
                wins = wins + 1
                form = form + "W"
            elif gf == ga:
                draws = draws + 1
                form = form + "D"
            else:
                losses = losses + 1
                form = form + "L"
        if played == 0:
            played = 1
        avg_scored = scored / played
        avg_conceded = conceded / played
        btts_rate = btts_count / played
        points = wins*3 + draws
        res = {"avg_scored": avg_scored, "avg_conceded": avg_conceded, "wins": wins, "draws": draws, "losses": losses, "form": form[::-1], "btts_rate": btts_rate, "points": points}
        TEAM_CACHE[team_id] = res
        time.sleep(0.2)
        return res
    except:
        fallback = {"avg_scored": 1.2, "avg_conceded": 1.1, "wins": 2, "draws": 1, "losses": 2, "form": "WDLLW", "btts_rate": 0.5, "points": 7}
        TEAM_CACHE[team_id] = fallback
        return fallback

def analyse_match(f):
    home = f['teams']['home']['name']
    away = f['teams']['away']['name']
    home_id = f['teams']['home']['id']
    away_id = f['teams']['away']['id']
    league = f['league']['name']
    time_str = f['fixture']['date'][11:16]
    fid = f['fixture']['id']
    status_short = f['fixture']['status']['short']
    minute = f['fixture']['status']['elapsed']
    gh = f['goals']['home']
    ga = f['goals']['away']
    date_match = f['fixture']['date'][:10]
    if status_short in ["1H","2H","HT","ET","P","LIVE","BT"]:
        real_status = "live"
    elif status_short in ["FT","AET","PEN"]:
        real_status = "finished"
    else:
        real_status = "upcoming"
    if gh is None:
        live_score = "-"
    else:
        live_score = f"{gh}-{ga}"
    hs = get_team_last5(home_id)
    aw = get_team_last5(away_id)
    home_strength = hs["points"] + (hs["avg_scored"] - hs["avg_conceded"])
    away_strength = aw["points"] + (aw["avg_scored"] - aw["avg_conceded"])
    diff = home_strength - away_strength
    if diff >= 3:
        victoire = "Victoire " + home
        conf = 80
        sh = round((hs["avg_scored"] + aw["avg_conceded"])/2 + 0.5)
        sa = round((aw["avg_scored"] + hs["avg_conceded"])/2)
    elif diff <= -3:
        victoire = "Victoire " + away
        conf = 77
        sh = round((hs["avg_scored"] + aw["avg_conceded"])/2)
        sa = round((aw["avg_scored"] + hs["avg_conceded"])/2 + 0.5)
    else:
        victoire = "Match Nul"
        conf = 60
        sh = round((hs["avg_scored"] + aw["avg_conceded"])/2)
        sa = sh
    if sh < 0: sh = 0
    if sa < 0: sa = 0
    if sh > 3: sh = 3
    if sa > 3: sa = 3
    if "Victoire" in victoire and home in victoire and sh <= sa:
        sh = sa + 1
    if "Victoire" in victoire and away in victoire and sa <= sh:
        sa = sh + 1
    score_exact = f"{sh}-{sa}"
    if diff >= 1.5:
        dc = "1X"
    elif diff <= -1.5:
        dc = "X2"
    else:
        if diff >= 0:
            dc = "1X fav domicile"
        else:
            dc = "X2 fav exterieur"
    avg_btts = (hs["btts_rate"] + aw["btts_rate"])/2
    if hs["avg_scored"] >= 1.2 and aw["avg_scored"] >= 1.0 and avg_btts >= 0.5:
        btts = f"BTTS OUI {int(avg_btts*100)}%"
    else:
        btts = f"BTTS NON {int((1-avg_btts)*100)}%"
    total_avg = hs["avg_scored"] + aw["avg_scored"]
    if total_avg >= 2.6:
        over = f"Over 2.5 {int(55+total_avg*5)}%"
    else:
        over = f"Under 2.5 {int(55+(3-total_avg)*8)}%"
    xG = round(total_avg, 2)
    corners = round(8.5 + total_avg*0.8, 1)
    analyse_txt = f"{home} {hs['form']} {hs['avg_scored']:.1f} buts. {away} {aw['form']} {aw['avg_scored']:.1f} buts. xG {xG}"
    return {"id": fid, "date": date_match, "league": f"{league} {time_str} GMT", "home": home, "away": away, "status": real_status, "minute": minute, "live_score": live_score, "cornerM": corners, "corner": f"Over {corners}", "over": over, "btts": btts, "victoire": victoire, "double_chance": dc, "score_exact": score_exact, "conf": conf, "analyse": analyse_txt}

fixtures_today = get_fixtures(today)
fixtures_tomorrow = get_fixtures(tomorrow)
fixtures_live = get_fixtures(live=True)
all_dict = {}
for fx in fixtures_today + fixtures_tomorrow + fixtures_live:
    all_dict[fx['fixture']['id']] = fx
all_fixtures = list(all_dict.values())
all_fixtures = sorted(all_fixtures, key=lambda x: x['fixture']['date'])
all_fixtures = all_fixtures[:35]
print(f"Analyse {len(all_fixtures)} matchs")
result = []
for i, fx in enumerate(all_fixtures):
    print(f"{i+1} {fx['teams']['home']['name']} vs {fx['teams']['away']['name']}")
    result.append(analyse_match(fx))
live_c = len([m for m in result if m['status']=='live'])
fin_c = len([m for m in result if m['status']=='finished'])
up_c = len([m for m in result if m['status']=='upcoming'])
os.makedirs("data", exist_ok=True)
with open("data/matches.json","w",encoding="utf-8") as out:
    json.dump({"date":today,"count":len(result),"live":live_c,"finished":fin_c,"upcoming":up_c,"matches":result}, out, ensure_ascii=False, indent=2)
print(f"V12 REAL OK {len(result)} matchs")
