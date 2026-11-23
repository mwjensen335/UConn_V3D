"""Build the HDF5 database from Qualisys/Theia/Visual3D session exports.

Each Qualisys session folder (e.g. "Counter-movement jump markerless session")
holds two files this script reads:

    session_data.xml   V3D XML export: every trial's signals (all frames),
                       events and metrics
    session.xml        Qualisys subject/session details

Usage
-----
    python rtp_ingest.py                       # scan this project folder
    python rtp_ingest.py "D:\\RTP-Assessment\\Data"
    python rtp_ingest.py DATA_ROOT --out database\\rtp_database.h5

The whole database is rebuilt from the exports on every run (they are the
source of truth), written to a temporary file and swapped in at the end, so an
interrupted run never leaves a half-written database.

Privacy: only the subject fields in SUBJECT_FIELDS are stored. Names, date of
birth, e-mail, free-text comments and injury history are never read into the
database.

Layout
------
/subjects/<ID>                                    attrs: sex, dominance, ...
/subjects/<ID>/<date>_<system>                    attrs: date, system, height_m, weight_kg, ...
/subjects/<ID>/<date>_<system>/<movement>/<variant>/trial_NN
        attrs:   source_file, type_name, n_frames, rate_hz, time_start, time_end
        signals/<TYPE>/<FOLDER>/<signal name>    float32 (n_frames, n_components)
                attrs: components, frame_start, frame_end, time_start, time_end
/tables/trials    one row per trial (index of everything above)
/tables/events    one row per event occurrence (trial_path, name, time)
/tables/metrics   one row per metric value (trial_path, name, component, value)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

SCHEMA_VERSION = "1"

# session.xml field -> database attribute. Anything not listed is ignored.
SUBJECT_FIELDS = {"Sex": "sex", "Dominance": "dominance"}
SESSION_FIELDS = {
    "Height": "height_m", "Weight": "weight_kg", "Injured_side": "injured_side",
    "Injury": "injury", "Event_mode": "event_mode",
}
NUMERIC = {"height_m", "weight_kg"}
SYSTEM_WORDS = {"markerless": "markerless", "markered": "markered", "marker": "markered"}
SIDE_WORDS = {"left", "right"}

STR = h5py.string_dtype("utf-8")


# ----------------------------------------------------------------------------
# session.xml
# ----------------------------------------------------------------------------
def _fields(elem: ET.Element) -> dict[str, str]:
    f = elem.find("Fields")
    return {c.tag: (c.text or "").strip() for c in f} if f is not None else {}


def read_session_xml(path: Path) -> dict:
    """Subject ID, the allowed subject/session fields, and trial type names."""
    root = ET.parse(path).getroot()
    subj = _fields(root)
    info = {"subject": subj.get("ID", "").strip(), "subject_attrs": {}, "session_attrs": {},
            "date": subj.get("Creation_date", ""), "type_names": set()}
    for src, dst in SUBJECT_FIELDS.items():
        if subj.get(src):
            info["subject_attrs"][dst] = subj[src]

    for elem in root.iter():
        fields = _fields(elem)
        if elem.tag == "Session":
            info["date"] = fields.get("Creation_date") or info["date"]
            for src, dst in SESSION_FIELDS.items():
                if fields.get(src):
                    val = fields[src]
                    info["session_attrs"][dst] = float(val) if dst in NUMERIC else val
        if elem.tag == "Measurement" and elem.get("Type"):
            info["type_names"].add(elem.get("Type"))
    return info


# ----------------------------------------------------------------------------
# Trial naming
# ----------------------------------------------------------------------------
def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_trial(owner: str, type_names: set[str]) -> dict:
    """'Squatting Markerless Left 2.c3d' -> movement squatting, variant left, trial 2."""
    stem = re.sub(r"(_Theia)?\.c3d$", "", owner, flags=re.IGNORECASE).strip()
    type_name = next((t for t in sorted(type_names, key=len, reverse=True)
                      if stem.lower().startswith(t.lower())), None)
    m = re.match(r"^(.*?)\s*(\d+)$", stem)
    if type_name is None:
        type_name = m.group(1) if m else stem
    rest = stem[len(type_name):].strip()
    number = int(rest) if rest.isdigit() else (int(m.group(2)) if m else 1)

    words = type_name.split()
    system = next((SYSTEM_WORDS[w.lower()] for w in words if w.lower() in SYSTEM_WORDS), "unknown")
    side = next((w.lower() for w in words if w.lower() in SIDE_WORDS), "bilateral")
    core = [w for w in words if w.lower() not in SYSTEM_WORDS and w.lower() not in SIDE_WORDS]
    return {"type_name": type_name, "trial": number, "system": system,
            "movement": slug(" ".join(core)) or "unknown", "variant": side}


# ----------------------------------------------------------------------------
# session_data.xml
# ----------------------------------------------------------------------------
def _values(text: str | None) -> np.ndarray:
    if not text:
        return np.array([], dtype=float)
    return pd.to_numeric(pd.Series(text.split(",")), errors="coerce").to_numpy(dtype=float)


def read_session_data(path: Path):
    """Yield (owner, trial dict) with signals, events and metrics per trial."""
    for owner in ET.parse(path).getroot().findall("owner"):
        trial = {"signals": [], "events": [], "metrics": []}
        for t in owner.findall("type"):
            stype = t.get("value")
            for folder in t.findall("folder"):
                fname = folder.get("value")
                for name in folder.findall("name"):
                    sname = name.get("value")
                    comps = name.findall("component")
                    if stype == "EVENT_LABEL":
                        for c in comps:
                            for time in _values(c.get("data")):
                                trial["events"].append((sname, float(time)))
                    elif stype == "METRIC":
                        for c in comps:
                            vals = _values(c.get("data"))
                            for v in vals if len(vals) else [np.nan]:
                                trial["metrics"].append((fname, sname, c.get("value"), float(v)))
                    else:
                        arrays = [_values(c.get("data")) for c in comps]
                        n = max((len(a) for a in arrays), default=0)
                        data = np.full((n, len(arrays)), np.nan, dtype=np.float32)
                        for i, a in enumerate(arrays):
                            data[: len(a), i] = a
                        first = comps[0].attrib if comps else {}
                        trial["signals"].append({
                            "type": stype, "folder": fname, "name": sname, "data": data,
                            "components": "".join(c.get("value", "") for c in comps),
                            **{k: float(first[k]) for k in
                               ("Frame_Start", "Frame_End", "Time_Start", "Time_End") if k in first},
                        })
        yield owner.get("value"), trial


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------
def h5name(text: str) -> str:
    return text.replace("/", "_")


def write_table(group: h5py.Group, df: pd.DataFrame) -> None:
    for col in df.columns:
        values = df[col]
        if values.dtype == object:
            group.create_dataset(col, data=values.fillna("").astype(str).to_numpy(dtype=object), dtype=STR)
        else:
            group.create_dataset(col, data=values.to_numpy())


def build(root: Path, out: Path) -> int:
    exports = sorted(root.rglob("session_data.xml"))
    if not exports:
        print(f"No session_data.xml files found under {root}")
        return 1
    print(f"Found {len(exports)} session exports under {root}\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    trials, events, metrics, problems = [], [], [], []
    seen: set[tuple] = set()

    with h5py.File(tmp, "w") as h5:
        h5.attrs.update(schema_version=SCHEMA_VERSION, created=datetime.now().isoformat(timespec="seconds"))
        for export in exports:
            sess_xml = export.with_name("session.xml")
            if not sess_xml.exists():
                problems.append(f"{export}: no session.xml next to it - skipped")
                continue
            info = read_session_xml(sess_xml)
            subject = info["subject"]
            if not subject:
                # Don't fall back to the folder name: Qualisys names it <Last name>_<ID>.
                problems.append(f"{export.parent.name}: session.xml has no subject ID - skipped")
                continue
            # Path below the subject folder only (the subject folder name contains a surname).
            export_rel = str(export.relative_to(export.parents[2])) if len(export.parents) > 2 else export.name
            print(f"  {subject}  {export.parent.name}")

            for owner, data in read_session_data(export):
                t = parse_trial(owner, info["type_names"])
                key = (subject, info["date"], t["system"], t["movement"], t["variant"], t["trial"])
                if key in seen:  # the static trial is repeated in every session export
                    continue
                seen.add(key)

                session_name = f"{info['date']}_{t['system']}"
                subj_grp = h5.require_group(f"subjects/{h5name(subject)}")
                subj_grp.attrs.update(info["subject_attrs"])
                sess_grp = subj_grp.require_group(h5name(session_name))
                sess_grp.attrs.update(date=info["date"], system=t["system"], **info["session_attrs"])

                path = f"/subjects/{h5name(subject)}/{h5name(session_name)}/{t['movement']}/{t['variant']}/trial_{t['trial']:02d}"
                grp = h5.create_group(path)

                n_frames, t0, t1 = 0, np.nan, np.nan
                for s in data["signals"]:
                    ds = grp.create_dataset(f"signals/{s['type']}/{s['folder']}/{h5name(s['name'])}",
                                            data=s["data"], compression="gzip", compression_opts=4)
                    ds.attrs.update(components=s["components"], name=s["name"],
                                    **{k.lower(): v for k, v in s.items() if k[0].isupper()})
                    if len(s["data"]) > n_frames:
                        n_frames, t0, t1 = len(s["data"]), s.get("Time_Start", np.nan), s.get("Time_End", np.nan)
                rate = (n_frames - 1) / (t1 - t0) if n_frames > 1 and t1 > t0 else np.nan
                grp.attrs.update(source_file=owner, type_name=t["type_name"], n_frames=n_frames,
                                 rate_hz=rate, time_start=t0, time_end=t1,
                                 source_export=export_rel)

                base = {"trial_path": path, "subject": subject, "session": session_name}
                trials.append({**base, "date": info["date"], "system": t["system"],
                               "movement": t["movement"], "variant": t["variant"], "trial": t["trial"],
                               "source_file": owner, "n_frames": n_frames, "rate_hz": rate,
                               "time_start": t0, "time_end": t1, "n_signals": len(data["signals"]),
                               "n_events": len(data["events"]), "n_metrics": len(data["metrics"])})
                events += [{"trial_path": path, "name": n, "time": v} for n, v in data["events"]]
                metrics += [{"trial_path": path, "folder": f, "name": n, "component": c, "value": v,
                             "aggregate": bool(re.search(r"_(MEAN|STDDEV)$", n))}
                            for f, n, c, v in data["metrics"]]

        tables = h5.create_group("tables")
        for name, rows in (("trials", trials), ("events", events), ("metrics", metrics)):
            write_table(tables.create_group(name), pd.DataFrame(rows))

    os.replace(tmp, out)

    df = pd.DataFrame(trials)
    print("\nTrials per movement:")
    print(df.groupby(["subject", "session", "movement", "variant"]).size().to_string())
    print(f"\n  {len(df)} trials, {len(events)} events, {len(metrics)} metric values")
    for p in problems:
        print("  ! " + p)
    print(f"\nWrote {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", type=Path, default=here, help="folder holding the subject folders")
    ap.add_argument("--out", type=Path, default=here / "database" / "rtp_database.h5")
    args = ap.parse_args()
    try:
        return build(args.root.resolve(), args.out.resolve())
    except PermissionError:
        print(f"Could not write {args.out} - is it open in another program (e.g. the dashboard)?")
        return 1


if __name__ == "__main__":
    sys.exit(main())
