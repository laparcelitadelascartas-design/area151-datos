#!/usr/bin/env python3
"""Fotos pequeñas de las cartas de Yu-Gi-Oh! alojadas aquí, como pide YGOPRODeck (no enlazar sus imágenes).

Baja el listado de cartas de YGOPRODeck y descarga solo las fotos que aún no están en ygo/img/<id>.jpg
(una por ilustración, también las alternativas), sin pasar de 8 por segundo y con un tiempo máximo.
La app las coge de raw.githubusercontent.com por el id de la carta.

Variables: YGO_MIN (minutos como mucho, 45 por defecto).
"""
import json, os, sys, time, urllib.request

API = 'https://db.ygoprodeck.com/api/v7/cardinfo.php'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ygo', 'img')
UA = {'User-Agent': 'AREA151Scan/1.0 (+https://scan.area151.es)'}


def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def main():
    os.makedirs(OUT, exist_ok=True)
    stop = time.time() + 60 * float(os.environ.get('YGO_MIN', '45'))
    data = json.loads(get(API, 180)).get('data', [])
    want = {}
    for d in data:
        for im in d.get('card_images') or []:
            if im.get('id') and im.get('image_url_small'): want[str(im['id'])] = im['image_url_small']
    have = {f[:-4] for f in os.listdir(OUT) if f.endswith('.jpg')}
    todo = [(k, u) for k, u in want.items() if k not in have]
    print(len(data), 'cartas,', len(want), 'ilustraciones,', len(have), 'ya están,', len(todo), 'por bajar', flush=True)
    got = bad = 0
    for k, u in todo:
        if time.time() > stop: print('tiempo agotado', flush=True); break
        t0 = time.time()
        try:
            b = get(u, 30)
            if len(b) > 1500 and b[:2] == b'\xff\xd8':
                open(os.path.join(OUT, k + '.jpg'), 'wb').write(b); got += 1
            else: bad += 1
        except Exception as e:
            bad += 1
            if bad > 200 and got == 0: sys.exit('no se puede bajar ninguna foto: ' + str(e))
        if got and got % 1000 == 0: print(got, 'bajadas', flush=True)
        time.sleep(max(0, 0.125 - (time.time() - t0)))
    print('bajadas', got, 'fallos', bad, 'faltan', len(todo) - got - bad, flush=True)


if __name__ == '__main__':
    main()
