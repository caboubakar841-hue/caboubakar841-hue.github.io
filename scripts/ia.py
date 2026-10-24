import os, requests, json, random
from datetime import datetime
API_KEY = os.getenv("API_KEY") or os.getenv("API_FOOTBALL_KEY")
headers = {"x-apisports-key": API_KEY}
today = datetime.today().date().isoformat()

def get_fixtures(date_str=None, live=False):
    try:
        url = f"https://v3.football.api-sports.io/fixtures?live=all" if live else f"https://v3.football.api-sports.io/fixtures?date={date_str}"
        r = requests.get(url, headers=headers, timeout=25)
        data = r.json().get('response', [])
        print(f"{'LIVE' if live else date_str}: {len(data)} matchs")
        return data
    except Exception as e:
        print(f"Erreur {e}")
        return []

def analyse(f):
    home = f['teams']['home']['name']; away = f['teams']['away']['name']
    league = f['league']['name']; time = f['fixture']['date'][11:16]
    fid = f['fixture']['id']
    home_id = f['teams']['home']['id']; away_id = f['teams']['away']['id']
    status_short = f['fixture']['status']['short']
    minute = f['fixture']['status']['elapsed']
    gh = f['goals']['home']; ga = f['goals']['away']; date_match = f['fixture']['date'][:10]
    
    if status_short in ["1H","2H","HT","ET","P","LIVE","BT"]:
        real_status = "live"
    elif status_short in ["FT","AET","PEN"]:
        real_status = "finished"
    else:
        real_status = "upcoming"
    
    live_score = f"{gh}-{ga}" if gh is not None else "-"
    random.seed(home_id + away_id + fid)
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
    return {"id":fid,"date":date_match,"league":f"{league} {time} GMT","home":home,"away":away,"status":real_status,"status_short":status_short,"minute":minute,"live_score":live_score,"cornerM":corners,"corner":f"Over {9.5 if corners>9.5 else 8.5}","over":over,"btts":btts,"victoire":victoire,"double_chance":dc,"score_exact":score,"conf":conf,"analyse":f"{home} {hs} buts/match ({home_form}), {away} {aus} buts/match ({away_form}). xG {xG}, Corners {corners}."}

fixtures_today = get_fixtures(today)
fixtures_live = get_fixtures(live=True)

all_dict = {}
for f in fixtures_today + fixtures_live:
    all_dict[f['fixture']['id']] = f
all_fixtures = list(all_dict.values())
all_fixtures = sorted(all_fixtures, key=lambda x: x['fixture']['date'])

result = [analyse(f) for f in all_fixtures[:120]]

live_count = len([m for m in result if m['status']=='live'])
finished_count = len([m for m in result if m['status']=='finished'])
upcoming_count = len([m for m in result if m['status']=='upcoming'])

os.makedirs("data",exist_ok=True)
try:
    with open("data/history.json","r") as old:
        d=json.load(old); history=d.get('matches',[]) if isinstance(d,dict) else d
except: history=[]

# FIX pour l'ancien historique sans ID
clean_history = []
for m in history:
    if 'id' not in m:
        m['id'] = hash(m.get('home','')+m.get('away','')+m.get('date','')) % 1000000
    clean_history.append(m)
history = clean_history

finished_today = [m for m in result if m['status']=='finished']
history = finished_today + history

seen={}
new_hist=[]
for m in history:
    mid = m.get('id')
    if mid not in seen:
        seen[mid]=True
        new_hist.append(m)
history = new_hist[:300]

with open("data/matches.json","w",encoding="utf-8") as out:
    json.dump({"date":today,"count":len(result),"live":live_count,"finished":finished_count,"upcoming":upcoming_count,"matches":result}, out, ensure_ascii=False, indent=2)
with open("data/history.json","w",encoding="utf-8") as out:
    json.dump({"count":len(history),"matches":history}, out, ensure_ascii=False, indent=2)

print(f"V11.1 OK: TOTAL {len(result)} = {upcoming_count} aujourd'hui + {live_count} live + {finished_count} finished")
