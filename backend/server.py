from __future__ import annotations

import io
import json
import os
import uuid
import gzip
import tempfile
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from astropy.io import fits
from astropy.table import Table
from astropy.time import Time
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
import numpy as np
from PIL import Image
from reproject import reproject_interp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
IRSA_RETRY_ATTEMPTS = 10
IRSA_RETRY_BACKOFF_S = 2.0
COLLECTIONS = {
    "spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep"
}
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "CieloEnMovimiento/1.1 (educational SPHEREx viewer)"})
OBSERVATIONS: dict[str, dict[str, Any]] = {}
TRACKS: dict[str, Path] = {}
TRACK_DATA: dict[str, list[dict[str, Any]]] = {}
DEMO_ROOT = FRONTEND_DIR / "demo" / "real-motion"
PRELOADED_TRACKS: list[dict[str, Any]] = []

app = FastAPI(title="Sky in Motion · SPHEREx API", version="1.1.0")

origins_setting = os.getenv("CORS_ORIGINS", "*")
allowed_origins = [item.strip() for item in origins_setting.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/config.js")
def config_script():
    return FileResponse(FRONTEND_DIR / "config.js", media_type="application/javascript")


@app.get("/spherex-integration.js")
def integration_script():
    return FileResponse(FRONTEND_DIR / "spherex-integration.js", media_type="application/javascript")


@app.get("/health")
def health():
    return {"status": "ok", "service": "Sky in Motion · SPHEREx API"}


def _row_value(row, names: list[str]):
    columns = {str(key).lower(): key for key in row.colnames}
    for name in names:
        key = columns.get(name.lower())
        if key is None:
            continue
        value = row[key]
        try:
            if getattr(value, "mask", False):
                continue
        except Exception:
            pass
        if value is not None:
            try:
                return value.item()
            except Exception:
                return value
    return None


def _clean(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _irsa_get(url: str, *, params: dict | None = None, timeout: tuple[float, float] = (20, 120)):
    """IRSA SIA and cutout endpoints often return a fast proxy 502, then a real response."""
    last_error = "IRSA did not respond."
    for attempt in range(IRSA_RETRY_ATTEMPTS):
        try:
            with requests.Session() as session:
                session.headers.update({
                    "User-Agent": "CieloEnMovimiento/1.1 (educational SPHEREx viewer)",
                    "Connection": "close",
                })
                response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"IRSA did not respond: {exc}"
            if attempt + 1 >= IRSA_RETRY_ATTEMPTS:
                raise RuntimeError(last_error) from exc
            time.sleep(IRSA_RETRY_BACKOFF_S * (attempt + 1))
            continue
        if response.status_code in {502, 503, 504}:
            last_error = (
                "IRSA could not return observations: its SIA service responded "
                f"{response.status_code} (the NASA proxy failed). This is not a CORS or local-backend error."
            )
            if attempt + 1 >= IRSA_RETRY_ATTEMPTS:
                raise RuntimeError(last_error)
            time.sleep(IRSA_RETRY_BACKOFF_S * (attempt + 1))
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            last_error = f"IRSA responded {response.status_code}."
            if attempt + 1 >= IRSA_RETRY_ATTEMPTS:
                raise RuntimeError(last_error) from exc
            time.sleep(IRSA_RETRY_BACKOFF_S * (attempt + 1))
            continue
        return response
    raise RuntimeError(last_error)


def _query_collection(collection: str, ra: float, dec: float, radius: float):
    params = {
        "COLLECTION": collection,
        "POS": f"circle {ra:.8f} {dec:.8f} {radius:.8f}",
        "MAXREC": "100",
    }
    response = _irsa_get(SIA_URL, params=params)
    try:
        table = Table.read(io.BytesIO(response.content), format="votable", use_names_over_ids=True)
    except Exception as exc:
        raise RuntimeError(f"IRSA returned a VOTable response that could not be parsed: {exc}") from exc

    found = []
    for row in table:
        access_url = _clean(_row_value(row, ["access_url"]))
        if not access_url:
            continue
        parsed = urlparse(access_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "ipac.caltech.edu" or host.endswith(".ipac.caltech.edu")):
            continue
        token = uuid.uuid4().hex
        OBSERVATIONS[token] = {"access_url": access_url, "collection": collection}
        found.append({
            "id": token,
            "preview_url": f"/api/observations/{token}/preview.fits",
            "collection": collection,
            "obs_id": _clean(_row_value(row, ["obs_id", "obs_publisher_did", "obs_id" ])),
            "ra": _row_value(row, ["s_ra", "ra"]),
            "dec": _row_value(row, ["s_dec", "dec"]),
            "band": _clean(_row_value(row, ["band", "energy_band", "em_min"])),
            "date": _clean(_row_value(row, ["t_min", "date_obs", "mjd_obs"])),
        })
    return found


@app.get("/api/search")
def search_observations(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(0.25, gt=0, le=5),
    collection: str = Query("current"),
):
    if collection == "current":
        selected_collections = ["spherex_dr1", "spherex_qr3"]
    elif collection == "deep":
        selected_collections = ["spherex_dr1_deep", "spherex_qr3_deep"]
    elif collection in COLLECTIONS:
        selected_collections = [collection]
    else:
        raise HTTPException(400, "SPHEREx collection not allowed.")

    observations = []
    errors = []
    for index, selected in enumerate(selected_collections):
        if index:
            time.sleep(2)
        try:
            observations.extend(_query_collection(selected, ra, dec, radius))
        except Exception as exc:
            errors.append(f"{selected}: {exc}")

    if not observations and errors and len(errors) >= len(selected_collections):
        raise HTTPException(502, "Could not query IRSA. " + " | ".join(errors))
    # Stable order and a capped response to protect the interface and the service.
    observations = observations[:100]
    return {"count": len(observations), "observations": observations, "warnings": errors}


@app.get("/api/observations/{token}/preview.fits")
def fits_preview(
    token: str,
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    size: float = Query(0.2, gt=0, le=0.5),
):
    record = OBSERVATIONS.get(token)
    if not record:
        raise HTTPException(404, "The observation expired or the server restarted. Search again.")

    try:
        response = _irsa_get(
            record["access_url"],
            params={"center": f"{ra:.8f},{dec:.8f}", "size": f"{size:.6f}"},
            timeout=(20, 180),
        )
        with fits.open(io.BytesIO(response.content), memmap=False) as hdul:
            candidates = []
            for index, hdu in enumerate(hdul):
                data = getattr(hdu, "data", None)
                if data is None or getattr(data, "ndim", 0) != 2:
                    continue
                extname = str(hdu.header.get("EXTNAME", "")).upper()
                score = 10 if extname in {"SCI", "SCIENCE", "IMAGE", "FLUX"} else 0
                if any(word in extname for word in ("VAR", "ERR", "FLAG", "MASK", "ZODI", "PSF", "DQ")):
                    score -= 20
                candidates.append((score, index, hdu))
            if not candidates:
                raise ValueError("The FITS cutout does not contain a compatible 2D image extension.")
            candidates.sort(key=lambda item: item[0], reverse=True)
            _, _, selected_hdu = candidates[0]
            image_hdu = fits.PrimaryHDU(data=selected_hdu.data.copy(), header=selected_hdu.header.copy())
            output = io.BytesIO()
            image_hdu.writeto(output, overwrite=True)
            fits_payload = output.getvalue()
    except requests.RequestException as exc:
        raise HTTPException(502, f"Could not download the cutout from IRSA: {exc}") from exc
    except Exception as exc:
        raise HTTPException(422, f"Could not prepare the FITS preview: {exc}") from exc

    return Response(
        content=fits_payload,
        media_type="application/fits",
        headers={
            "Content-Disposition": 'inline; filename="spherex-preview.fits"',
            "Cache-Control": "public, max-age=300",
        },
    )


def _mjd_or_date(value):
    if value is None:
        return "Unknown date", float("inf")
    try:
        number = float(value)
        return Time(number, format="mjd").isot[:10], number
    except (TypeError, ValueError):
        try:
            return Time(str(value)).isot[:10], float("inf")
        except Exception:
            return str(value), float("inf")


def _sample_evenly(items, limit):
    if len(items) <= limit:
        return items
    indices = np.unique(np.linspace(0, len(items) - 1, limit).round().astype(int))
    return [items[int(index)] for index in indices]


def _science_image(hdul):
    candidates = []
    for index, hdu in enumerate(hdul):
        data = getattr(hdu, "data", None)
        if data is None or getattr(data, "ndim", 0) != 2:
            continue
        name = str(hdu.header.get("EXTNAME", "")).upper()
        score = 10 if name in {"SCI", "SCIENCE", "IMAGE", "FLUX"} else 0
        if any(word in name for word in ("VAR", "ERR", "FLAG", "MASK", "ZODI", "PSF", "DQ")):
            score -= 30
        candidates.append((score, index, hdu))
    if not candidates:
        raise ValueError("The FITS file does not contain a 2D science image.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][2]


def _read_and_align_fits(payload: bytes, target_wcs, shape_out):
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    with fits.open(io.BytesIO(payload), memmap=False) as hdul:
        hdu = _science_image(hdul)
        data = np.asarray(hdu.data, dtype=float)
        header = hdul[0].header.copy()
        header.extend(hdu.header, update=True, strip=False)
        w_in = WCS(header).celestial
        if not w_in.has_celestial:
            raise ValueError("The FITS image does not contain a usable celestial WCS.")
        date_value = None
        for key in ("DATE-OBS", "DATE-BEG", "DATE_OBS", "DATE-AVG", "MJD-OBS", "MJD-BEG", "MJD-AVG", "MJD_OBS"):
            if key in header:
                date_value = header[key]
                break
        detector = header.get("DETECTOR", "D?")
        if isinstance(detector, (int, np.integer)) or str(detector).strip().isdigit():
            detector = f"D{int(detector)}"
        detector = str(detector)
        aligned, footprint = reproject_interp((data, w_in), target_wcs, shape_out=shape_out, order="bilinear")
    aligned[footprint <= 0] = np.nan
    valid = np.isfinite(aligned)
    coverage = float(valid.mean())
    if coverage < 0.35:
        raise ValueError(f"Insufficient cutout coverage ({coverage:.0%}).")
    _, background, noise = sigma_clipped_stats(aligned[valid], sigma=3)
    aligned = aligned - float(background)
    aligned[~np.isfinite(aligned)] = 0.0
    quality = "good" if coverage > 0.95 else "warning" if coverage > 0.75 else "limited"
    date, sort_value = _mjd_or_date(date_value)
    return {"image": aligned, "date": date, "sort": sort_value, "detector": detector,
            "coverage": coverage, "noise": float(noise), "quality": quality}


def _asinh_png(image, low, high, soft=0.1):
    if not math.isfinite(high) or high <= low:
        high = low + 1.0
    scaled = np.clip((image - low) / (high - low), 0, 1)
    stretched = np.arcsinh(scaled / soft) / np.arcsinh(1 / soft)
    return Image.fromarray((stretched * 255).astype(np.uint8)[::-1])


def _load_preloaded_tracks() -> None:
    """Register SPHEREx sequences saved on disk so the demo does not call NASA."""
    PRELOADED_TRACKS.clear()
    if not DEMO_ROOT.is_dir():
        return
    for manifest_path in sorted(DEMO_ROOT.glob("*/manifest.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        track_id = str(payload.get("track_id") or "")
        frames = payload.get("frames") or []
        if not track_id or not frames:
            continue
        directory = manifest_path.parent.resolve()
        records = []
        for frame in frames:
            raw_path = directory / f"raw_{int(frame['index']):03d}.npy"
            if not raw_path.is_file():
                records = []
                break
            records.append({"raw_path": raw_path, "detector": frame["detector"]})
        if not records:
            continue
        TRACKS[track_id] = directory
        TRACK_DATA[track_id] = records
        PRELOADED_TRACKS.append(payload)


def _match_preload(ra: float, dec: float, tolerance: float = 0.02) -> dict[str, Any] | None:
    best = None
    best_distance = tolerance
    for payload in PRELOADED_TRACKS:
        dra = (ra - float(payload["ra"])) * math.cos(math.radians(dec))
        ddec = dec - float(payload["dec"])
        distance = math.hypot(dra, ddec)
        if distance <= best_distance:
            best = payload
            best_distance = distance
    return best


_load_preloaded_tracks()


@app.get("/api/track/preload")
def track_preload(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
):
    """Return a SPHEREx sequence already stored for these coordinates."""
    payload = _match_preload(ra, dec)
    if not payload:
        raise HTTPException(404, "No preloaded SPHEREx sequence for these coordinates.")
    return payload


@app.get("/api/track")
def track_object(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(0.04, gt=0, le=0.5),
    max_frames: int = Query(24, ge=2, le=40),
    collection: str = Query("current"),
):
    """Search, download, and align a time sequence of SPHEREx cutouts."""
    if collection not in {"current", "deep"}:
        raise HTTPException(400, "Collection not allowed.")
    selected_collections = (["spherex_dr1", "spherex_qr3"] if collection == "current"
                            else ["spherex_dr1_deep", "spherex_qr3_deep"])
    found, errors = [], []
    for index, selected in enumerate(selected_collections):
        if index:
            time.sleep(2)
        try:
            found.extend(_query_collection(selected, ra, dec, radius))
        except Exception as exc:
            errors.append(f"{selected}: {exc}")
    # Deduplicate by URL and sort chronologically using t_min/MJD when available.
    unique = {}
    for item in found:
        record = OBSERVATIONS.get(item["id"])
        if not record:
            continue
        url = record["access_url"]
        if url not in unique:
            date, sort_value = _mjd_or_date(item.get("date"))
            unique[url] = {**item, "access_url": url, "date_label": date, "sort_value": sort_value}
    observations = sorted(unique.values(), key=lambda item: item["sort_value"])
    observations = _sample_evenly(observations, max_frames)
    if not observations:
        if errors and len(errors) >= len(selected_collections):
            raise HTTPException(502, "IRSA could not return observations: " + " | ".join(errors))
        return {"track_id": None, "count": 0, "frames": [], "warnings": errors}

    # Common north-up, east-left TAN grid shared by every frame in the sequence.
    fov_deg = min(max(radius * 2, 0.02), 0.5)
    scale_arcsec = 3.0
    side = max(48, min(240, int(round(fov_deg * 3600 / scale_arcsec))))
    target_wcs = WCS(naxis=2)
    target_wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target_wcs.wcs.crval = [ra, dec]
    target_wcs.wcs.crpix = [(side + 1) / 2, (side + 1) / 2]
    target_wcs.wcs.cdelt = [-scale_arcsec / 3600, scale_arcsec / 3600]

    processed, failures = [], []
    for item in observations:
        try:
            response = _irsa_get(
                item["access_url"],
                params={"center": f"{ra:.8f},{dec:.8f}", "size": f"{fov_deg:.6f}"},
                timeout=(20, 180),
            )
            frame = _read_and_align_fits(response.content, target_wcs, (side, side))
            frame.update({"collection": item["collection"], "obs_id": item.get("obs_id") or "",
                          "source_id": item["id"]})
            processed.append(frame)
        except Exception as exc:
            failures.append(f"{item.get('obs_id') or item['collection']}: {str(exc)[:180]}")

    if not processed:
        detail = " | ".join(failures[:4])
        raise HTTPException(422, "Observations were found, but their FITS files could not be processed. " + detail)

    # One representative image per date and detector: prefer coverage and lower noise.
    best = {}
    for frame in processed:
        key = (frame["date"], frame["detector"])
        previous = best.get(key)
        quality_key = (frame["coverage"], -frame["noise"])
        if previous is None or quality_key > (previous["coverage"], -previous["noise"]):
            best[key] = frame
    frames = list(best.values())
    track_id = uuid.uuid4().hex
    out_dir = Path(tempfile.gettempdir()) / "cem_spherex_tracks" / track_id
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = []
    # Shared brightness cuts per detector so the sequence does not change contrast artificially.
    cuts = {}
    for detector in sorted({frame["detector"] for frame in frames}):
        subset = [frame for frame in frames if frame["detector"] == detector]
        noise = float(np.median([frame["noise"] for frame in subset]))
        values = np.concatenate([frame["image"].ravel() for frame in subset])
        high = float(np.nanpercentile(values, 99.7))
        cuts[detector] = (-2 * noise, max(high, 8 * noise, 1e-8))
    for index, frame in enumerate(sorted(frames, key=lambda f: (f["sort"], f["detector"]))):
        low, high = cuts[frame["detector"]]
        filename = f"frame_{index:03d}.png"
        image = _asinh_png(frame["image"], low, high)
        image = image.resize((480, 480), Image.Resampling.NEAREST)
        image.save(out_dir / filename, optimize=True)
        raw_filename = f"raw_{index:03d}.npy"
        np.save(out_dir / raw_filename, frame["image"].astype(np.float32))
        TRACK_DATA.setdefault(track_id, []).append({"raw_path": out_dir / raw_filename, "detector": frame["detector"]})
        metadata.append({"index": index, "date": frame["date"], "detector": frame["detector"],
                         "collection": frame["collection"], "obs_id": frame["obs_id"],
                         "quality": frame["quality"], "coverage": round(frame["coverage"], 3),
                         "noise": round(frame["noise"], 6),
                         "image_url": f"/api/tracks/{track_id}/{filename}"})
    TRACKS[track_id] = out_dir
    return {"track_id": track_id, "count": len(metadata), "frames": metadata,
            "ra": ra, "dec": dec, "radius": radius, "warnings": errors + failures[:8],
            "processing": "WCS reprojection; background subtraction; shared asinh stretch per detector"}


@app.get("/api/tracks/{track_id}/difference.png")
def track_difference(track_id: str, a: int = Query(..., ge=0), b: int = Query(..., ge=0)):
    """Linear subtraction of two reprojected images from the same detector."""
    directory = TRACKS.get(track_id)
    records = TRACK_DATA.get(track_id)
    if not directory or not records or a >= len(records) or b >= len(records):
        raise HTTPException(404, "The sequence expired. Search for the observations again.")
    if a == b:
        raise HTTPException(400, "Select two different dates.")
    if records[a]["detector"] != records[b]["detector"]:
        raise HTTPException(400, "To subtract images you must select the same detector.")
    image_a = np.load(records[a]["raw_path"])
    image_b = np.load(records[b]["raw_path"])
    delta = image_b - image_a
    scale = float(np.nanpercentile(np.abs(delta), 99.5))
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    normalized = np.clip(delta / scale, -1, 1)
    # Diverging difference: orange = increase; cyan = decrease.
    rgb = np.zeros((*normalized.shape, 3), dtype=np.uint8)
    positive = np.clip(normalized, 0, 1)
    negative = np.clip(-normalized, 0, 1)
    rgb[..., 0] = (255 * positive).astype(np.uint8)
    rgb[..., 1] = (145 * positive + 190 * negative).astype(np.uint8)
    rgb[..., 2] = (255 * negative).astype(np.uint8)
    output = Image.fromarray(rgb[::-1]).resize((480, 480), Image.Resampling.NEAREST)
    path = directory / f"difference_{a}_{b}.png"
    output.save(path, optimize=True)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/tracks/{track_id}/{filename}")
def track_frame(track_id: str, filename: str):
    directory = TRACKS.get(track_id)
    if not directory or not filename.startswith("frame_") or not filename.endswith(".png"):
        raise HTTPException(404, "The sequence does not exist or expired. Search for the observations again.")
    path = directory / filename
    if not path.is_file() or path.parent != directory:
        raise HTTPException(404, "Image not found.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
