# AREA151 · datos

Datos públicos que usa la app AREA151 Scan para las cartas de fútbol: foto y precio de anuncios activos de eBay España, buscados cada noche con la API oficial de eBay (Browse API).

- `cards.json`: las cartas que se buscan (generado desde los listados de la app con `tools/make_cards.py`).
- `ebay/<colección>.json`: por carta, `[precio mediano €, nº de anuncios, foto, enlace al anuncio, fecha, precio más bajo €]`.
- Las claves de eBay están guardadas como secretos del repositorio (`EBAY_APP_ID`, `EBAY_CERT_ID`) y no aparecen en ningún archivo.

Son precios de lo que se pide en anuncios activos, no de ventas cerradas.
