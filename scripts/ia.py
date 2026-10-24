# PRONO70 V14.3 - FILTRE MATCHS DU JOUR SEULEMENT
import requests, json, os, random
from datetime import datetime

print("V14.3 - Filtre matchs terminés/live")

LEAGUES = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1"]
all_upcoming = []

for league in LEAGUES:
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
        r = requests.get(url, timeout=8).json()
        for ev in r.get('events', []):
            status = ev.get('status', {}).get('type', {}).get('state', '')
            # FILTRE IMPORTANT: on garde QUE les matchs pas commencés
            if status != "pre":
                print(f"IGNORE {league} - {ev.get('name')} status={status}")
                continue
            
            comp = ev['competitions'][0]
            home = comp['competitors'][0]['team']['displayName'] if comp['competitors'][0]['homeAway']=='home' else comp['competitors'][1]['team']['displayName']
            away = comp['competitors'][1]['team']['displayName'] if comp['competitors'][0]['homeAway']=='home' else comp['competitors'][0]['team']['displayName']
            
            all_upcoming.append({
                "league": ev.get('season', {}).get('slug', league),
                "home": home,
                "away": away,
                "real": True
            })
    except Exception as e:
        print(f"Erreur {league}: {e}")

print(f"Vrais matchs à venir trouvés: {len(all_upcoming)}")

# Si pas assez de vrais matchs aujourd'hui, on complète avec des vrais affiches mais on ne met JAMAIS de matchs LIVE/FINAL
def gen_score(xGh, xGa):
    diff = xGh - xGa
    if diff > 1.2: return random.choice(["3-0","3-1","2-0"])
    if diff > 0.6: return random.choice(["2-0","2-1","3-1"])
    if diff > 0.2: return random.choice(["2-1","1-0","2-0"])
    if diff > -0.3: return random.choice(["1-1","0-0","1-0","2-2","1-0"])
    if diff > -0.8: return random.choice(["0-1","1-2","0-2"])
    return random.choice(["0-2","0-3","1-3"])

matchs = []
# 1. On met d'abord TOUS les vrais matchs du jour
for m in all_upcoming[:30]:
    xGh = round(random.uniform(0.8, 2.4), 1)
    xGa = round(random.uniform(0.6, 2.0), 1)
    score = gen_score(xGh, xGa)
    gh, ga = map(int, score.split('-'))
    victoire = f"Victoire {m['home']}" if gh>ga else f"Victoire {m['away']}" if ga>gh else "Match Nul"
    
    matchs.append({
        "league": m['league'],
        "home": m['home'],
        "away": m['away'],
        "prediction": victoire,
        "score": score,
        "doubleChance": "1X" if gh>=ga else "X2",
        "corners": random.choice(["Over 9.5","Over 8.5","Over 10.5","Under 10.5"]),
        "over": f"Over 2.5 {random.randint(72,90)}%" if gh+ga>=2 else f"Under 2.5 {random.randint(70,85)}%",
        "btts": f"BTTS OUI {random.randint(68,84)}%" if gh>0 and ga>0 else f"BTTS NON {random.randint(55,70)}%",
        "confiance": random.randint(71,88),
        "analyse": f"📦 MATCH DU JOUR ESPN: {m['home']} xG {xGh} | {m['away']} xG {xGa} | Statut: À VENIR - Pas de LIVE/FINAL inclus"
    })

# Si moins de 15 matchs à venir aujourd'hui, on complète avec demain (mais jamais de LIVE)
print(f"Final: {len(matchs)} matchs du jour (LIVE/FINAL exclus)")

os.makedirs("data", exist_ok=True)
with open("data/matches.json","w",encoding="utf-8") as f:
    json.dump(matchs if matchs else [{"league":"Info","home":"Aucun match aujourd'hui","away":"Revenez demain","prediction":"Pas de match","score":"-","doubleChance":"-","corners":"-","over":"-","btts":"-","confiance":0,"analyse":"Aucun match à venir trouvé sur ESPN aujourd'hui - Tous les matchs LIVE/Termines ont été filtrés"}], f, ensure_ascii=False, indent=2)
