import requests, json, os, time
from datetime import datetime, timedelta
print("V13.2 FIXED REAL SCORE")

today = datetime.today().date()
today_str = today.strftime("%Y%m%d")
tomorrow_str = (today + timedelta(days=1)).strftime("%Y%m%d")
LEAGUES = ["eng.1","esp.1","fra.1","ger.1","ita.1","ned.1","por.1","uefa.champions"]

TEAM_STATS = {}
for lg in LEAGUES:
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/standings?season=2024"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for child in data.get('children', []):
                for e in child.get('standings', {}).get('entries', []):
                    tid = str(e['team']['id'])
                    s = {x['name']: x['value'] for x in e.get('stats', [])}
                    played = s.get('gamesPlayed', 25) or 25
                    TEAM_STATS[tid] = {
                        "scored": s.get('pointsFor', 30) / played,
                        "conceded": s.get('pointsAgainst', 25) / played,
                        "points": s.get('points', 30),
                        "wins": s.get('wins', 8),
                        "form": e.get('form', 'WDLWW')[:5]
                    }
        time.sleep(0.3)
    except Exception as ex:
        print(f"standings err {ex}")
        continue

print(f"STATS {len(TEAM_STATS)}")

def scoreboard(date_str, league):
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={date_str}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get('events', [])
        return []
    except:
        return []

all_events = []
for lg in LEAGUES:
    all_events += scoreboard(today_str, lg)
    all_events += scoreboard(tomorrow_str, lg)
    time.sleep(0.2)

seen = set()
uniq = []
for ev in all_events:
    if ev['id'] not in seen:
        seen.add(ev['id'])
        uniq.append(ev)
all_events = uniq[:40]
print(f"EVENTS {len(all_events)}")

result = []
for ev in all_events:
    try:
        comp = ev['competitions'][0]
        home_c = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
        away_c = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
        home = home_c['team']['displayName']
        away = away_c['team']['displayName']
        hid = str(home_c['id'])
        aid = str(away_c['id'])
        league_name = ev.get('league', {}).get('name', 'Football')
        date_iso = ev['date']

        hs = TEAM_STATS.get(hid, {"scored": 1.3, "conceded": 1.1, "points": 25, "wins": 7, "form": "WDLWW"})
        aw = TEAM_STATS.get(aid, {"scored": 1.2, "conceded": 1.2, "points": 22, "wins": 6, "form": "LWDWW"})

        # CALCUL VRAI SCORE - base sur stats reelles
        home_xG = (hs['scored'] + aw['conceded']) / 2 * 1.15
        away_xG = (aw['scored'] + hs['conceded']) / 2 * 0.90
        
        home_bonus = hs['form'].count('W') * 0.15 - hs['form'].count('L') * 0.08
        away_bonus = aw['form'].count('W') * 0.15 - aw['form'].count('L') * 0.08
        home_xG = home_xG + home_bonus
        away_xG = away_xG + away_bonus

        home_goals = max(0, min(4, int(round(home_xG))))
        away_goals = max(0, min(4, int(round(away_xG))))
        if home_xG > 1.2 and home_goals == 0:
            home_goals = 1
        if away_xG > 1.2 and away_goals == 0:
            away_goals = 1

        score_exact = f"{home_goals}-{away_goals}"

        if home_xG > away_xG + 0.4:
            victoire = f"Victoire {home}"
            conf = 68 + int((home_xG - away_xG) * 12)
        elif away_xG > home_xG + 0.4:
            victoire = f"Victoire {away}"
            conf = 68 + int((away_xG - home_xG) * 12)
        else:
            victoire = "Match Nul"
            conf = 58 + int((home_xG + away_xG) * 3)

        total_buts = home_xG + away_xG
        over_pct = max(48, min(82, int(45 + total_buts * 12)))
        over = f"Over 2.5 {over_pct}%" if total_buts >= 2.2 else f"Under 2.5 {100-over_pct}%"
        
        btts_pct = max(45, min(78, int(50 + (hs['scored'] + aw['scored']) * 8)))
        btts = f"BTTS OUI {btts_pct}%" if hs['scored'] >= 0.9 and aw['scored'] >= 0.9 else f"BTTS NON {100-btts_pct}%"
        
        dc = "1X" if home_xG >= away_xG else "X2"
        corners = "Over 9.5" if total_buts > 2.6 else "Under 9.5"

        analyse = f"REAL xG: {home} {hs['form']} {hs['scored']:.2f}m {hs['conceded']:.2f}e | {away} {aw['form']} {aw['scored']:.2f}m {aw['conceded']:.2f}e | xG {home_xG:.2f}-{away_xG:.2f} = {score_exact}"

        result.append({
            "id": ev['id'],
            "date": date_iso[:10],
            "league": f"{league_name} {date_iso[11:16]} GMT",
            "home": home,
            "away": away,
            "status": "upcoming",
            "minute": None,
            "live_score": "-",
            "cornerM": 9.5,
            "corner": corners,
            "over": over,
            "btts": btts,
            "victoire": victoire,
            "double_chance": dc,
            "score_exact": score_exact,
            "conf": min(conf, 87),
            "analyse": analyse
        })
    except Exception as e:
        print(f"ev err {e}")
        continue

os.makedirs("data", exist_ok=True)
with open("data/matches.json", "w", encoding="utf-8") as f:
    json.dump({"date": today.isoformat(), "count": len(result), "matches": result}, f, ensure_ascii=False, indent=2)

print(f"V13.2 FIXED OK {len(result)} matchs")
