#!/usr/bin/env python3
"""AREA151 Scan · fotos y precios de cartas de fútbol desde la API oficial de eBay (Browse API).
- Busca anuncios activos en eBay España de cada jugador de cada colección (cards.json) y guarda, por carta:
  precio mediano en euros, número de anuncios, foto del anuncio que mejor encaja, enlace y fecha → ebay/<colección>.json
- Las claves (EBAY_APP_ID, EBAY_CERT_ID) son secretos del repositorio: nunca se escriben en ningún archivo.
- Cada noche gasta como mucho CALLS búsquedas (eBay da 5.000 al día): primero las cartas nunca buscadas, luego las más antiguas.
Solo librería estándar."""
import base64, json, os, re, statistics, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
CALLS = int(os.environ.get('CALLS', '4500'))
MAX_AGE = int(os.environ.get('MAX_AGE_DAYS', '10'))
ONLY = os.environ.get('ONLY', '').split(',') if os.environ.get('ONLY') else []
MARKET = os.environ.get('MARKET', 'EBAY_ES')
FIRST = [x for x in os.environ.get('FIRST', 'mgk').split(',') if x]
TODAY = time.strftime('%Y-%m-%d')
API = 'https://api.ebay.com'

def norm(s): return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFD', str(s or '').lower()).encode('ascii', 'ignore').decode())
def words(s): return [w for w in re.split(r'[^a-z0-9]+', unicodedata.normalize('NFD', str(s or '').lower()).encode('ascii', 'ignore').decode()) if w]

class Ebay:
    def __init__(self):
        self.id, self.secret = os.environ.get('EBAY_APP_ID', '').strip(), os.environ.get('EBAY_CERT_ID', '').strip()
        if not self.id or not self.secret: sys.exit('Faltan los secretos EBAY_APP_ID y EBAY_CERT_ID')
        self.tok, self.exp, self.calls = None, 0, 0
    def token(self):
        if self.tok and time.time() < self.exp - 120: return self.tok
        auth = base64.b64encode(f'{self.id}:{self.secret}'.encode()).decode()
        body = urllib.parse.urlencode({'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}).encode()
        req = urllib.request.Request(API + '/identity/v1/oauth2/token', data=body, headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'})
        try: d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e: sys.exit(f'eBay no acepta las claves ({e.code}): {e.read()[:300]!r}')
        self.tok, self.exp = d['access_token'], time.time() + int(d.get('expires_in', 7200))
        return self.tok
    def search(self, q, limit=200):
        self.calls += 1; time.sleep(0.12)
        u = API + '/buy/browse/v1/item_summary/search?' + urllib.parse.urlencode({'q': q, 'limit': limit})
        req = urllib.request.Request(u, headers={'Authorization': 'Bearer ' + self.token(), 'X-EBAY-C-MARKETPLACE-ID': MARKET, 'Accept-Language': 'es-ES'})
        for attempt in range(3):
            try: return json.loads(urllib.request.urlopen(req, timeout=30).read()).get('itemSummaries', [])
            except urllib.error.HTTPError as e:
                if e.code == 429: raise RuntimeError('límite diario de eBay')
                if e.code in (500, 502, 503, 504): time.sleep(3 * (attempt + 1)); continue
                print('  error', e.code, q, e.read()[:200], flush=True); return []
            except Exception as e: print('  error', e, flush=True); time.sleep(3)
        return []

BAD = re.compile(r'\b(psa|bgs|sgc|cgc|beckett|graded|gradead[ao]|slab|lote|lot|lots|bundle|pack|sobre|sobres|caja|box|blaster|hobby|tin|album|álbum|set completo|complete set|colecci[oó]n|completa|elige|choose|pick|select your|you pick|a elegir|escoge|repes|duplicad[ao]s|x\s?\d{1,3}|\d{1,3}\s?x|\d+\s?(cartas|cards|cromos)|(cartas|cards|cromos)\s?\d+)\b', re.I)
def seasons_ok(s):
    """Formas de escribir la temporada o el año de la colección en un título"""
    toks = []
    m = re.search(r'(20(\d\d))-(\d\d)', s.get('season') or '')
    if m:
        a, a2, b2 = m.group(1), m.group(2), m.group(3); b = '20' + b2
        toks += [f'{a}/{b2}', f'{a}-{b2}', f'{a2}/{b2}', f'{a2}-{b2}', f'{a}/{b}', f'{a}-{b}', f'{a} {b}', f'{a2}{b2}', f'{a2} {b2}', f'{a}/{b}']
    for y in re.findall(r'\b20\d\d\b', re.sub(r'20\d\d-\d\d', ' ', s['name'])): toks.append(y)   # «FIFA 365 2027», «World Cup 2026»
    if not m:
        for y in re.findall(r'\b20\d\d\b', s.get('season') or ''): toks.append(y)
    return sorted(set(toks), key=len, reverse=True)
def num_hit(title, n):
    n = str(n).lstrip('0') or '0'
    t = ' ' + re.sub(r'[#nº°]', ' ', title.lower()) + ' '
    return re.search(r'(?<![0-9a-z/])0*' + re.escape(n.lower()) + r'(?![0-9a-z])', t) is not None

def pick(items, s, player, nums, kws, stoks, siblings):
    """Anuncios que son de verdad de esta colección y este jugador"""
    sur = [w for w in words(player.split('/')[0]) if len(w) >= 3]
    key = sur[-1] if sur else norm(player)
    out = []
    for it in items:
        t = it.get('title') or ''
        if BAD.search(t): continue
        nt = norm(t)
        if key not in nt: continue
        if kws and not any(k in nt for k in kws): continue
        lt = t.lower().replace('–', '-')
        if siblings and stoks and not any(tok in lt for tok in stoks): continue     # hay otras temporadas de esta línea: el título tiene que decir cuál
        pr = it.get('price') or {}
        try: v = float(pr.get('value'))
        except Exception: continue
        if pr.get('currency') != 'EUR': continue
        img = ((it.get('image') or {}).get('imageUrl')) or (((it.get('thumbnailImages') or [{}])[0]).get('imageUrl'))
        out.append({'t': t, 'v': v, 'img': img, 'url': it.get('itemWebUrl') or '', 'nums': [n for n in nums if num_hit(t, n)]})
    return out

DEBUG = []
def main():
    cards = json.load(open(os.environ.get('CARDS', 'cards.json'), encoding='utf-8'))
    os.makedirs('ebay', exist_ok=True)
    st_path = 'ebay/_state.json'
    state = json.load(open(st_path)) if os.path.exists(st_path) else {'q': {}}
    for sid in [x for x in os.environ.get('RESET', '').split(',') if x]:   # volver a buscar una colección entera
        state['q'] = {k: v for k, v in state['q'].items() if not k.startswith(sid + '|')}   # se vuelve a buscar (lo ya encontrado se queda hasta entonces)
    lines = {}
    for s in cards: lines.setdefault(s['line'] or s['id'], []).append(s['id'])
    jobs = []   # (prioridad, colección, jugador)
    order = {s['id']: i for i, s in enumerate(cards)}
    for s in cards:
        if ONLY and s['id'] not in ONLY: continue
        players = {}
        for code, p, pn, t in s['cards']: players.setdefault(p.split('/')[0].strip(), []).append((code, pn))
        for p in players:
            last = state['q'].get(f"{s['id']}|{p}")
            age = 9999 if not last else (time.mktime(time.strptime(TODAY, '%Y-%m-%d')) - time.mktime(time.strptime(last, '%Y-%m-%d'))) / 86400
            if age < MAX_AGE: continue
            first = 0 if any(s['id'].startswith(f) for f in FIRST) else 1   # colecciones con prioridad (FIRST=mgk)
            jobs.append((first, 0 if not last else 1, -age, order[s['id']], s['id'], p, players[p]))
    jobs.sort()
    print(len(jobs), 'búsquedas pendientes; hoy como mucho', CALLS, flush=True)
    eb = Ebay(); by_set = {s['id']: s for s in cards}; out = {}; found = 0
    try:
        for _, _, _, _, sid, player, cs in jobs:
            if eb.calls >= CALLS: break
            s = by_set[sid]
            if sid not in out:
                f = f'ebay/{sid}.json'
                out[sid] = json.load(open(f)) if os.path.exists(f) else {'name': s['name'], 'c': {}}
            q = f"{s['q']} {player}"
            items = eb.search(q)
            if eb.calls <= 40: DEBUG.append({'q': q, 'n': len(items), 'titles': [(i.get('title'), (i.get('price') or {}).get('value'), (i.get('price') or {}).get('currency')) for i in items[:25]]})
            stoks = seasons_ok(s); sib = len(lines.get(s['line'] or sid, [])) > 1
            good = pick(items, s, player, [pn for _, pn in cs], s['kw'], stoks, sib)
            for code, pn in cs:
                # la carta concreta: anuncios con su número; si el jugador solo tiene una carta en la colección, todos
                mine = [g for g in good if pn in g['nums']] or (good if len(cs) == 1 else [])
                if not mine: out[sid]['c'].pop(code, None); continue
                vals = sorted(g['v'] for g in mine); med = round(statistics.median(vals), 2)
                best = min(mine, key=lambda g: abs(g['v'] - med))
                out[sid]['c'][code] = [med, len(mine), best['img'], best['url'], TODAY, round(vals[0], 2)]
                found += 1
            state['q'][f'{sid}|{player}'] = TODAY
            if eb.calls % 100 == 0: print(f'  {eb.calls} búsquedas, {found} cartas con precio', flush=True)
    except RuntimeError as e:
        print('Parada:', e, flush=True)
    for sid, d in out.items():
        d['v'] = TODAY
        json.dump(d, open(f'ebay/{sid}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(state, open(st_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    idx = {}
    for f in sorted(os.listdir('ebay')):
        if f.endswith('.json') and not f.startswith('_'):
            d = json.load(open('ebay/' + f)); idx[f[:-5]] = {'v': d.get('v'), 'n': len(d.get('c', {}))}
    json.dump(idx, open('ebay/_index.json', 'w'), separators=(',', ':'))
    if DEBUG: json.dump(DEBUG, open('ebay/_debug.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'Hecho: {eb.calls} búsquedas, {found} cartas con precio en esta pasada', flush=True)

if __name__ == '__main__': main()
