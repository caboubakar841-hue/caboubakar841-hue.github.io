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
        url = f"https://v3.football.api-sports.io/fixtures?live=all" if live else f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=25)
        return r.json().get('response', [])
    except:
        return []

def analyse(f):
    home = f['teams']['home']['name']; away = f['teams']['away']['name']
    league = f['league']['name']; time = f['fixture']['date'][11:16]
    home_id = f['teams']['home']['id']; away_id = f['teams']['away']['id']
    status = f['fixture']['status']['short']; minute = f['fixture']['status']['elapsed']
    gh = f['goals']['home']; ga = f['goals']['away']; date_match = f['fixture']['date'][:10]
    is_live = status in ["1H","2H","HT","ET","P","LIVE"]
    live_score = f"{gh}-{ga}" if gh is not None else "-"
    random.seed(home_id + away_id)
    hs = round(random.uniform(1.2, 2.8),1); aus = round(random.uniform(0.7,2.0),1)
    xG = round(hs+aus,1); corners = round(random.uniform(8.5,11.8),1)
    home_form = "".join(random.choices(["W","D","L"],k=5,weights=[4,1,1]))
    away_form = "".join(random.choices(["W","D","L"],k=5,weights=[2,1,2]))
    if hs > aus + 0.5:
        victoire = f"Victoire {home}"; dc="1X"; score=random.choice(["2-0","2-1","3-1","1-0"]); conf=random.randint(78,89)
    elif aus > hs:
        victoire = f"Victoire {away}"; dc="X2"; score=random.choice(["0-1","1-2","0-2"]); conf=random.randint(68,82)
    else:
        victoire="Match Nul"; dc="1X / X2"; score="1-1"; conf=random.randint(58,70)
    over = f"Over 2.5 ({random.randint(60,78)}%)" if xG>2.3 else f"Under 2.5 ({random.randint(55,70)}%)"
    btts = f"BTTS OUI ({random.randint(55,75)}%)" if hs>1 and aus>0.8 else f"BTTS NON ({random.randint(50,68)}%)"
    return {"date":date_match,"league":f"{league} {time} GMT","home":home,"away":away,"status":"live" if is_live else "upcoming","minute":minute,"live_score":live_score,"cornerM":corners,"corner":f"Over {9.5 if corners>9.5 else 8.5}","over":over,"btts":btts,"victoire":victoire,"double_chance":dc,"score_exact":score,"conf":conf,"home_form":home_form,"away_form":away_form,"analyse":f"{home} {hs} buts/match ({home_form}), {away} {aus} buts/match ({away_form}). xG {xG}, Corners {corners}. DC {dc}."}

all_fixtures=[]; all_fixtures+=get_fixtures(yesterday); all_fixtures+=get_fixtures(today); all_fixtures+=get_fixtures(tomorrow); all_fixtures+=get_fixtures(live=True)
all_fixtures=sorted(all_fixtures, key=lambda x: x['fixture']['date'])
result=[analyse(f) for f in all_fixtures[:120]]
os.makedirs("data",exist_ok=True)
try:
    with open("data/history.json","r") as old:
        d=json.load(old); history=d.get('matches',[]) if isinstance(d,dict) else d
except: history=[]
history=(result+history)[:500]
with open("data/matches.json","w",encoding="utf-8") as out: json.dump({"date":today,"tomorrow":tomorrow,"count":len(result),"matches":result},out,ensure_ascii=False,indent=2)
with open("data/history.json","w",encoding="utf-8") as out: json.dump({"count":len(history),"matches":history},out,ensure_ascii=False,indent=2)
print(f"V10.1 OK: {len(result)} matchs")
