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
        url = f"https://v3.football.api-sports.io/fixtures?live=all" if live else f"https://v3.football.api-sports.io/fixtures?date={date_str}"
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
        wins = draws = losses = 0
        btts_count = 0
        form = ""
        played = 0
        for f in data:
            is_home = f['teams']['home']['id'] == team_id
            gf = f['goals']['home'] if is_home else f['goals']['away']
            ga = f['goals']['away'] if is_home else f['goals']['home']
            if gf is None or ga is None:
                continue
            played += 1
            scored += gf
            conceded += ga
            if f['goals']['home'] > 0 and f['goals']['away'] > 0:
                btts_count += 1
            if gf > ga:
                wins += 1
                form += "W"
            elif gf == ga:
                draws += 1
                form += "D"
            else:
                losses += 1
                form += "L"
        if played == 0:
            played = 1
        result = {
            "played": played,
            "avg_scored": scored / played,
            "avg_conceded": conceded / played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "form": form[::-1],
            "btts_rate": btts_count / played,
            "points": wins*3 + draws
        }
        TEAM_CACHE[team_id] = result
        time.sleep(0.12)
        return result
    except Exception as e:
        print(f"Erreur team {team_id}: {e}")
        fallback = {"played":5,"avg_scored":1.2,"avg_conceded":1.1,"wins":2,"draws":1,"losses":2,"form":"WDLLW","btts_rate":0.5,"points":7}
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
    live_score = f"{gh}-{ga}" if gh is not None else "-"
    home_stats = get_team_last5(home_id)
    away_stats = get_team_last5(away_id)
    home_strength = home_stats["points"] + (home_stats["avg_scored"] - home_stats["avg_conceded"])
    away_strength = away_stats["points"] + (away_stats["avg_scored"] - away_stats["avg_conceded"])
    diff = home_strength - away_strength
    if diff >= 3:
        victoire = f"Victoire {home}"
        conf = 78 + min(int(diff*2), 10)
        score_home = round((home_stats["avg_scored"] + away_stats["avg_conceded"])/2 + 0.3)
        score_away = round((away_stats["avg_scored"] + home_stats["avg_conceded"])/2 - 0.2)
    elif diff <= -3:
        victoire = f"Victoire {away}"
        conf = 75 + min(int(abs(diff)*2), 10)
        score_home = round((home_stats["avg_scored"] + away_stats["avg_conceded"])/2 - 0.2)
        score_away = round((away_stats["avg_scored"] + home_stats["avg_conceded"])/2 + 0.3)
    else:
        victoire = "Match Nul"
        conf = 60
        score_home = round((home_stats["avg_scored"] + away_stats["avg_conceded"])/2)
        score_away = round((away_stats["avg_scored"] + home_stats["avg_conceded"])/2)
    score_home = max(0, min(3, score_home))
    score_away = max(0, min(3, score_away))
    if "Victoire" in victoire and home in victoire and score_home <= score_away:
        score_home = score_away + 1
    if "Victoire" in victoire and away in victoire and score_away <= score_home:
        score_away = score_home + 1
    if victoire == "Match Nul":
        score_away = score_home
    score_exact = f"{score_home}-{score_away}"
    if diff >= 1.5:
        dc = "1X"
    elif diff <= -1.5:
       
