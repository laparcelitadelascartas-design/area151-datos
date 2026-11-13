#!/usr/bin/env python3
"""Huella de diseño de cada colección de fútbol, con las fotos de los anuncios de eBay.

Cuando el escáner lee el nombre de un jugador que sale en varias colecciones y no lee la colección,
los colores y la composición de la carta ayudan a elegir: cada colección tiene su diseño.
Por colección: hasta MAXN fotos → se busca la carta en la foto → 4x6 casillas con su color medio (Lab)
y un histograma de tonos. La huella es la mediana. Se guarda en design.json.

Con EVAL=1 además mide, dejando fuera cada foto, si la huella elige bien entre las colecciones en las
que sale ese mismo jugador (lo que el escáner tiene que decidir).
"""
import io, json, os, random, re, sys, time, urllib.request
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
MAXN = int(os.environ.get('MAXN', '40'))
GW, GH = 4, 6


def get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'AREA151Scan/1.0'}), timeout=timeout).read()


def card_crop(img):
    """La carta dentro de la foto (cuadrilátero más grande con forma de carta) enderezada a 320x440."""
    h, w = img.shape[:2]
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    e = cv2.dilate(cv2.Canny(g, 40, 120), np.ones((3, 3), np.uint8), iterations=2)
    cs, _ = cv2.findContours(e, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in sorted(cs, key=cv2.contourArea, reverse=True)[:6]:
        a = cv2.contourArea(c)
        if a < 0.2 * w * h: break
        p = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(p) == 4: best = p.reshape(4, 2).astype(np.float32); break
    if best is not None:
        s = best.sum(1); d = np.diff(best, axis=1).ravel()
        q = np.array([best[np.argmin(s)], best[np.argmin(d)], best[np.argmax(s)], best[np.argmax(d)]], np.float32)
        ww = np.linalg.norm(q[1] - q[0]); hh = np.linalg.norm(q[3] - q[0])
        if hh < ww: q = np.roll(q, -1, axis=0); ww, hh = hh, ww
        if 0.55 < ww / max(hh, 1) < 0.85:
            M = cv2.getPerspectiveTransform(q, np.array([[0, 0], [320, 0], [320, 440], [0, 440]], np.float32))
            return cv2.warpPerspective(img, M, (320, 440)), True
    # sin borde claro: el centro con forma de carta
    if w > h: img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE); h, w = w, h
    tw = min(w, int(h * 0.716)); th = int(tw / 0.716); x = (w - tw) // 2; y = (h - th) // 2
    return cv2.resize(img[max(0, y):y + th, x:x + tw], (320, 440)), False


def feat(card):
    """4x6 casillas de color medio (Lab, 0..1) + histograma de 12 tonos pesado por saturación."""
    lab = cv2.cvtColor(cv2.resize(card, (GW * 8, GH * 8), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2LAB).astype(np.float32) / 255.0
    grid = lab.reshape(GH, 8, GW, 8, 3).mean(axis=(1, 3)).ravel()
    hsv = cv2.cvtColor(cv2.resize(card, (80, 110), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV).astype(np.float32)
    hb = (hsv[..., 0] / 180.0 * 12).astype(int) % 12; wgt = (hsv[..., 1] / 255.0) * (hsv[..., 2] / 255.0)
    hist = np.bincount(hb.ravel(), weights=wgt.ravel(), minlength=12); hist = hist / (hist.sum() + 1e-6)
    return np.concatenate([grid, hist]).astype(np.float32)


def main():
    cards = json.load(open(os.path.join(ROOT, 'cards.json'), encoding='utf-8'))
    rnd = random.Random(151)
    F, names = {}, {}
    t0 = time.time()
    for s in cards:
        sid = s['id']; names[sid] = {c[0]: c[1] for c in s['cards']}
        fp = os.path.join(ROOT, 'ebay', sid + '.json')
        if not os.path.exists(fp): continue
        eb = json.load(open(fp, encoding='utf-8')).get('c', {})
        pool = [k for k, v in eb.items() if v and v[2] and (v[1] or 0) >= 2] or [k for k, v in eb.items() if v and v[2]]
        rnd.shuffle(pool); got = []
        for code in pool[:MAXN * 2]:
            if len(got) >= MAXN: break
            try:
                b = get(re.sub(r's-l\d+\.', 's-l500.', eb[code][2]))
                img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
                if img is None or min(img.shape[:2]) < 150: continue
                c, ok = card_crop(img)
                got.append((code, feat(c), ok))
            except Exception:
                continue
        if got: F[sid] = got
        print(sid, len(got), 'fotos', sum(1 for g in got if g[2]), 'con borde', f'{time.time() - t0:.0f}s', flush=True)
    allv = np.array([f for g in F.values() for _, f, _ in g]); sd = allv.std(0) + 1e-3
    out = {'v': time.strftime('%Y-%m-%d'), 'gw': GW, 'gh': GH, 'sd': [round(float(x), 4) for x in sd],
           'sets': {sid: [round(float(x), 4) for x in np.median(np.array([f for _, f, _ in g]), 0)] for sid, g in F.items() if len(g) >= 5}}
    json.dump(out, open(os.path.join(ROOT, 'design.json'), 'w'), separators=(',', ':'))
    print('design.json:', len(out['sets']), 'colecciones')
    if os.environ.get('EVAL'):
        # dejando fuera cada foto: ¿la huella elige bien entre las colecciones en que sale ese jugador?
        norm = lambda n: re.sub(r'[^a-z]', '', n.lower())
        byname = {}
        for sid, nm in names.items():
            for code, n in nm.items(): byname.setdefault(norm(n.split('/')[0]), set()).add(sid)
        med = {sid: np.median(np.array([f for _, f, _ in g]), 0) for sid, g in F.items()}
        tot = ok = 0; per = {}
        for sid, g in F.items():
            arr = np.array([f for _, f, _ in g])
            for i, (code, f, _) in enumerate(g):
                cand = [x for x in byname.get(norm(names[sid][code].split('/')[0]), set()) if x in med]
                if len(cand) < 2: continue
                loo = np.median(np.delete(arr, i, 0), 0) if len(arr) > 2 else med[sid]
                dist = {x: float(np.abs((f - (loo if x == sid else med[x])) / sd).mean()) for x in cand}
                hit = min(dist, key=dist.get) == sid
                tot += 1; ok += hit; per.setdefault(sid, [0, 0]); per[sid][0] += hit; per[sid][1] += 1
        print(f'EVAL: {ok}/{tot} = {100 * ok / max(1, tot):.0f} % eligiendo entre las colecciones del mismo jugador')
        for sid, (a, b) in sorted(per.items()): print(f'  {sid:14} {a}/{b}')


if __name__ == '__main__':
    main()
