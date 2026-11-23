"""Generate a FULLY SYNTHETIC demo database - safe to share.

    python make_demo_database.py                  # 12 subjects -> demo/demo_database.h5
    python make_demo_database.py --subjects 30

Unlike make_mock_database.py (which perturbs a real subject's trials), this
uses no real data at all: every curve is built from simple keyframe models of a
counter-movement jump and a squat, with subject-to-subject and trial-to-trial
variation. Values are plausible but invented. Same layout as the real database
(see docs/hdf5_layout.md), so all analysis code works on either.

Contents per subject (one markerless session):
    counter-movement-jump / bilateral        3 trials
    squatting / bilateral, left, right       3 trials each
Signals (200 Hz, X/Y/Z): Left/Right Knee, Hip, Ankle Angles; Left/Right GRF;
Left/Right Knee Moment.
Each subject has an "injured side" whose limb loads less on landing, so the
data contain a limb asymmetry to find.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

from rtp_ingest import write_table

HERE = Path(__file__).resolve().parent
RATE = 200.0
G = 9.81


def curve(t: np.ndarray, keys: list[tuple[float, float]]) -> np.ndarray:
    """Smooth, shape-preserving curve through (time, value) keyframes."""
    kt, kv = map(np.array, zip(*sorted(keys)))
    keep = np.r_[True, np.diff(kt) > 1e-6]
    return PchipInterpolator(kt[keep], kv[keep], extrapolate=True)(t)


def noise(rng, n: int, scale: float) -> np.ndarray:
    """Low-frequency wobble (looks like soft-tissue/tracking noise, not white noise)."""
    w = np.convolve(rng.normal(0, 1, n + 40), np.ones(40) / 40, mode="valid")[:n]
    return scale * w / (np.abs(w).max() + 1e-9)


# ----------------------------------------------------------------------------
# Movement models
# ----------------------------------------------------------------------------
def cmj_trial(subj: dict, rng) -> tuple[dict, dict, float]:
    start = 0.8 + rng.uniform(0, 0.3)
    ecc = rng.normal(subj["ecc_time"], 0.03)
    con = rng.normal(subj["con_time"], 0.02)
    height = max(0.12, rng.normal(subj["jump_height"], 0.015))
    flight = 2 * np.sqrt(2 * height / G)
    bottom, takeoff = start + ecc, start + ecc + con
    touchdown = takeoff + flight
    land_peak, stable = touchdown + 0.12, touchdown + 0.6
    plot_end, eof = touchdown + 0.8, touchdown + 1.1
    t = np.arange(0, eof, 1 / RATE)
    bw = subj["weight_kg"] * G
    events = {"BOF": [0.0], "EOF": [t[-1]], "LeftPlotStart": [start], "RightPlotStart": [start],
              "COM_MIN": [bottom], "TakeOff": [takeoff], "TouchDown": [touchdown],
              "LeftPlotEnd": [plot_end], "RightPlotEnd": [plot_end]}

    signals = {}
    for side in ("Left", "Right"):
        injured = side == subj["injured_side"]
        k_max = rng.normal(subj["knee_max"], 3)
        k_land = rng.normal(subj["knee_land"] * (0.88 if injured else 1.0), 3)
        h_max = rng.normal(subj["hip_max"], 3)
        knee = curve(t, [(0, 5), (start, 5), (bottom, k_max), (takeoff, 3), (takeoff + flight / 2, 15),
                         (touchdown, 12), (land_peak, k_land), (stable, 10), (eof, 6)])
        hip = curve(t, [(0, 5), (start, 5), (bottom, h_max), (takeoff, 0), (takeoff + flight / 2, 10),
                        (touchdown, 12), (land_peak, 0.75 * k_land), (stable, 15), (eof, 8)])
        ankle = curve(t, [(0, 2), (start, 2), (bottom, 25), (takeoff, -35), (takeoff + flight / 2, -25),
                          (touchdown, -20), (land_peak, 22), (stable, 5), (eof, 3)])

        land = rng.normal(subj["land_grf_bw"] * (0.85 if injured else 1.0), 0.1) * bw
        grf_z = curve(t, [(0, bw / 2), (start, bw / 2), (start + 0.6 * ecc, 0.35 * bw), (bottom, 1.1 * bw),
                          (takeoff - 0.06, 0.9 * bw), (takeoff, 0), (touchdown, 0), (touchdown + 0.05, land),
                          (touchdown + 0.25, 0.7 * bw), (stable, bw / 2), (eof, bw / 2)])
        grf_z[(t > takeoff) & (t < touchdown)] = 0
        grf_z = np.clip(grf_z + noise(rng, len(t), 0.01 * bw), 0, None)

        valgus = subj["valgus"] * (1.3 if injured else 1.0)
        n = len(t)
        signals[f"{side} Knee Angles"] = np.c_[knee + noise(rng, n, 1.0), valgus * knee / 100 * 8 + noise(rng, n, 0.8),
                                               0.1 * knee + noise(rng, n, 1.0)]
        signals[f"{side} Hip Angles"] = np.c_[hip + noise(rng, n, 1.0), 0.05 * hip + noise(rng, n, 0.8),
                                              -0.05 * hip + noise(rng, n, 1.0)]
        signals[f"{side} Ankle Angles"] = np.c_[ankle + noise(rng, n, 1.0), noise(rng, n, 1.5), noise(rng, n, 1.5)]
        signals[f"{side} GRF"] = np.c_[0.05 * grf_z * np.sin(t * 3), 0.08 * grf_z, grf_z]
        moment = grf_z * 0.35 * np.sin(np.radians(knee))
        signals[f"{side} Knee Moment"] = np.c_[moment, 0.1 * moment, 0.05 * moment]
    return signals, events, flight


def squat_trial(subj: dict, variant: str, rng) -> tuple[dict, dict]:
    start = 1.0 + rng.uniform(0, 0.3)
    down = rng.normal(1.2, 0.1)
    bottom, end = start + down, start + 2 * down
    eof = end + 0.8
    t = np.arange(0, eof, 1 / RATE)
    bw = subj["weight_kg"] * G
    events = {"BOF": [0.0], "EOF": [t[-1]], "LeftPlotStart": [start], "RightPlotStart": [start],
              "Bottom": [bottom], "LeftPlotEnd": [end], "RightPlotEnd": [end]}
    signals = {}
    for side in ("Left", "Right"):
        stance = variant == "bilateral" or variant == side.lower()
        depth = subj["squat_depth"] if variant == "bilateral" else 0.72 * subj["squat_depth"]
        if side == subj["injured_side"]:
            depth *= 0.93
        if stance:
            k_max = rng.normal(depth, 3)
            knee = curve(t, [(0, 5), (start, 5), (bottom, k_max), (end, 5), (eof, 5)])
            share = 0.5 if variant == "bilateral" else 1.0
            grf_z = curve(t, [(0, share * bw), (start, share * bw), (start + 0.3 * down, 0.8 * share * bw),
                              (bottom, share * bw), (bottom + 0.4 * down, 1.15 * share * bw), (end, share * bw),
                              (eof, share * bw)])
        else:  # raised leg in a single-leg squat
            knee = curve(t, [(0, 5), (start - 0.3, 60), (end + 0.3, 60), (eof, 5)])
            grf_z = np.zeros_like(t)
        hip = 0.8 * knee
        n = len(t)
        grf_z = np.clip(grf_z + noise(rng, n, 0.01 * bw), 0, None)
        signals[f"{side} Knee Angles"] = np.c_[knee + noise(rng, n, 1.0), subj["valgus"] * knee / 100 * 8 + noise(rng, n, 0.8),
                                               0.1 * knee + noise(rng, n, 1.0)]
        signals[f"{side} Hip Angles"] = np.c_[hip + noise(rng, n, 1.0), noise(rng, n, 1.0), noise(rng, n, 1.0)]
        signals[f"{side} Ankle Angles"] = np.c_[0.3 * knee + noise(rng, n, 1.0), noise(rng, n, 1.0), noise(rng, n, 1.0)]
        signals[f"{side} GRF"] = np.c_[noise(rng, n, 0.02 * bw), noise(rng, n, 0.03 * bw), grf_z]
        moment = grf_z * 0.3 * np.sin(np.radians(knee))
        signals[f"{side} Knee Moment"] = np.c_[moment, 0.1 * moment, 0.05 * moment]
    return signals, events


# ----------------------------------------------------------------------------
# Metrics (computed from the generated curves, so they are consistent)
# ----------------------------------------------------------------------------
def window_max(sig: np.ndarray, t: np.ndarray, t0: float, t1: float) -> float:
    m = (t >= t0) & (t <= t1)
    return float(np.nanmax(sig[m])) if m.any() else np.nan


def cmj_metrics(signals, events, flight, t) -> list[tuple[str, str, float]]:
    s, to, td, end = events["LeftPlotStart"][0], events["TakeOff"][0], events["TouchDown"][0], events["LeftPlotEnd"][0]
    out = [("Jump_height_CMJ", "X", G * flight ** 2 / 8), ("FlightTime_CMJ", "X", flight),
           ("EccentricTime_CMJ", "X", events["COM_MIN"][0] - s), ("ConcentricTime_CMJ", "X", to - events["COM_MIN"][0])]
    for side in ("Left", "Right"):
        out += [(f"{side} Knee Angles_max_CMJ", "X", window_max(signals[f"{side} Knee Angles"][:, 0], t, s, to)),
                (f"{side} Knee Angles_max_landing_CMJ", "X", window_max(signals[f"{side} Knee Angles"][:, 0], t, td, end)),
                (f"{side} Hip Angles_max_CMJ", "X", window_max(signals[f"{side} Hip Angles"][:, 0], t, s, to)),
                (f"{side} GRF_max_landing_CMJ", "Z", window_max(signals[f"{side} GRF"][:, 2], t, td, end)),
                (f"{side} Knee Moment_max_landing_CMJ", "X", window_max(signals[f"{side} Knee Moment"][:, 0], t, td, end))]
    return out


def squat_metrics(signals, events, t) -> list[tuple[str, str, float]]:
    s, e = events["LeftPlotStart"][0], events["LeftPlotEnd"][0]
    out = [("Squat_duration", "X", e - s)]
    for side in ("Left", "Right"):
        out += [(f"{side} Knee Angles_max_Squat", "X", window_max(signals[f"{side} Knee Angles"][:, 0], t, s, e)),
                (f"{side} Hip Angles_max_Squat", "X", window_max(signals[f"{side} Hip Angles"][:, 0], t, s, e))]
    return out


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------
def make_subject(k: int, rng) -> dict:
    sex = str(rng.choice(["Male", "Female"]))
    male = sex == "Male"
    knee_max = float(rng.normal(92, 9))
    # Built-in relationships (so the tutorial has something to find): men jump
    # higher, and a deeper countermovement goes with a slightly higher jump.
    jump = rng.normal(0.36 if male else 0.27, 0.03) + 0.002 * (knee_max - 92)
    return {
        "id": f"DEMO_{k:03d}", "sex": sex, "dominance": str(rng.choice(["Right", "Left"], p=[0.85, 0.15])),
        "height_m": float(np.clip(rng.normal(1.80 if male else 1.67, 0.07), 1.5, 2.05)),
        "weight_kg": float(np.clip(rng.normal(82 if male else 64, 9), 48, 120)),
        "injured_side": str(rng.choice(["Left", "Right"])),
        "date": (date(2026, 6, 1) + timedelta(days=int(rng.integers(0, 120)))).isoformat(),
        "jump_height": float(np.clip(jump, 0.15, 0.55)),
        "ecc_time": float(rng.normal(0.52, 0.05)), "con_time": float(rng.normal(0.30, 0.03)),
        "knee_max": knee_max, "knee_land": float(rng.normal(62, 8)), "hip_max": float(rng.normal(85, 9)),
        "land_grf_bw": float(rng.normal(2.3, 0.35)), "valgus": float(rng.normal(0, 1)),
        "squat_depth": float(rng.normal(108, 9)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subjects", type=int, default=12)
    ap.add_argument("--out", type=Path, default=HERE / "demo" / "demo_database.h5")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".h5.tmp")

    trials, events_rows, metric_rows = [], [], []
    with h5py.File(tmp, "w") as h5:
        h5.attrs.update(mock=True, synthetic=True, schema_version="1",
                        created=datetime.now().isoformat(timespec="seconds"),
                        note="FULLY SYNTHETIC demo data generated by make_demo_database.py - no real subject data")
        for k in range(1, args.subjects + 1):
            subj = make_subject(k, rng)
            session = f"{subj['date']}_markerless"
            sg = h5.create_group(f"subjects/{subj['id']}")
            sg.attrs.update(sex=subj["sex"], dominance=subj["dominance"])
            sess = sg.create_group(session)
            sess.attrs.update(date=subj["date"], system="markerless", height_m=subj["height_m"],
                              weight_kg=subj["weight_kg"], injured_side=subj["injured_side"],
                              injury="Synthetic", event_mode="Force Plates")

            plan = [("counter-movement-jump", "bilateral")] + [("squatting", v) for v in ("bilateral", "left", "right")]
            for movement, variant in plan:
                for trial in (1, 2, 3):
                    if movement == "counter-movement-jump":
                        signals, events, flight = cmj_trial(subj, rng)
                    else:
                        signals, events = squat_trial(subj, variant, rng)
                    n = len(next(iter(signals.values())))
                    t = np.arange(n) / RATE
                    metrics = (cmj_metrics(signals, events, flight, t) if movement == "counter-movement-jump"
                               else squat_metrics(signals, events, t))
                    path = f"/subjects/{subj['id']}/{session}/{movement}/{variant}/trial_{trial:02d}"
                    g = h5.create_group(path)
                    type_name = ("Counter-Movement Jump Markerless" if movement == "counter-movement-jump"
                                 else "Squatting Markerless" + ("" if variant == "bilateral" else f" {variant.title()}"))
                    g.attrs.update(source_file=f"{type_name} {trial}.c3d (synthetic)", type_name=type_name,
                                   n_frames=n, rate_hz=RATE, time_start=0.0, time_end=t[-1], source_export="synthetic")
                    for name, data in signals.items():
                        ds = g.create_dataset(f"signals/LINK_MODEL_BASED/ORIGINAL/{name}", data=data.astype(np.float32),
                                              compression="gzip", compression_opts=6, shuffle=True)
                        ds.attrs.update(name=name, components="XYZ", frame_start=1.0, frame_end=float(n),
                                        time_start=0.0, time_end=float(t[-1]))
                    n_ev = sum(len(v) for v in events.values())
                    trials.append({"trial_path": path, "subject": subj["id"], "session": session, "date": subj["date"],
                                   "system": "markerless", "movement": movement, "variant": variant, "trial": trial,
                                   "source_file": g.attrs["source_file"], "n_frames": n, "rate_hz": RATE,
                                   "time_start": 0.0, "time_end": float(t[-1]), "n_signals": len(signals),
                                   "n_events": n_ev, "n_metrics": len(metrics)})
                    events_rows += [{"trial_path": path, "name": e, "time": float(v)} for e, vs in events.items() for v in vs]
                    metric_rows += [{"trial_path": path, "folder": "PROCESSED", "name": nm, "component": c,
                                     "value": float(v), "aggregate": False} for nm, c, v in metrics]
            print(f"  {subj['id']}  {subj['sex']:6}  injured side: {subj['injured_side']}")

        tables = h5.create_group("tables")
        write_table(tables.create_group("trials"), pd.DataFrame(trials))
        write_table(tables.create_group("events"), pd.DataFrame(events_rows))
        write_table(tables.create_group("metrics"), pd.DataFrame(metric_rows))

    os.replace(tmp, args.out)
    print(f"\nWrote {args.out}  ({args.out.stat().st_size / 1e6:.1f} MB) - {len(trials)} synthetic trials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
