#!/usr/bin/env python
"""
descargar_spherex.py - Descarga recortes pequenos de SPHEREx (IRSA) para cada
objeto de targets.txt, repartidos en el tiempo, con limite de espera.

Uso:
  python scripts/descargar_spherex.py                    # todos los objetos
  python scripts/descargar_spherex.py --solo wise0855    # solo uno
  python scripts/descargar_spherex.py --solo wise0855 --max 40 --size 0.04

Salida: cutouts/<objeto>_<archivo original>.fits
"""
import argparse
import gzip
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests  # usa sus propios certificados (evita CERTIFICATE_VERIFY_FAILED en Windows)

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa import Irsa

warnings.filterwarnings("ignore")


def leer_targets(path):
    filas = []
    with open(path) as fh:
        for linea in fh:
            p = linea.split()
            if len(p) >= 3 and p[0].lower() != "name":
                filas.append((p[0], float(p[1]), float(p[2])))
    return filas


def buscar(ra, dec):
    """Lista de imagenes SPHEREx que contienen el punto, ordenadas por fecha."""
    pos = (SkyCoord(ra, dec, unit="deg"), 1 * u.arcsec)
    for intento in (dict(collection="spherex_qr2"), dict(instrument="SPHEREx")):
        try:
            t = Irsa.query_sia(pos=pos, **intento)
        except Exception as e:
            print(f"   consulta {intento} fallo: {e}")
            continue
        if t is not None and len(t):
            cols = {c.lower(): c for c in t.colnames}
            urls = [str(u_) for u_ in t[cols["access_url"]]]
            tmin = np.array(t[cols["t_min"]], dtype=float) if "t_min" in cols else np.arange(len(urls), dtype=float)
            orden = np.argsort(tmin)
            vistos, res = set(), []
            solo_l2 = any("level2" in x for x in urls)
            for i in orden:                      # quitar duplicados y cubos (solo imagenes level2)
                if solo_l2 and "level2" not in urls[i]:
                    continue
                if urls[i] not in vistos:
                    vistos.add(urls[i]); res.append((tmin[i], urls[i]))
            print(f"   {len(res)} imagenes encontradas ({intento})")
            return res
    return []


def repartir(lista, n):
    """Elige n elementos repartidos a lo largo del tiempo (no los primeros n)."""
    if n <= 0 or len(lista) <= n:
        return lista
    idx = np.unique(np.linspace(0, len(lista) - 1, n).round().astype(int))
    return [lista[i] for i in idx]


def url_recorte(url, ra, dec, size):
    if url.startswith("/"):
        url = "https://irsa.ipac.caltech.edu" + url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}center={ra:.6f},{dec:.6f}&size={size}"


def bajar(url, destino, timeout, reintentos=2):
    for k in range(reintentos + 1):
        try:
            r = requests.get(url, headers={"User-Agent": "MadeOnEarth-SpaceApps"}, timeout=timeout)
            if r.status_code in (400, 404, 422):
                return f"HTTP {r.status_code}"
            if r.status_code != 200:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            datos = r.content
            if datos[:2] == b"\x1f\x8b":           # a veces IRSA lo manda comprimido
                datos = gzip.decompress(datos)
            if len(datos) < 2880 or not datos.startswith(b"SIMPLE"):
                return f"respuesta no es FITS ({len(datos)} bytes)"
            with open(destino, "wb") as fh:
                fh.write(datos)
            return None
        except (requests.RequestException, OSError) as e:
            err = str(e)[:200]
        time.sleep(2 * (k + 1))
    return err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="targets.txt")
    ap.add_argument("--solo", help="Nombre de un objeto de targets.txt (ej. wise0855)")
    ap.add_argument("--out", default="cutouts")
    ap.add_argument("--size", type=float, default=0.04, help="Lado del recorte en grados (0.04 = 2.4')")
    ap.add_argument("--max", type=int, default=40, help="Maximo de imagenes por objeto (0 = todas)")
    ap.add_argument("--timeout", type=int, default=60, help="Segundos maximos de espera por archivo")
    ap.add_argument("--hilos", type=int, default=4, help="Descargas en paralelo")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    objetos = [o for o in leer_targets(args.targets) if not args.solo or o[0] == args.solo]
    if not objetos:
        raise SystemExit(f"No encontre '{args.solo}' en {args.targets}")

    for nombre, ra, dec in objetos:
        print(f"\n== {nombre}  (RA {ra:.5f}, Dec {dec:+.5f})")
        imgs = repartir(buscar(ra, dec), args.max)
        if not imgs:
            print("   Sin datos de SPHEREx aqui (o IRSA no respondio).")
            continue
        tareas = {}
        with ThreadPoolExecutor(args.hilos) as ex:
            for _, url in imgs:
                base = url.split("?")[0].rstrip("/").split("/")[-1]
                destino = os.path.join(args.out, f"{nombre}_{base}")
                if os.path.exists(destino):
                    continue
                tareas[ex.submit(bajar, url_recorte(url, ra, dec, args.size), destino, args.timeout)] = base
            ok = fallos = 0
            for i, fut in enumerate(as_completed(tareas), 1):
                err = fut.result()
                if err:
                    fallos += 1
                    print(f"   [{i}/{len(tareas)}] x {tareas[fut]}: {err}")
                else:
                    ok += 1
                    print(f"   [{i}/{len(tareas)}] ok {tareas[fut]}")
        print(f"   Resultado {nombre}: {ok} descargados, {fallos} fallidos, "
              f"{len(imgs) - len(tareas)} ya existian")


if __name__ == "__main__":
    main()
