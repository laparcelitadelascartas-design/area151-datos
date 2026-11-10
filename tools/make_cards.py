#!/usr/bin/env python3
"""Genera cards.json (lo que se busca en eBay) a partir de www/catalog.js de la app.
Uso: python3 tools/make_cards.py ruta/a/catalog.js"""
import json, re, sys
src = open(sys.argv[1], encoding='utf-8').read()
cat = json.loads(src.split('=', 1)[1].strip().rstrip(';'))
def core(name):
    q = re.sub(r'\b20\d\d(-\d\d)?\b', '', name)                  # años fuera de la búsqueda: se comprueban en el título
    q = q.replace('Stadium Club Chrome UEFA Champions League', 'Stadium Club Chrome')
    q = re.sub(r'\((cromos)\)', 'sticker', q)
    for w in ['XL', 'FIFA', 'Club Competitions', 'Road to', 'Panini', 'Topps', 'LaLiga Este']:
        q = re.sub(r'\b' + re.escape(w) + r'\b', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    if name.startswith('LaLiga Este'): q = 'liga este'
    if name.startswith('Topps') and 'Match' not in name: q = 'topps ' + q
    return q.lower()
out = []
for s in cat['sets']:
    teams = s.get('teams') or []
    cards = []
    for c in s['cards']:
        p = c['p']; t = c.get('t'); t = teams[t] if isinstance(t, int) and t < len(teams) else (t or '')
        if re.match(r'^(escudo|team badge|badge|crest|emblem|checklist|index|índice)\b', p, re.I): continue
        cards.append([c['n'], p, c.get('pn') or c['n'], t])
    out.append({'id': s['id'], 'name': s['name'], 'line': s.get('line', ''), 'season': s.get('season', ''), 'kw': [k for k in s.get('kw', []) if k not in ('topps', 'fifa', 'worldcup')], 'q': core(s['name']), 'cards': cards})
json.dump(out, open('cards.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(out), 'colecciones,', sum(len(s['cards']) for s in out), 'cartas')
for s in out: print(f"  {s['id']:13} «{s['q']}»")
