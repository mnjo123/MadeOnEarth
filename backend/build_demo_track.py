"""Download one SPHEREx sequence and store it for the Real Motion demo.

The running app serves this directory immediately, so opening Real Motion
does not wait on NASA. Run again only when the cached images should be refreshed.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from astropy.wcs import WCS
from PIL import Image

import server

OUT_ROOT = Path(__file__).resolve().parent.parent / "demo" / "real-motion"
TARGET = {
    "slug": "wise0855",
    "name": "WISE 0855",
    "ra": 133.795,
    "dec": -7.245,
    "radius": 0.04,
    "track_id": "wise0855",
}


def _gather(ra: float, dec: float, radius: float) -> list[dict]:
    found = []
    for collection in ("spherex_dr1", "spherex_qr3"):
        try:
            found.extend(server._query_collection(collection, ra, dec, radius))
            print(f"query {collection}: {len(found)} rows so far", flush=True)
        except Exception as exc:
            print(f"query {collection} failed: {exc}", flush=True)
    unique = {}
    for item in found:
        record = server.OBSERVATIONS.get(item["id"])
        if not record:
            continue
        url = record["access_url"]
        if url in unique:
            continue
        date, sort_value = server._mjd_or_date(item.get("date"))
        unique[url] = {**item, "access_url": url, "date_label": date, "sort_value": sort_value}
    return sorted(unique.values(), key=lambda item: item["sort_value"])


def _process(observations: list[dict], ra: float, dec: float, radius: float) -> list[dict]:
    fov_deg = min(max(radius * 2, 0.02), 0.5)
    scale_arcsec = 3.0
    side = max(48, min(240, int(round(fov_deg * 3600 / scale_arcsec))))
    target_wcs = WCS(naxis=2)
    target_wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target_wcs.wcs.crval = [ra, dec]
    target_wcs.wcs.crpix = [(side + 1) / 2, (side + 1) / 2]
    target_wcs.wcs.cdelt = [-scale_arcsec / 3600, scale_arcsec / 3600]
    processed = []
    for index, item in enumerate(observations, start=1):
        print(f"cutout {index}/{len(observations)} {item.get('obs_id') or item['collection']}", flush=True)
        try:
            response = server._irsa_get(
                item["access_url"],
                params={"center": f"{ra:.8f},{dec:.8f}", "size": f"{fov_deg:.6f}"},
                timeout=(20, 180),
            )
            frame = server._read_and_align_fits(response.content, target_wcs, (side, side))
            frame.update({"collection": item["collection"], "obs_id": item.get("obs_id") or ""})
            processed.append(frame)
            print(f"  kept {frame['date']} {frame['detector']} coverage {frame['coverage']:.0%}", flush=True)
        except Exception as exc:
            print(f"  skipped: {exc}", flush=True)
    return processed


def _best_detector(frames: list[dict], limit: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for frame in frames:
        groups[frame["detector"]].append(frame)

    def rank(detector: str) -> tuple:
        dates = sorted({frame["date"] for frame in groups[detector] if frame["date"] != "Unknown date"})
        return (len(dates), dates[-1] if dates else "")

    if not groups:
        return []
    detector = max(groups, key=rank)
    best = {}
    for frame in groups[detector]:
        previous = best.get(frame["date"])
        quality = (frame["coverage"], -frame["noise"])
        if previous is None or quality > (previous["coverage"], -previous["noise"]):
            best[frame["date"]] = frame
    chosen = sorted(best.values(), key=lambda frame: frame["sort"])
    if len(chosen) > limit:
        indices = np.unique(np.linspace(0, len(chosen) - 1, limit).round().astype(int))
        chosen = [chosen[int(index)] for index in indices]
    print(f"detector {detector}: {len(chosen)} dates", flush=True)
    return chosen


def main() -> None:
    ra, dec, radius = TARGET["ra"], TARGET["dec"], TARGET["radius"]
    observations = _gather(ra, dec, radius)
    print(f"unique observations: {len(observations)}", flush=True)
    if len(observations) < 2:
        raise SystemExit("NASA did not return enough SPHEREx observations to build the demo.")

    chosen: list[dict] = []
    for sample in (12, 24, len(observations)):
        batch = server._sample_evenly(observations, sample)
        processed = _process(batch, ra, dec, radius)
        chosen = _best_detector(processed, 8)
        if len(chosen) >= 2:
            break
        print(f"only {len(chosen)} dates after sampling {sample}; trying a wider sample", flush=True)
    if len(chosen) < 2:
        raise SystemExit("Could not keep two SPHEREx images from the same detector.")

    out_dir = OUT_ROOT / TARGET["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    cuts = {}
    detector = chosen[0]["detector"]
    noise = float(np.median([frame["noise"] for frame in chosen]))
    values = np.concatenate([frame["image"].ravel() for frame in chosen])
    high = float(np.nanpercentile(values, 99.7))
    cuts[detector] = (-2 * noise, max(high, 8 * noise, 1e-8))
    metadata = []
    for index, frame in enumerate(chosen):
        low, high = cuts[detector]
        filename = f"frame_{index:03d}.png"
        image = server._asinh_png(frame["image"], low, high)
        image = image.resize((480, 480), Image.Resampling.NEAREST)
        image.save(out_dir / filename, optimize=True)
        np.save(out_dir / f"raw_{index:03d}.npy", frame["image"].astype(np.float32))
        metadata.append({
            "index": index,
            "date": frame["date"],
            "detector": frame["detector"],
            "collection": frame["collection"],
            "obs_id": frame["obs_id"],
            "quality": frame["quality"],
            "coverage": round(frame["coverage"], 3),
            "noise": round(frame["noise"], 6),
            "image_url": f"/api/tracks/{TARGET['track_id']}/{filename}",
        })
    manifest = {
        "name": TARGET["name"],
        "ra": ra,
        "dec": dec,
        "radius": radius,
        "track_id": TARGET["track_id"],
        "count": len(metadata),
        "frames": metadata,
        "warnings": [],
        "processing": "WCS reprojection; background subtraction; shared asinh stretch per detector",
        "source": "NASA/IPAC IRSA SPHEREx, saved locally for the demo",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"saved {len(metadata)} frames to {out_dir}", flush=True)


if __name__ == "__main__":
    main()
