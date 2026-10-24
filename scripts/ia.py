import requests, json, os, time
from datetime import datetime, timedelta
print("V13.2 REAL SCORE - CALCUL VRAI")

today = datetime.today().date()
today_str = today.strftime("%Y%m%d")
tomorrow_str = (today + timedelta(days=1)).strftime("%Y%m%d")
LEAGUES = ["eng.1","esp.1","fra.1","ger.1","ita.1","ned.1","por.1","uefa.champions"]

# 1. VRAI CLASSEMENT : buts marqués + encaissés réels par équipe
TEAM_STATS = {}
for lg in LEAGUES:
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/standings?season=2024"
        r = requests.get(url, timeout=10)
        if r.status_code==200:
            for child in r.json().get('children',[]):
                for e in child.get('standings',{}).get('entries',[]):
                    tid = str(e['team']['id'])
                    s = {x['name']: x['value'] for x in e.get('stats',[])}
                    played = s.get('gamesPlayed',25) or 25
                    TEAM_STATS[tid] = {
                        "scored": s.get('pointsFor',30)/played,      # moyenne buts marqués
                        "conceded": s.get('pointsAgainst',25)/played, # moyenne buts encaissés
                        "points": s.get('points',30),
                        "wins": s.get('wins',8),
                        "form": e.get('form','WDLWW')[:5]
                    }
        time.sleep(0.4)
    except: pass

print(f"STATS REELLES: {len(TEAM_STATS)} equipes")

def scoreboard(date_str, league):
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={date_str}"
        r=requests.get(url,timeout=10)
        return r.json().get('events',[]) if r.status_code==200 else []
    except: return []

all_events=[]
for lg in LEAGUES:
    all_events+=scoreboard(today_str, lg)
    all_events+=scoreboard(tomorrow_str, lg)
    time.sleep(0.2)

# dedup
seen=set()
uniq=[]
for ev in all_events:
    if ev['id'] not in seen:
        seen.add(ev['id'])
        uniq.append(ev)
all_events=uniq[:40]

result=[]
for ev in all_events:
    try:
        comp=ev['competitions'][0]
        home_c=next(c for c in comp['competitors'] if c['homeAway']=='home')
        away_c=next(c for c in comp['competitors'] if c['homeAway']=='away')
        home=home_c['team']['displayName']
        away=away_c['team']['displayName']
        hid=str(home_c['id'])
        aid=str(away_c['id'])
        league_name=ev.get('league',{}).get('name','Football')
        date_iso=ev['date']

        hs=TEAM_STATS.get(hid, {"scored":1.3,"conceded":1.1,"points":25,"wins":7,"form":"WDLWW"})
        aw=TEAM_STATS.get(aid, {"scored":1.2,"conceded":1.2,"points":22,"wins":6,"form":"LWDWW"})

        # === CALCUL V
