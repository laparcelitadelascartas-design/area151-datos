#!/usr/bin/env python3
"""AREA151 Scan · fotos y precios de cartas de fútbol desde la API oficial de eBay (Browse API).
- Busca anuncios activos en eBay España de cada jugador de cada colección (cards.json) y guarda, por carta:
  precio mediano en euros, número de anuncios, foto del anuncio que mejor encaja, enlace y fecha → ebay/<colección>.json
- Las claves (EBAY_APP_ID, EBAY_CERT_ID) son secretos del repositorio: nunca se escriben en ningún archivo.
- Cada noche gasta como mucho CALLS búsquedas (eBay da 5.000 al día; antes de empezar mira cuántas quedan): primero las colecciones de FIRST, luego las cartas nunca buscadas y luego las más antiguas.
Solo librería estándar."""
import base64, json, os, re, statistics, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
CALLS = int(os.environ.get('CALLS', '4990'))
MAX_AGE = int(os.environ.get('MAX_AGE_DAYS', '10'))
ONLY = os.environ.get('ONLY', '').split(',') if os.environ.get('ONLY') else []
MARKET = os.environ.get('MARKET', 'EBAY_ES')
FIRST = [x for x in os.environ.get('FIRST', 'mgk').split(',') if x]
TODAY = time.strftime('%Y-%m-%d')
API = 'https://api.ebay.com'
STALE = int(os.environ.get('STALE_DAYS', '30'))   # un precio sin anuncios activos se deja de mostrar a los 30 días (la foto se queda)
LANG = {'EBAY_ES': 'es-ES', 'EBAY_IT': 'it-IT', 'EBAY_DE': 'de-DE', 'EBAY_FR': 'fr-FR', 'EBAY_GB': 'en-GB', 'EBAY_US': 'en-US'}
# segunda pasada, solo para las cartas que aún no tienen foto: otra búsqueda en España y luego otros eBay (los que no son en euros, solo para la foto)
ALT = [('EBAY_ES', 'corta'), ('EBAY_IT', 'llena'), ('EBAY_FR', 'llena'), ('EBAY_DE', 'llena'), ('EBAY_GB', 'llena'), ('EBAY_US', 'llena')]

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
    def quota(self):
        """Búsquedas que quedan hoy y cuándo se renueva el cupo (Developer Analytics API; no gasta búsquedas)"""
        u = API + '/developer/analytics/v1_beta/rate_limit/?' + urllib.parse.urlencode({'api_context': 'buy', 'api_name': 'browse'})
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'Bearer ' + self.token()}), timeout=30).read())
            for a in d.get('rateLimits', []):
                for r in a.get('resources', []):
                    if 'search' in r.get('name', '') or r.get('name') == 'buy.browse':
                        x = (r.get('rates') or [{}])[0]
                        return x.get('remaining'), x.get('limit'), x.get('reset')
        except Exception as e: print('  cupo de eBay desconocido:', e, flush=True)
        return None, None, None
    def search(self, q, limit=200, market=None):
        self.calls += 1; time.sleep(0.12)
        market = market or MARKET
        u = API + '/buy/browse/v1/item_summary/search?' + urllib.parse.urlencode({'q': q, 'limit': limit})
        req = urllib.request.Request(u, headers={'Authorization': 'Bearer ' + self.token(), 'X-EBAY-C-MARKETPLACE-ID': market, 'Accept-Language': LANG.get(market, 'es-ES')})
        for attempt in range(3):
            try: return json.loads(urllib.request.urlopen(req, timeout=30).read()).get('itemSummaries', [])
            except urllib.error.HTTPError as e:
                if e.code == 429: raise RuntimeError('límite diario de eBay')
                if e.code in (500, 502, 503, 504): time.sleep(3 * (attempt + 1)); continue
                print('  error', e.code, q, e.read()[:200], flush=True); return []
            except Exception as e: print('  error', e, flush=True); time.sleep(3)
        return []

BAD = re.compile(r'\b(psa|bgs|sgc|cgc|beckett|graded|gradead[ao]|slab|lote|lot|lots|bundle|pack|sobre|sobres|caja|box|blaster|hobby|tin|album|álbum|set completo|complete set|colecci[oó]n|completa|elige|choose|pick|select your|you pick|a elegir|escoge|a escoger|tu elecci[oó]n|lotto|scegli|a scelta|bustin[ae]|konvolut|sammlung|auswahl|aussuchen|au choix|lot de|faltas|missing|sueltas|discount|todas las ediciones|todos los cromos|repes|duplicad[ao]s|x\s?\d{1,3}|\d{1,3}\s?x|\d+\s?(cartas|cards|cromos)|(cartas|cards|cromos)\s?\d+)\b', re.I)
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
        eur = pr.get('currency') == 'EUR'
        img = ((it.get('image') or {}).get('imageUrl')) or (((it.get('thumbnailImages') or [{}])[0]).get('imageUrl'))
        if not img: continue
        out.append({'t': t, 'v': v, 'eur': eur, 'img': img, 'url': it.get('itemWebUrl') or '', 'nums': [n for n in nums if num_hit(t, n)]})
    return out

BASEISH = {'laliga', 'liga', 'base', 'coleccion', 'bis', 'ficha', 'fichas', 'fichaje', 'fichajes', 'equipo', 'equipos', 'spain', 'espana', 'nuevas', 'nuevos', 'nueva', 'nuevo', 'las', 'los', 'del', 'con', 'mgk', 'cards', 'card'}
SPECIAL = {'power', 'elite', 'vip', 'rookie', 'novato', 'flash', 'flashback', 'limitada', 'autografo', 'firma', 'firmado', 'auto', 'special', 'iconos', 'icono', 'mvp', 'vertigo', 'fuego', 'magicos', 'evolution', 'golden', 'oro', 'gold', 'anthology', 'master', 'stars', 'enjoy', 'black', 'just', 'status', 'mega', 'parallel', 'paralelo', 'futuro'}
def spec(sec): return frozenset(w for w in words(sec) if w not in BASEISH and len(w) >= 3)
def other_series(title, cs, code):
    """El título nombra una serie de otra carta del mismo jugador que esta no tiene (Power en una Élite normal…)"""
    tw = set(words(title)); mine = next((spec(sec) for c, _, sec in cs if c == code), frozenset())
    return any(spec(sec) - mine and (spec(sec) - mine) <= tw for c, _, sec in cs if c != code)
def by_series(title, cs):
    """Carta del jugador a la que se refiere un anuncio sin número, por la serie que nombra el título"""
    tw = set(words(title))
    hit = [(len(spec(sec)), code) for code, _, sec in cs if spec(sec) and spec(sec) <= tw]
    if hit:
        top = max(h for h, _ in hit); best = [c for h, c in hit if h == top]
        return best[0] if len(best) == 1 else None
    if tw & SPECIAL: return None                       # dice una serie especial que no es de este jugador: mejor nada
    base = [code for code, _, sec in cs if not spec(sec)]
    return base[0] if len(base) == 1 else None

DEBUG = []
def days(d):
    try: return (time.mktime(time.strptime(TODAY, '%Y-%m-%d')) - time.mktime(time.strptime(d, '%Y-%m-%d'))) / 86400
    except Exception: return 9999
def search_player(eb, s, player, cs, q, market, have, lines, fill_only=False):
    """Busca un jugador de una colección y apunta en `have` (código → [mediana €, anuncios, foto, enlace, fecha, mínimo €]) lo encontrado.
    fill_only: solo cartas sin foto (segunda pasada). Una foto ya encontrada no se borra nunca; el precio sin anuncios activos caduca a los STALE días."""
    items = eb.search(q, market=market)
    if eb.calls <= 40: DEBUG.append({'q': q, 'm': market, 'n': len(items), 'titles': [(i.get('title'), (i.get('price') or {}).get('value'), (i.get('price') or {}).get('currency')) for i in items[:25]]})
    stoks = seasons_ok(s); sib = len(lines.get(s['line'] or s['id'], [])) > 1
    good = pick(items, s, player, [pn for _, pn, _ in cs], s['kw'], stoks, sib)
    if fill_only:   # búsqueda más abierta: el anuncio tiene que llevar el número o el nombre entero (no vale otro «Rodríguez»)
        full = [w for w in words(player.split('/')[0]) if len(w) >= 3]
        good = [g for g in good if g['nums'] or all(w in norm(g['t']) for w in full)]
    n = 0
    for code, pn, _ in cs:
        old = have.get(code)
        if fill_only and old and old[2]: continue
        # la carta concreta: anuncios con su número; si el jugador solo tiene una carta en la colección, todos;
        # si tiene varias, los anuncios sin número que nombran la serie de esta carta (Élite, Power, Zona VIP…)
        mine = [g for g in good if pn in g['nums'] and not other_series(g['t'], cs, code)] or (good if len(cs) == 1 else [g for g in good if not g['nums'] and by_series(g['t'], cs) == code])
        if not mine:
            if old and old[0] and days(old[4]) > STALE: have[code] = [0, 0, old[2], old[3], old[4], 0]   # sin anuncios desde hace tiempo: foto sí, precio no
            continue
        eur = [g for g in mine if g['eur']]
        if eur:
            vals = sorted(g['v'] for g in eur); med = round(statistics.median(vals), 2)
            best = min(eur, key=lambda g: abs(g['v'] - med))
            have[code] = [med, len(eur), best['img'], best['url'], TODAY, round(vals[0], 2)]
        else:
            best = mine[0]
            have[code] = [old[0], old[1], best['img'], best['url'], old[4], old[5]] if old else [0, 0, best['img'], best['url'], TODAY, 0]
        n += 1
    return n

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
        for code, p, pn, t, *sec in s['cards']: players.setdefault(p.split('/')[0].strip(), []).append((code, pn, sec[0] if sec else ''))
        for p in players:
            last = state['q'].get(f"{s['id']}|{p}")
            age = 9999 if not last else (time.mktime(time.strptime(TODAY, '%Y-%m-%d')) - time.mktime(time.strptime(last, '%Y-%m-%d'))) / 86400
            if age < MAX_AGE: continue
            first = 0 if any(s['id'].startswith(f) for f in FIRST) else 1   # colecciones con prioridad (FIRST=mgk)
            jobs.append((first, 0 if not last else 1, -age, order[s['id']], s['id'], p, players[p]))
    jobs.sort()
    print(len(jobs), 'búsquedas pendientes; hoy como mucho', CALLS, flush=True)
    eb = Ebay(); by_set = {s['id']: s for s in cards}; out = {}; found = 0
    left, lim, reset = eb.quota()
    print(f'Cupo de eBay: quedan {left} de {lim}; se renueva {reset}', flush=True)
    budget = CALLS if left is None else min(CALLS, max(0, int(left) - 10))
    def book(sid):
        if sid not in out:
            f = f'ebay/{sid}.json'
            out[sid] = json.load(open(f)) if os.path.exists(f) else {'name': by_set[sid]['name'], 'c': {}}
        return out[sid]['c']
    def missing(phase):
        """Jugadores con alguna carta aún sin foto → otra búsqueda u otro eBay (uno distinto cada día)"""
        res = []
        for s in cards:
            if ONLY and s['id'] not in ONLY: continue
            if (0 if any(s['id'].startswith(x) for x in FIRST) else 1) != phase: continue
            have = book(s['id']); players = {}
            for code, p, pn, t, *sec in s['cards']: players.setdefault(p.split('/')[0].strip(), []).append((code, pn, sec[0] if sec else ''))
            for p, cs in players.items():
                if all(have.get(c) and have[c][2] for c, _, _ in cs): continue
                nxt = [i for i in range(len(ALT)) if str(i) not in state['alt'].get(f"{s['id']}|{p}", [])]
                if nxt: res.append((s['id'], p, cs, nxt[0]))
        return res
    state.setdefault('alt', {})
    try:
        # primero las colecciones de FIRST (búsqueda normal y luego la segunda pasada), después el resto igual
        for phase in (0, 1):
            for first, _, _, _, sid, player, cs in jobs:
                if first != phase: continue
                if eb.calls >= budget: break
                s = by_set[sid]
                found += search_player(eb, s, player, cs, f"{s['q']} {player}", 'EBAY_ES', book(sid), lines)
                state['q'][f'{sid}|{player}'] = TODAY
                if eb.calls % 100 == 0: print(f'  {eb.calls} búsquedas, {found} cartas encontradas', flush=True)
            if eb.calls >= budget: break
            miss = missing(phase)
            print(len(miss), 'jugadores con cartas sin foto (' + ('prioritarias' if phase == 0 else 'resto') + '): segunda pasada', flush=True)
            for sid, player, cs, i in miss:
                if eb.calls >= budget: break
                s = by_set[sid]; market, how = ALT[i]
                sur = [w for w in re.split(r'\s+', player) if len(w) >= 3]
                q = f"{s['q']} {sur[-1] if (how == 'corta' and sur) else player}"
                found += search_player(eb, s, player, cs, q, market, book(sid), lines, fill_only=True)
                state['alt'].setdefault(f'{sid}|{player}', []).append(str(i))
    except RuntimeError as e:
        print('Parada:', e, flush=True)
    for sid, d in out.items():
        d['v'] = TODAY
        json.dump(d, open(f'ebay/{sid}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(state, open(st_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    idx = {}
    for f in sorted(os.listdir('ebay')):
        if f.endswith('.json') and not f.startswith('_'):
            d = json.load(open('ebay/' + f)); c = d.get('c', {})
            idx[f[:-5]] = {'v': d.get('v'), 'n': sum(1 for x in c.values() if x[2]), 'p': sum(1 for x in c.values() if x[0])}
    json.dump(idx, open('ebay/_index.json', 'w'), separators=(',', ':'))
    if DEBUG: json.dump(DEBUG, open('ebay/_debug.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'Hecho: {eb.calls} búsquedas, {found} cartas encontradas en esta pasada', flush=True)

if __name__ == '__main__': main()
