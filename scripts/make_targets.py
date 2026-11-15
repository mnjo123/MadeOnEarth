#!/usr/bin/env python
"""
make_targets.py - Crea targets.txt con la posicion ACTUAL de cada objeto.

Por que: Barnard's Star, WISE 0855 y eps Indi B se mueven varios segundos de
arco por ano. Sus coordenadas de catalogo ya estan a minutos de arco de donde
SPHEREx los vio, asi que un recorte centrado ahi saldria vacio.

No necesita internet: usa posiciones y movimientos propios de catalogo
(abajo) y calcula donde estaba cada objeto a mitad de los datos de SPHEREx.

Uso:    python scripts/make_targets.py
Salida: targets.txt (formato que espera get_cutouts_spherex.py)
"""
import warnings

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

warnings.filterwarnings("ignore")      # avisos de ERFA por fechas futuras: inofensivos

EPOCA = 2025.9                         # mitad de los datos publicados de SPHEREx

# carpeta: (RA grados, Dec grados, epoca de esa posicion,
#           mov. propio RA*cos(Dec) mas/ano, mov. propio Dec mas/ano, fuente)
OBJETOS = {
    "barnard":    (269.452075, 4.693391, 2000.0,  -801.6, 10362.4, "Gaia DR3 llevado a J2000"),
    "eps_indi_b": (331.043833, -56.782694, 2000.0, 3982.0, -2566.0, "Scholz et al. 2003"),
    "wise0855":   (133.795125, -7.245139, 2010.5, -8118.0,   673.0, "AllWISE; Luhman 2014"),
    "rw_aur":     (76.956417, 30.401417, 2000.0,      0.0,     0.0, "SIMBAD (mov. propio despreciable)"),
    "r_dra":      (248.167417, 66.755000, 2000.0,     0.0,     0.0, "SIMBAD (mov. propio despreciable)"),
}

lineas = ["name ra dec"]
for carpeta, (ra, dec, ep, pmra, pmdec, fuente) in OBJETOS.items():
    c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg,
                 pm_ra_cosdec=pmra * u.mas / u.yr, pm_dec=pmdec * u.mas / u.yr,
                 obstime=Time(ep, format="jyear"), frame="icrs")
    hoy = c.apply_space_motion(new_obstime=Time(EPOCA, format="jyear"))
    salto = c.separation(hoy).arcsec
    print(f"{carpeta:11s} RA {hoy.ra.deg:10.5f}  Dec {hoy.dec.deg:+9.5f}   "
          f"(se movio {salto:6.1f}\" desde {ep:.0f})")
    lineas.append(f"{carpeta} {hoy.ra.deg:.6f} {hoy.dec.deg:.6f}")

with open("targets.txt", "w") as fh:
    fh.write("\n".join(lineas) + "\n")
print("Listo: targets.txt")
