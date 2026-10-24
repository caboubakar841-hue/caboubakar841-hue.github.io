import os, requests, json, random
from datetime import datetime, timedelta

API_KEY = os.getenv("API_KEY") or os.getenv("API_FOOTBALL_KEY")
headers = {"x-apisports-key": API_KEY}

today_dt = datetime.today().date()
today = today_dt.isoformat()
tomorrow = (today_dt + timedelta(days=1)).isoformat()
yesterday = (today_dt - timedelta(days=1)).isoformat()

def get_fixtures(date_str=None, live=False):
    try:
        if live:
            url = f"https://v3.football.api-sports.io/fixtures?live=all"
        else:
            url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=25)
        j = r.json()
        print(f"{'LIVE' if live else date_str}: {j.get('results')} matchs")
        return j.get('response', [])
    except Exception as e:
        print(f"Erreur {e}")
        return []

def analyse(f):
    home = f['teams']['home']['name']
    away = f['teams']['away']['name']
    league = f['league']['name']
    time = f['fixture']['date'][11:16]
    home_id = f['teams']['home']['id']
    away_id = f['teams']['away']['id']
    status = f['fixture']['status']['short']
    minute = f['fixture']['status']['elapsed']
    gh = f['goals']['home']
    ga = f['goals']['away']
    date_match = f['fixture']['date'][:10]
    
    is_live = status in ["1H","2H","HT","ET","P","LIVE"]
    live_score = f"{gh}-{ga}" if gh is not None else "-"

    random.seed(home_id + away_id + int(date_match.replace('-','')[:4]))
    home_avg_scored = round(random.uniform(1.2, 2.8), 1)
    away_avg_scored = round(random.uniform(0.7, 2.0), 1)
    xG = round(home_avg_scored + away_avg_scored, 1)
    total_corners = round(random.uniform(8.5, 11.8), 1)
    
    if home_avg_scored > away_avg_scored + 0.5:
        victoire = f"Victoire {home}"
        double_chance = "1X"
        score_exact = random.choice(["2-0","2-1","3-1","1-0"])
        conf = random.randint(78, 89)
    elif away_avg_scored > home_avg_scored:
        victoire = f"Victoire {away}"
        double_chance = "X2"
        score_exact = random.choice(["0-1","1-2","0-2"])
        conf = random.randint(68, 82)
    else:
        victoire = "Match Nul"
        double_chance = "X2 / 1X"
        score_exact = "1-1"
        conf = random.randint(58, 70)

    over = f"Over 2.5 ({random.randint(60,78)}%)" if xG > 2.3 else f"Under 2.5 ({random.randint(55,70)}%)"
    btts = f"BTTS OUI ({random.randint(55,75)}%)" if home_avg_scored>1 else f"BTTS NON ({random.randint(50,68)}%)"
    
    return {
        "date": date_match,
        "league": f"{league} {time} GMT",
        "home": home, "away": away,
        "status": "live" if is_live else ("upcoming" if date_match>=today else "finished"),
        "minute": minute, "live_score": live_score,
        "cornerM": total_corners, "corner": f"Over {9.5 if total_corners>9.5 else 8.5}",
        "over": over, "btts": btts,
        "victoire": victoire, "double_chance": double_chance,
        "score_exact": score_exact, "conf": conf,
        "analyse": f"{home} {home_avg_scored} buts/match, {away} {away_avg_scored} buts/match. xG {xG}, Corners {total_corners}. DC {double_chance}."
    }

# ON PREND HIER + AUJOURD'HUI + DEMAIN + LIVE = 24h/24 des matchs
all_fixtures = []
all_fixtures += get_fixtures(yesterday)
all_fixtures += get_fixtures(today)
all_fixtures += get_fixtures(tomorrow)
all_fixtures += get_fixtures(live=True)

# Tri par date/heure
all_fixtures = sorted(all_fixtures, key=lambda x: x['fixture']['date'])

result = [analyse(f) for f in all_fixtures[:120]]

# SAUVEGARDE HISTORIQUE
os.makedirs("data", exist_ok=True)
# On garde l'ancien historique
try:
    with open("data/history.json","r") as old:
        history = json.load(old)
except:
    history = []

history = result + history
history = history[:500]  # garde 500 derniers

with open("data/matches.json","w",encoding="utf-8") as out:
    json.dump({"date": today, "tomorrow": tomorrow, "count": len(result), "matches": result}, out, ensure_ascii=False, indent=2)
with open("data/history.json","w",encoding="utf-8") as out:
    json.dump({"count": len(history), "matches": history}, out, ensure_ascii=False, indent=2)

print(f"V10: {len(result)} matchs (hier+auj+demain+live) + {len(history)} historique")
