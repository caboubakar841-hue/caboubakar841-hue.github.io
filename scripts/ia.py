import os, requests, json, time
from datetime import datetime, timedelta
print("V12.3 DEBUG START")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    API_KEY = os.getenv("API_FOOTBALL_KEY")
print(f"API_KEY present: {bool(API_KEY)}")
headers = {"x-apisports-key": API_KEY} if API_KEY else {}
today = datetime.today().date().isoformat()
tomorrow = (datetime.today().date() + timedelta(days=1)).isoformat()
TEAM_CACHE = {}

def get_fixtures(date_str=None, live=False):
    try:
        if live:
            url = "https://v3.football.api-sports.io/fixtures?live=all"
        else:
            url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=15)
        print(f"GET {url} -> {r.status_code}")
        return r.json().get('response', [])[:30]
    except Exception as e:
        print(f"get_fixtures error: {e}")
        return []

def get_team_last5(team_id):
    if team_id in TEAM_CACHE:
        return TEAM_CACHE[team_id]
    try:
        url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json().get('response', [])
        scored = 0
        conceded = 0
        wins = 0
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
            if gf > ga:
                form += "W"
                wins += 1
            elif gf == ga:
                form += "D"
            else:
                form += "L"
        if played == 0:
            played = 1
        res = {"avg_scored": scored/played, "avg_conceded": conceded/played, "wins": wins, "form": form[::-1] or "WDLWW", "points": wins*3, "btts_rate": 0.5}
        TEAM_CACHE[team_id] = res
        time.sleep(0.2)
        return res
    except Exception as e:
        print(f"team {team_id} error {e}")
        return {"avg_scored":1.2,"avg_conceded":1.0,"wins":2,"form":"WDLLW","points":6,"btts_rate":0.5}

fixtures = get_fixtures(today)
if len(fixtures) < 5:
    fixtures = fixtures + get_fixtures(tomorrow)
if len(fixtures) < 5:
    fixtures = get_fixtures(live=True)
fixtures = fixtures[:25]
print(f"Total fixtures: {len(fixtures)}")
result = []
for fx in fixtures:
    try:
        home = fx['teams']['home']['name']
        away = fx['teams']['away']['name']
        hid = fx['teams']['home']['id']
        aid = fx['teams']['away']['id']
        hs = get_team_last5(hid)
        aw = get_team_last5(aid)
        diff = hs["points"] - aw["points"] + (hs["avg_scored"]-aw["avg_scored"])
        if diff >= 2:
            victoire = "Victoire " + home
            score = "2-1"
            conf = 78
        elif diff <= -2:
            victoire = "Victoire " + away
            score = "1-2"
            conf = 76
        else:
            victoire = "Match Nul"
            score = "1-1"
            conf = 60
        if diff >= 1:
            dc = "1X"
        elif diff <= -1:
            dc = "X2"
        else:
            dc = "1X fav domicile" if diff>=0 else "X2 fav exterieur"
        total = hs["avg_scored"] + aw["avg_scored"]
        over = f"Over 2.5 {int(60+total*5)}%" if total>=2.5 else f"Under 2.5 {int(60+(3-total)*5)}%"
        btts = "BTTS OUI 60%" if hs["avg_scored"]>=1 and aw["avg_scored"]>=1 else "BTTS NON 55%"
        analyse = f"{home} {hs['form']} {hs['avg_scored']:.1f} buts. {away} {aw['form']} {aw['avg_scored']:.1f} buts."
        result.append({"id":fx['fixture']['id'],"date":fx['fixture']['date'][:10],"league":fx['league']['name']+" "+fx['fixture']['date'][11:16]+" GMT","home":home,"away":away,"status":"upcoming","minute":None,"live_score":"-","cornerM":9.5,"corner":"Over 9.5","over":over,"btts":btts,"victoire":victoire,"double_chance":dc,"score_exact":score,"conf":conf,"analyse":analyse})
    except Exception as e:
        print(f"analyse error {e}")
        continue

os.makedirs("data", exist_ok=True)
with open("data/matches.json","w",encoding="utf-8") as out:
    json.dump({"date":today,"count":len(result),"live":0,"finished":0,"upcoming":len(result),"matches":result}, out, ensure_ascii=False, indent=2)
print(f"V12 REAL OK {len(result)} matchs ecrits")
