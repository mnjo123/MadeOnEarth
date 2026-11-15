#!/usr/bin/env python
"""
make_frames.py - Convierte recortes FITS de SPHEREx en PNG nitidos, ALINEADOS
y comparables entre fechas, mas un frames.json que la interfaz carga.

Que hace con cada imagen:
  1. La reproyecta a una cuadricula comun "norte arriba, este a la izquierda"
     centrada en --ra/--dec (usa el WCS del FITS; paquete reproject, BSD-3).
     SPHEREx gira entre barridos: sin esto las estrellas no coinciden.
  2. Le resta el fondo (luz zodiacal), que cambia segun la epoca del ano.
  3. Rellena los pixeles sin dato con el nivel del fondo.
  4. Aplica un estiramiento asinh con el MISMO corte para todas las fechas de
     un detector, para que solo cambie lo que de verdad cambio.
  5. Se queda con la mejor imagen de cada fecha y detector.

Uso:
  python scripts/make_frames.py --input cutouts --match "wise0855_*.fits" \
      --output web/data/wise0855 --name "WISE 0855" --ra 133.760 --dec -7.242

Requisitos: astropy, numpy, pillow, reproject
"""
import argparse
import glob
import json
import os
import warnings

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.time import Time
from astropy.wcs import WCS
from PIL import Image

warnings.filterwarnings("ignore")

try:
    from reproject import reproject_interp
except ImportError:
    raise SystemExit("Falta el paquete 'reproject'. Instalalo con:  pip install reproject")


def find_ext(hdul, names, default=None):
    for h in hdul:
        if h.header.get("EXTNAME", "").upper() in names and h.data is not None:
            return h
    return hdul[default] if default is not None and len(hdul) > default else None


def wcs_destino(ra, dec, fov_deg, escala_arcsec):
    n = int(round(fov_deg * 3600 / escala_arcsec))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-escala_arcsec / 3600, escala_arcsec / 3600]
    return w, (n, n)


def read_frame(path, w_out, shape_out):
    with fits.open(path, memmap=False) as hdul:
        img_hdu = find_ext(hdul, {"IMAGE", "SCI"}, default=1)
        img = np.array(img_hdu.data, dtype=float)
        hdr_img = img_hdu.header
        hdr = {**hdul[0].header, **hdr_img}

    date = None
    for key in ("DATE-OBS", "DATE-BEG", "DATE_OBS", "DATE-AVG"):
        if key in hdr:
            try:
                date = Time(hdr[key]).isot[:10]
                break
            except Exception:
                pass
    if date is None:
        for key in ("MJD-OBS", "MJD-BEG", "MJD-AVG", "MJD_OBS"):
            if key in hdr:
                date = Time(float(hdr[key]), format="mjd").isot[:10]
                break

    det = hdr.get("DETECTOR")
    if isinstance(det, (int, np.integer)):
        det = f"D{det}"
    elif isinstance(det, str) and det.strip().isdigit():
        det = f"D{det.strip()}"
    det = det or "D?"

    # Pixeles sin dato valido -> NaN para que no se mezclen al reproyectar
    img[~np.isfinite(img) | (img == 0)] = np.nan

    rep, foot = reproject_interp((img, WCS(hdr_img).celestial), w_out, shape_out=shape_out, order="bilinear")
    rep[foot == 0] = np.nan
    cubierto = float(np.mean(np.isfinite(rep)))
    if cubierto < 0.5:
        raise ValueError(f"el objeto queda fuera o en el borde del recorte ({cubierto:.0%} cubierto)")

    _, fondo, ruido = sigma_clipped_stats(rep[np.isfinite(rep)], sigma=3)
    rep = rep - fondo
    rep[~np.isfinite(rep)] = 0.0             # sin dato = nivel del fondo

    calidad = "buena" if cubierto > 0.95 else "aviso" if cubierto > 0.8 else "mala"
    return {"path": path, "img": rep, "date": date or "desconocida", "detector": det,
            "ruido": float(ruido), "cubierto": cubierto, "calidad": calidad}


def asinh_png(x, vmin, vmax, a):
    t = np.clip((x - vmin) / (vmax - vmin), 0, 1)
    return np.arcsinh(t / a) / np.arcsinh(1 / a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Carpeta con los recortes .fits")
    ap.add_argument("--match", default="*.fits", help='Que archivos usar, ej. "wise0855_*.fits"')
    ap.add_argument("--output", required=True, help="Carpeta de salida (PNG + frames.json)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--ra", type=float, required=True, help="Centro (grados); usa el de targets.txt")
    ap.add_argument("--dec", type=float, required=True)
    ap.add_argument("--fov", type=float, default=0.028, help="Campo en grados (default 0.028 = 1.7')")
    ap.add_argument("--escala", type=float, default=3.0, help="Segundos de arco por pixel de salida")
    ap.add_argument("--size", type=int, default=480, help="Lado del PNG en pixeles")
    ap.add_argument("--percentile", type=float, default=99.7, help="Brillo que se vuelve blanco")
    ap.add_argument("--asinh", type=float, default=0.1, help="Menor = mas contraste en lo tenue")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.input, args.match)))
    if not files:
        raise SystemExit(f"No hay archivos {args.match} en {args.input}")
    os.makedirs(args.output, exist_ok=True)
    for viejo in glob.glob(os.path.join(args.output, "*.png")):
        os.remove(viejo)

    w_out, shape = wcs_destino(args.ra, args.dec, args.fov, args.escala)
    frames = []
    for f in files:
        try:
            frames.append(read_frame(f, w_out, shape))
        except Exception as e:
            print(f"  salto {os.path.basename(f)}: {e}")
    if not frames:
        raise SystemExit("Ningun archivo se pudo usar")

    mejor = {}
    for f in frames:
        k = (f["date"], f["detector"])
        if k not in mejor or (f["cubierto"], -f["ruido"]) > (mejor[k]["cubierto"], -mejor[k]["ruido"]):
            mejor[k] = f
    print(f"{len(files)} archivos -> {len(frames)} utiles -> {len(mejor)} fechas/detector distintas")
    frames = list(mejor.values())

    cortes = {}
    for det in sorted({f["detector"] for f in frames}):
        sel = [f for f in frames if f["detector"] == det]
        ruido = float(np.median([f["ruido"] for f in sel]))
        alto = float(np.percentile(np.concatenate([f["img"].ravel() for f in sel]), args.percentile))
        cortes[det] = (-2 * ruido, max(alto, 8 * ruido))

    out = []
    for f in sorted(frames, key=lambda f: (f["detector"], f["date"])):
        vmin, vmax = cortes[f["detector"]]
        g = asinh_png(f["img"], vmin, vmax, args.asinh)
        png = Image.fromarray((g * 255).astype(np.uint8)[::-1])     # norte arriba
        png = png.resize((args.size, args.size), Image.NEAREST)
        name = f"{f['date']}_{f['detector']}_{os.path.splitext(os.path.basename(f['path']))[0][-12:]}.png"
        png.save(os.path.join(args.output, name), optimize=True)
        out.append({"fecha": f["date"], "detector": f["detector"], "png": name, "calidad": f["calidad"],
                    "cobertura": round(f["cubierto"], 3), "ruido": round(f["ruido"], 4)})

    meta = {"objeto": args.name, "ra": args.ra, "dec": args.dec,
            "orientacion": "norte arriba, este a la izquierda",
            "campo_arcmin": round(args.fov * 60, 2), "escala_arcsec_px": args.escala,
            "estiramiento": f"fondo restado; asinh({args.asinh}); corte comun por detector",
            "frames": out}
    with open(os.path.join(args.output, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f"{len(out)} imagenes -> {args.output}/frames.json")


if __name__ == "__main__":
    main()
