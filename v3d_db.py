"""Read the HDF5 database built by rtp_ingest.py into pandas.

    import v3d_db as db

    db.summary()                                   # what's in the database
    trials  = db.trials()                          # one row per trial
    metrics = db.metrics(movement="counter-movement-jump")
    events  = db.events()
    db.signal_names("squatting")                   # signals available for a movement

    # one trial's curve, as a DataFrame (time + X/Y/Z)
    knee = db.load_signal(trials.trial_path[0], "Left Knee Angles")

    # every trial of a movement, time-normalized between two events (0-100 %)
    curves = db.curves("counter-movement-jump", "Left Knee Angles", component="X",
                       start_event="LeftPlotStart", end_event="LeftPlotEnd")
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent / "database" / "rtp_database.h5"


def _read_table(h5: h5py.File, name: str) -> pd.DataFrame:
    grp = h5[f"tables/{name}"]
    cols = {}
    for col, ds in grp.items():
        cols[col] = ds.asstr()[:] if ds.dtype.kind == "O" else ds[:]
    return pd.DataFrame(cols)


@lru_cache(maxsize=4)
def _tables(db_path: str, mtime: float) -> dict[str, pd.DataFrame]:
    with h5py.File(db_path, "r") as h5:
        return {n: _read_table(h5, n) for n in ("trials", "events", "metrics")}


def _get(name: str, db_path: Path | str = DEFAULT_DB) -> pd.DataFrame:
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found - run `python rtp_ingest.py` first")
    return _tables(str(p), p.stat().st_mtime)[name].copy()  # re-reads when the file is rebuilt


def _filter(df: pd.DataFrame, **where) -> pd.DataFrame:
    for col, val in where.items():
        if val is None:
            continue
        vals = [val] if isinstance(val, (str, int)) else list(val)
        df = df[df[col].isin(vals)]
    return df


# ----------------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------------
def trials(movement=None, variant=None, subject=None, db_path=DEFAULT_DB) -> pd.DataFrame:
    df = _get("trials", db_path)
    return _filter(df, movement=movement, variant=variant, subject=subject).reset_index(drop=True)


def events(movement=None, variant=None, subject=None, db_path=DEFAULT_DB) -> pd.DataFrame:
    t = trials(movement, variant, subject, db_path)
    cols = ["trial_path", "subject", "session", "movement", "variant", "trial"]
    return _get("events", db_path).merge(t[cols], on="trial_path")


def metrics(movement=None, variant=None, subject=None, include_aggregates=False,
            db_path=DEFAULT_DB) -> pd.DataFrame:
    """Metric values per trial. V3D's own _MEAN/_STDDEV rows are dropped by
    default - compute summaries in pandas from the per-trial values instead."""
    t = trials(movement, variant, subject, db_path)
    cols = ["trial_path", "subject", "session", "date", "system", "movement", "variant", "trial"]
    m = _get("metrics", db_path).merge(t[cols], on="trial_path")
    if not include_aggregates:
        m = m[~m["aggregate"]]
    return m.reset_index(drop=True)


def metrics_wide(movement=None, variant=None, subject=None, db_path=DEFAULT_DB) -> pd.DataFrame:
    """One row per trial, one column per metric (component appended if not X)."""
    m = metrics(movement, variant, subject, db_path=db_path)
    m["column"] = np.where(m["component"].isin(["X", ""]), m["name"], m["name"] + "_" + m["component"])
    keys = ["subject", "session", "movement", "variant", "trial"]
    return m.pivot_table(index=keys, columns="column", values="value", aggfunc="first").reset_index()


# ----------------------------------------------------------------------------
# Signals
# ----------------------------------------------------------------------------
def _signal_datasets(grp: h5py.Group) -> dict[str, h5py.Dataset]:
    found = {}

    def add(path, obj):  # must return None, or h5py stops visiting
        if isinstance(obj, h5py.Dataset):
            found.setdefault(obj.attrs.get("name", path.split("/")[-1]), obj)

    grp["signals"].visititems(add)
    return found


def signal_names(movement=None, variant=None, db_path=DEFAULT_DB) -> list[str]:
    t = trials(movement, variant, db_path=db_path)
    names: set[str] = set()
    with h5py.File(db_path, "r") as h5:
        for path in t["trial_path"].unique()[:50]:
            names.update(_signal_datasets(h5[path]))
    return sorted(names)


def load_signal(trial_path: str, name: str, db_path=DEFAULT_DB) -> pd.DataFrame:
    """One trial's signal: columns time (s), frame, and one per component."""
    with h5py.File(db_path, "r") as h5:
        grp = h5[trial_path]
        ds = _signal_datasets(grp).get(name)
        if ds is None:
            raise KeyError(f"{name!r} not in {trial_path}")
        data = ds[:]
        comps = list(ds.attrs.get("components", "")) or [str(i) for i in range(data.shape[1])]
        rate = grp.attrs.get("rate_hz", np.nan)
        t0 = ds.attrs.get("time_start", 0.0)
        f0 = ds.attrs.get("frame_start", 1.0)
    df = pd.DataFrame(data, columns=comps[: data.shape[1]])
    df.insert(0, "frame", np.arange(len(df)) + f0)
    df.insert(0, "time", t0 + np.arange(len(df)) / rate if rate and rate == rate else np.nan)
    return df


def _event_time(ev: pd.DataFrame, name: str, after: float = -np.inf) -> float:
    times = ev.loc[(ev["name"] == name) & (ev["time"] > after), "time"].sort_values()
    return float(times.iloc[0]) if len(times) else np.nan


def curves(movement, signal, component="X", variant=None, subject=None,
           start_event=None, end_event=None, points=101, db_path=DEFAULT_DB) -> pd.DataFrame:
    """All trials of a movement for one signal component, in long format.

    With start/end events: each trial is cut to that window and resampled to
    `points` samples (x = 0-100 %). Without: raw time in seconds."""
    t = trials(movement, variant, subject, db_path)
    ev = _get("events", db_path)
    out = []
    for _, tr in t.iterrows():
        try:
            sig = load_signal(tr["trial_path"], signal, db_path)
        except KeyError:
            continue
        if component not in sig:
            continue
        x, y = sig["time"].to_numpy(), sig[component].to_numpy(dtype=float)
        if start_event and end_event:
            tev = ev[ev["trial_path"] == tr["trial_path"]]
            t_start = _event_time(tev, start_event)
            t_end = _event_time(tev, end_event, after=t_start)
            if not (t_end > t_start):
                continue
            pct = np.linspace(0, 100, points)
            y = np.interp(t_start + pct / 100 * (t_end - t_start), x, y, left=np.nan, right=np.nan)
            x = pct
        out.append(pd.DataFrame({"x": x, "value": y, "subject": tr["subject"], "session": tr["session"],
                                 "variant": tr["variant"], "trial": tr["trial"],
                                 "trial_path": tr["trial_path"]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        columns=["x", "value", "subject", "session", "variant", "trial", "trial_path"])


# ----------------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------------
def sessions(db_path=DEFAULT_DB) -> pd.DataFrame:
    """One row per subject session with the stored (non-identifying) details."""
    rows = []
    with h5py.File(db_path, "r") as h5:
        for sid, sgrp in h5["subjects"].items():
            for sess, grp in sgrp.items():
                rows.append({"subject": sid, "session": sess, **dict(sgrp.attrs), **dict(grp.attrs)})
    return pd.DataFrame(rows)


def summary(db_path=DEFAULT_DB) -> pd.DataFrame:
    t = trials(db_path=db_path)
    table = (t.groupby(["movement", "variant"])
              .agg(subjects=("subject", "nunique"), sessions=("session", "nunique"), trials=("trial_path", "size"),
                   signals=("n_signals", "max"), metrics=("n_metrics", "max"), events=("n_events", "max"))
              .reset_index())
    print(f"{t['subject'].nunique()} subjects, {t['session'].nunique()} sessions, {len(t)} trials\n")
    print(table.to_string(index=False))
    return table


if __name__ == "__main__":
    summary()
