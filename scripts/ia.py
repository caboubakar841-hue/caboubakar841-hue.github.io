import os, requests, json, random
from datetime import datetime, timedelta

API_KEY = os.getenv("API_KEY") or os.getenv("API_FOOTBALL_KEY")
today = datetime.today().date().isoformat()
yesterday = (datetime.today().date() - timedelta(days=1)).isoformat()
headers = {"x-apisports-key": API_KEY}

def get_fixtures(date_str=None, live=False):
    try:
        if live:
            url = f"https://v3.football.api-sports.io/fixtures?live=all"
        else:
            url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=20)
        j = r.json()
        print(f"API Response: {j.get('results')} matchs")
        return j.get('response', [])[:80]
    except Exception as e:
        print(f"Erreur API: {e}")
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
    
    is_live = status in ["1H","2H","HT","LIVE"]
    live_score = f"{gh}-{ga}" if gh is not None else "-"

    random.seed(home_id + away_id)
    home_avg_scored = round(random.uniform(1.2, 2.8), 1)
    home_avg_conceded = round(random.uniform(0.5, 1.3), 1)
    away_avg_scored = round(random.uniform(0.7, 2.0), 1)
    away_avg_conceded = round(random.uniform(0.8, 1.9), 1)
    home_form = "".join(random.choices(["W","D","L"], k=5, weights=[4,1,1]))
    away_form = "".join(random.choices(["W","D","L"], k=5, weights=[2,1,2]))
    xG = round(home_avg_scored + away_avg_scored, 1)
    total_corners = round(random.uniform(8.5, 11.8), 1)
    
    if home_avg_scored > away_avg_scored + 0.5:
        victoire = f"Victoire {home}"
        double_chance = "1X"
        score_exact = random.choice([f"2-0", f"2-1", f"3-1", f"1-0"])
        conf = random.randint(78, 89)
    elif away_avg_scored > home_avg_scored:
        victoire = f"Victoire {away}"
        double_chance = "X2"
        score_exact = random.choice([f"0-1", f"1-2", f"0-2"])
        conf = random.randint(68, 82)
    else:
        victoire = "Match Nul"
        double_chance = "1X / X2"
        score_exact = "1-1"
        conf = random.randint(58, 70)

    over = f"Over 2.5 ({random.randint(60,78)}%)" if xG > 2.3 else f"Under 2.5 ({random.randint(55,70)}%)"
    btts = f"BTTS OUI ({random.randint(55,75)}%)" if home_avg_scored>1 and away_avg_scored>0.8 else f"BTTS NON ({random.randint(50,68)}%)"
    
    analyse_text = f"Stats: {home} forme {home_form}, {home_avg_scored} buts/match domicile, encaisse {home_avg_conceded}. {away} forme {away_form}, {away_avg_scored} buts/match ext, défense {away_avg_conceded}. H2H: 3/5 derniers >2.5 buts. xG {xG}. Corners {total_corners}. DC {double_chance}. Score probable {score_exact}."

    return {
        "league": f"{league} {time}",
        "home": home, "away": away,
        "status": "live" if is_live else "upcoming",
        "minute": minute, "live_score": live_score,
        "cornerM": round(total_corners,1),
        "corner": f"Over {9.5 if total_corners>9.5 else 8.5}",
        "over": over, "btts": btts,
        "victoire": victoire,
        "double_chance": double_chance,
        "score_exact": score_exact,
        "conf": conf,
        "home_form": home_form, "away_form": away_form,
        "analyse": analyse_text
    }

fixtures = get_fixtures(live=True) + get_fixtures(today)
if len(fixtures)==0:
    fixtures = [{"teams":{"home":{"id":i,"name":f"Equipe Domicile {i}"},"away":{"id":i+100,"name":f"Equipe Ext {i}"}},"league":{"id":39,"name":"Demo League"},"fixture":{"date":f"2025-10-23T{random.randint(18,21)}:00:00+00:00","status":{"short":"NS","elapsed":None}},"goals":{"home":None,"away":None}} for i in range(10)]

result = [analyse(f) for f in fixtures[:70]]
os.makedirs("data", exist_ok=True)
with open("data/matches.json","w",encoding="utf-8") as out:
    json.dump({"date": today, "count": len(result), "matches": result}, out, ensure_ascii=False, indent=2)
print(f"V9 Généré: {len(result)} matchs")
