"""Build a lab-wide variable dictionary from every Visual3D pipeline (.v3s).

Usage
-----
    python build_dictionary.py                 # scan the folder this script is in
    python build_dictionary.py --root "R:\\path\\to\\pipelines"

Outputs (in ./dictionary/)
--------------------------
    pipelines.csv        EDIT: which pipeline, movement and capture system each
                         script belongs to. New scripts are added with guesses;
                         your edits are kept on re-run.
    standard_names.csv   EDIT: the master variable list, one row per unique
                         model-based definition (function + segment + reference +
                         Cardan sequence). Set `standard_name`, `units`,
                         `description` here; your edits are kept on re-run.
    v3d_dictionary.xlsx  GENERATED: full report (definitions, every signal,
                         metric, event and export, plus conflicts). Rebuilt on
                         every run, so don't edit it.

Adding a new movement (pitching, running, ...) is just: drop its .v3s into the
folder, re-run, then check its row in pipelines.csv.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from v3s_parser import Command, parse_v3s

OUT_DIRNAME = "dictionary"

# ----------------------------------------------------------------------------
# Visual3D naming conventions
# ----------------------------------------------------------------------------
SEGMENTS = {
    "RPV": "Pelvis",
    "RTA": "Torso (thorax/abdomen)",
    "RTX": "Trunk",
    "RHE": "Head",
    "LTH": "Left thigh", "RTH": "Right thigh",
    "LSK": "Left shank", "RSK": "Right shank",
    "LFT": "Left foot", "RFT": "Right foot",
    "LTO": "Left toe/forefoot", "RTO": "Right toe/forefoot",
    "LMF": "Left midfoot (Theia.mdh)", "RMF": "Right midfoot (Theia.mdh)",
    "LAR": "Left upper arm", "RAR": "Right upper arm",
    "LFA": "Left forearm", "RFA": "Right forearm",
    "LHA": "Left hand", "RHA": "Right hand",
    "LAB": "Lab (global)",
    "": "Lab (global, default)",
    "VLB": "Virtual lab segment",
    "VIRTUAL LAB": "Virtual lab segment",
}
CENTRAL = {"RPV", "RTA", "RTX", "RHE"}  # single segments that carry an R prefix
PART = {
    "PV": "PELVIS", "TA": "TORSO", "TX": "TRUNK", "HE": "HEAD",
    "TH": "THIGH", "SK": "SHANK", "FT": "FOOT", "TO": "TOE", "MF": "MIDFOOT",
    "AR": "UPPER_ARM", "FA": "FOREARM", "HA": "HAND",
}
LAB_REFS = {"": "LAB", "LAB": "LAB", "VLB": "VIRTUAL_LAB", "VIRTUAL LAB": "VIRTUAL_LAB"}
LAB_SUFFIX = {"LAB": "_LAB", "VIRTUAL_LAB": "_VLAB"}

# Lab-wide decisions. Anything that deviates is listed on the Conflicts tab.
# Cardan (angle) sequence is NOT standardized: it is chosen per movement and
# stored as metadata alongside the data.
LAB_STANDARDS = {
    "trunk_segment": "RTX",   # not RTA
    "lab_reference": "LAB",   # not blank, VLB or 'Virtual Lab'
}
TRUNK_CODES = {"RTX", "RTA"}
JOINTS = {
    ("THIGH", "PELVIS"): "HIP", ("SHANK", "THIGH"): "KNEE",
    ("FOOT", "SHANK"): "ANKLE", ("MIDFOOT", "SHANK"): "ANKLE", ("TOE", "FOOT"): "MTP",
    ("UPPER_ARM", "TORSO"): "SHOULDER", ("UPPER_ARM", "TRUNK"): "SHOULDER",
    ("FOREARM", "UPPER_ARM"): "ELBOW", ("HAND", "FOREARM"): "WRIST",
    ("HEAD", "TORSO"): "NECK", ("HEAD", "TRUNK"): "NECK",
}
PROX_JOINT = {"THIGH": "HIP", "SHANK": "KNEE", "FOOT": "ANKLE", "TOE": "MTP",
              "UPPER_ARM": "SHOULDER", "FOREARM": "ELBOW", "HAND": "WRIST"}
DIST_JOINT = {"THIGH": "KNEE", "SHANK": "ANKLE", "FOOT": "MTP",
              "UPPER_ARM": "ELBOW", "FOREARM": "WRIST"}
FUNC_SUFFIX = {
    "JOINT_ANGLE": "ANGLE", "JOINT_VELOCITY": "ANGVEL",
    "JOINT_ACCELERATION": "ANGACC", "JOINT_MOMENT": "MOMENT",
    "JOINT_POWER": "POWER", "JOINT_FORCE": "FORCE",
}
POSITION_FUNCS = {"SEG_PROXIMAL_JOINT", "SEG_DISTAL_JOINT", "TARGET_PATH", "MODEL_COG"}
UNITS = {"ANGLE": "deg", "ANGVEL": "deg/s", "ANGACC": "deg/s^2",
         "MOMENT": "N*m", "POWER": "W", "FORCE": "N", "POS": "m"}

# Order matters only for display. Patterns are matched against the script's
# path first, then (if nothing matched) against its command parameters.
MOVEMENTS = [
    ("counter-movement-jump", r"(?i:counter.?movement)|(?<![A-Za-z])CMJ(?![A-Za-z])"),
    ("squat-jump", r"(?i:squat.?jump)|(?<![A-Za-z])SJ(?![A-Za-z])"),
    ("static", r"(?i:static)"),
    ("jump-landing", r"(?i:jump.?landing|landing)|(?<![A-Za-z])JL(?![A-Za-z])|LESS"),
    ("squat", r"(?i:squat)|(?<![A-Za-z])[DS]LS[LR]?(?![A-Za-z])"),
    ("gait", r"(?i:gait|walk)"),
    ("running", r"(?i:running|sprint|(?<![a-z])run(?![a-z]))"),
    ("pitching", r"(?i:pitch)"),
    ("throwing", r"(?i:throw)"),
]
MARKERLESS_HINT = re.compile(r"(?i)pose_filt|_4x4|theia")
MARKERED_HINT = re.compile(r"(?i)\.mdh\b|Apply_Model_Template")


# ----------------------------------------------------------------------------
# Pipeline discovery / config
# ----------------------------------------------------------------------------
def discover_scripts(root: Path, out_dir: Path) -> list[Path]:
    """All .v3s pipelines and .mdh model templates (same command syntax).

    Skipped: folders starting with "_" (scratch/test scripts), and anything
    inside a Qualisys project/subject data folder (one holding data.qpr) -
    every subject carries a copy of the same pipelines and those folder
    names contain surnames. Keep one reference copy elsewhere instead
    (see RTP-Assessment/)."""
    def in_data_folder(p: Path) -> bool:
        return any((d / "data.qpr").exists() for d in p.parents if root in d.parents or d == root)

    return sorted(
        p for ext in ("*.v3s", "*.mdh") for p in root.rglob(ext)
        if out_dir not in p.parents and ".git" not in p.parts
        and not any(part.startswith("_") for part in p.relative_to(root).parts[:-1])
        and not in_data_folder(p)
    )


def guess_pipeline(rel: Path, root_stems: list[str]) -> str:
    if len(rel.parts) > 1:  # scripts in a subfolder form one pipeline
        return re.sub(r"-main$", "", rel.parts[0])
    stem = re.sub(r"^\d+\)\s*", "", rel.stem)
    m = re.match(r"^[A-Z][A-Z-]*_(.+)$", stem)  # e.g. EXPORT_UCONN_kinematics
    if m and sum(s.endswith("_" + m.group(1)) for s in root_stems) >= 2:
        return m.group(1)
    return stem


def guess_movements(text: str) -> list[str]:
    return [label for label, pat in MOVEMENTS if re.search(pat, text)]


def guess_system(text: str) -> str:
    if MARKERLESS_HINT.search(text):
        return "markerless"
    if MARKERED_HINT.search(text):
        return "markered"
    return "unknown"


def load_pipeline_config(
    csv_path: Path, root: Path, scripts: list[Path], parsed: dict[Path, list[Command]]
) -> pd.DataFrame:
    cols = ["file", "pipeline", "movement", "system", "notes"]
    existing = {}
    if csv_path.exists():
        old = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        old = old.apply(lambda col: col.str.strip())  # stray spaces from hand edits
        if "system" in old:
            old["system"] = old["system"].str.lower()
        existing = {r["file"]: r for r in old.to_dict("records")}

    rels = [s.relative_to(root) for s in scripts]
    root_stems = [re.sub(r"^\d+\)\s*", "", r.stem) for r in rels if len(r.parts) == 1]

    rows, new_rows = [], []
    for script, rel in zip(scripts, rels):
        key = rel.as_posix()
        if key in existing:
            rows.append({c: existing[key].get(c, "") for c in cols})
            continue
        params_text = " ".join(
            v for cmd in parsed[script] for v in cmd.params.values()
        )
        moves = guess_movements(key) or guess_movements(params_text)
        row = {
            "file": key,
            "pipeline": guess_pipeline(rel, root_stems),
            "movement": "; ".join(moves),
            "system": guess_system(key + " " + params_text),
            "notes": "auto-guessed, please check",
        }
        rows.append(row)
        new_rows.append(row)

    df = pd.DataFrame(rows, columns=cols)

    # Share guesses across the files of one pipeline (only for new rows).
    new_files = {r["file"] for r in new_rows}
    order = [m[0] for m in MOVEMENTS]
    for _, grp in df.groupby("pipeline"):
        new_idx = [i for i in grp.index if df.at[i, "file"] in new_files]
        if not new_idx:
            continue
        moves = sorted({m.strip() for v in grp["movement"] for m in v.split(";")
                        if m.strip() in order}, key=order.index)
        systems = set(grp["system"]) - {"unknown", ""}
        for i in new_idx:
            df.at[i, "movement"] = "; ".join(moves) or "unknown"
            if len(systems) == 1:
                df.at[i, "system"] = next(iter(systems))
    return df


# ----------------------------------------------------------------------------
# Naming helpers
# ----------------------------------------------------------------------------
def seg_parts(code: str) -> tuple[str, str]:
    c = code.strip().upper()
    if c in CENTRAL:
        return "", PART[c[1:]]
    if len(c) == 3 and c[0] in "LR" and c[1:] in PART:
        return c[0], PART[c[1:]]
    return "", re.sub(r"\W+", "_", c)


def ref_frame(ref: str) -> str:
    return LAB_REFS.get(ref.strip().upper(), ref.strip())


def cardan_of(cmd: Command) -> str:
    return "".join(cmd.get(f"AXIS{i}", "XYZ"[i - 1]).strip().upper() for i in (1, 2, 3))


def negate_of(cmd: Command) -> str:
    return "".join(a for a in "XYZ" if cmd.get(f"NEGATE{a}").strip().upper() == "TRUE")


def where_suffix(ref_canon: str, ref_raw: str) -> str:
    if ref_canon in LAB_SUFFIX:
        return LAB_SUFFIX[ref_canon]
    side, part = seg_parts(ref_raw)
    return f"_WRT_{side + '_' if side else ''}{part}"


def propose_name(func: str, seg: str, ref_raw: str, res_cs: str = "") -> str:
    """Readable base name. Cardan sequence / sign flips are only added later
    (see `disambiguate`) when two different definitions would share a name."""
    side, part = seg_parts(seg)
    pre = f"{side}_" if side else ""
    ref_canon = ref_frame(ref_raw)
    where = where_suffix(ref_canon, ref_raw)

    if func in FUNC_SUFFIX:
        suf = FUNC_SUFFIX[func]
        if ref_canon in LAB_SUFFIX:
            name = f"{pre}{part}_{suf}{where}"
        else:
            _, ref_part = seg_parts(ref_raw)
            joint = JOINTS.get((part, ref_part))
            name = f"{pre}{joint}_{suf}" if joint else f"{pre}{part}{where}_{suf}"
    elif func in ("SEG_PROXIMAL_JOINT", "SEG_DISTAL_JOINT"):
        prox = func == "SEG_PROXIMAL_JOINT"
        jc = (PROX_JOINT if prox else DIST_JOINT).get(part, f"{part}_{'PROX' if prox else 'DIST'}")
        name = f"{pre}{jc}_POS{where}"
    elif func == "TARGET_PATH":
        target = re.sub(r"\W+", "_", seg.upper())
        name = f"{target}_POS{where}"
    elif func == "MODEL_COG":
        name = f"COM_POS{where}"
    else:
        name = f"{pre}{part}_{func}{where}"

    # Expressed in a different coordinate system than the reference?
    if res_cs and ref_frame(res_cs) != ref_canon:
        name += "_IN" + where_suffix(ref_frame(res_cs), res_cs).replace("_WRT", "")
    return name


def disambiguate(defs: pd.DataFrame) -> pd.Series:
    """Make proposed names unique by adding a version number where different
    definitions would otherwise collide."""
    names = defs["proposed_name"].copy()
    dup = names.duplicated(keep=False)
    for base, idx in names[dup].groupby(names[dup]).groups.items():
        for n, i in enumerate(idx):
            if n:
                names[i] = f"{base}_v{n + 1}"
    return names


def majority_sign(g: pd.DataFrame) -> str:
    """Most common sign-flip setting for a definition (ties -> fewer flips).
    Returned as e.g. 'YZ', or 'none'."""
    counts = g.groupby("negate").size()
    best = sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]
    return best or "none"


def sign_correction(row_negate: str, standard: str) -> str:
    """Components to multiply by -1 at ingest so this export matches the standard."""
    std = "" if standard.strip().lower() == "none" else standard.strip().upper()
    return "".join(sorted(set(row_negate) ^ set(std)))


def quantity_of(func: str) -> str:
    if func in FUNC_SUFFIX:
        return FUNC_SUFFIX[func]
    if func in POSITION_FUNCS:
        return "POS"
    return func


# ----------------------------------------------------------------------------
# Existing hand-made dictionaries (e.g. football-throw-pipeline-dictionary.xlsx)
# ----------------------------------------------------------------------------
def load_existing_descriptions(root: Path, out_dir: Path) -> dict[str, dict]:
    desc: dict[str, dict] = {}
    for xlsx in root.rglob("*.xlsx"):
        if out_dir in xlsx.parents or xlsx.name.startswith("~$"):
            continue
        try:
            sheets = pd.read_excel(xlsx, sheet_name=None, dtype=str)
        except Exception as exc:  # unreadable/locked workbook: skip, don't fail
            print(f"  ! could not read {xlsx.name}: {exc}")
            continue
        for df in sheets.values():
            cols = {str(c).strip().upper(): c for c in df.columns}
            if "RESULT NAME" not in cols:
                continue
            for _, r in df.iterrows():
                names = str(r[cols["RESULT NAME"]] or "")
                info = {
                    "measure": r.get(cols.get("MEASURE"), "") if "MEASURE" in cols else "",
                    "method": r.get(cols.get("METHOD"), "") if "METHOD" in cols else "",
                    "source_dictionary": xlsx.name,
                }
                info = {k: ("" if pd.isna(v) else str(v).strip()) for k, v in info.items()}
                for n in re.split(r"[\n,;]+", names):
                    if n.strip() and n.strip().upper() != "NAN":
                        desc.setdefault(n.strip().upper(), info)
    return desc


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------
def extract(script: Path, rel: str, cmds: list[Command], cfg: dict) -> dict[str, list[dict]]:
    base = {"pipeline": cfg["pipeline"], "movement": cfg["movement"],
            "system": cfg["system"], "file": rel}
    out = defaultdict(list)

    for cmd in cmds:
        loc = {**base, "line": cmd.line, "command": cmd.name}

        if cmd.name == "Compute_Model_Based_Data" and cmd.get("FUNCTION"):
            func = cmd.get("FUNCTION").strip().upper()
            seg = cmd.get("SEGMENT").strip()
            ref = cmd.get("REFERENCE_SEGMENT").strip()
            cardan = cardan_of(cmd)
            negate = negate_of(cmd)
            res_cs = cmd.get("RESOLUTION_COORDINATE_SYSTEM").strip()
            name = cmd.get("RESULT_NAME").strip()
            # Cardan sequence and sign flips are deliberately not part of the key:
            # the sequence is chosen per movement (metadata), and signs are
            # normalized to one convention per variable at ingest.
            key = "|".join([func, seg.upper(), ref_frame(ref), res_cs.upper()])
            out["model"].append({
                **loc,
                "name": name,
                "def_key": key,
                "function": func,
                "segment": seg,
                "segment_desc": SEGMENTS.get(seg.upper(), "target/marker" if func == "TARGET_PATH" else "UNKNOWN CODE"),
                "reference": ref,
                "reference_desc": SEGMENTS.get(ref.upper(), "UNKNOWN CODE"),
                "reference_frame": ref_frame(ref),
                "cardan": cardan,
                "resolution_cs": res_cs,
                "negate": negate,
                "result_folder": cmd.get("RESULT_FOLDER") or cmd.get("FOLDER"),
                "proposed_name": propose_name(func, seg, ref, res_cs),
                "quantity": quantity_of(func),
                "template_values": cmd.template_values(name),
            })

        elif cmd.get("RESULT_METRIC_NAME"):
            name = cmd.get("RESULT_METRIC_NAME").strip()
            source = "::".join(x for x in (cmd.get("SIGNAL_TYPES"), cmd.get("SIGNAL_FOLDER"),
                                           cmd.get("SIGNAL_NAMES")) if x)
            events = "; ".join(f"{k}={cmd.get(k)}" for k in
                               ("EVENT_NAME", "EVENT_SEQUENCE", "EXCLUDE_EVENTS", "EVENT_INSTANCE")
                               if cmd.get(k))
            value = cmd.get("METRIC_VALUE") or cmd.get("EXPRESSION")
            component = cmd.get("COMPONENT_SEQUENCE") or cmd.get("SIGNAL_COMPONENTS")
            # APPLY_AS_SUFFIX_TO_SIGNAL_NAME: V3D names the result <signal><suffix>,
            # one metric per input signal (e.g. "Left Knee Angles@COM_MIN_CMJ_B").
            as_suffix = cmd.get("APPLY_AS_SUFFIX_TO_SIGNAL_NAME").strip().upper() == "TRUE"
            signals = [s.strip() for s in cmd.get("SIGNAL_NAMES").split("+") if s.strip()]
            pairs = [(s + name, s) for s in signals] if as_suffix and signals else [(name, cmd.get("SIGNAL_NAMES"))]
            for full_name, sig in pairs:
                src = "::".join(x for x in (cmd.get("SIGNAL_TYPES"), cmd.get("SIGNAL_FOLDER"), sig) if x)
                out["metrics"].append({
                    **loc,
                    "name": full_name,
                    "folder": cmd.get("RESULT_METRIC_FOLDER") or "PROCESSED (default)",
                    "source_signal": src,
                    "component": component,
                    "events": events,
                    "value_or_expression": value,
                    "definition": " | ".join([cmd.name, src, component, events, value]),
                    "template_values": cmd.template_values(full_name + " " + src),
                })

        elif cmd.name.startswith("Event_") and cmd.name not in ("Event_Delete", "Event_Rename"):
            name = (cmd.get("RESULT_EVENT_NAME") or cmd.get("NEW_EVENT_NAME")
                    or (cmd.get("EVENT_NAME") if cmd.name == "Event_Explicit" else "")).strip()
            if not name:
                continue
            source = "::".join(x for x in (cmd.get("SIGNAL_TYPES"), cmd.get("SIGNAL_FOLDER"),
                                           cmd.get("SIGNAL_NAMES")) if x)
            settings = "; ".join(f"{k}={cmd.get(k)}" for k in
                                 ("SIGNAL_COMPONENTS", "THRESHOLD", "FRAME_OFFSET", "FRAME_WINDOW",
                                  "EVENT_SEQUENCE", "EVENT_INSTANCE", "ON_ASCENT", "ON_DESCENT",
                                  "TIME", "FRAME")
                                 if cmd.get(k))
            out["events"].append({**loc, "name": name, "source_signal": source,
                                  "settings": settings,
                                  "template_values": cmd.template_values(name + source)})

        elif cmd.name.startswith("Export_"):
            target = (cmd.get("FILE_NAME") or cmd.get("EXPORT_FILENAME")
                      or cmd.get("FILENAME"))
            flags = "; ".join(f"{k}={v}" for k, v in cmd.params.items()
                              if k.startswith(("USE_", "NORMALIZE", "EXPORT_MEAN")))
            out["exports"].append({
                **loc,
                "file_name": target,
                "signal_types": cmd.get("SIGNAL_TYPES"),
                "signal_names": cmd.get("SIGNAL_NAMES") or cmd.get("METRIC_NAMES"),
                "format_flags": flags or ("(defaults: ASCII text)" if "Ascii" in cmd.name else "(defaults)"),
                "template_values": cmd.template_values(target + cmd.get("SIGNAL_NAMES")),
            })

        elif cmd.get("RESULT_NAME"):  # derived / processed signals
            name = cmd.get("RESULT_NAME").strip()
            inputs = cmd.get("EXPRESSION") or "::".join(
                x for x in (cmd.get("SIGNAL_TYPES"), cmd.get("SIGNAL_FOLDER"),
                            cmd.get("SIGNAL_NAMES")) if x)
            out["derived"].append({
                **loc,
                "name": name,
                "result_type": cmd.get("RESULT_TYPES"),
                "result_folder": cmd.get("RESULT_FOLDERS") or cmd.get("RESULT_FOLDER"),
                "inputs_or_expression": inputs,
                "template_values": cmd.template_values(name + inputs),
            })
    return out


# ----------------------------------------------------------------------------
# Master definitions + conflicts
# ----------------------------------------------------------------------------
def by_movement(model: pd.DataFrame) -> pd.DataFrame:
    """One row per (signal row, movement) - a script can cover several movements."""
    m = model.assign(movement=model["movement"].str.split(";")).explode("movement")
    m["movement"] = m["movement"].str.strip().replace("", "unknown")
    return m


def cardan_by_movement(g: pd.DataFrame) -> str:
    if g["function"].iloc[0] not in FUNC_SUFFIX:
        return ""
    m = by_movement(g)
    return " | ".join(f"{mv}: {'/'.join(sorted(set(gg['cardan'])))}"
                      for mv, gg in m.groupby("movement"))


def build_definitions(model: pd.DataFrame, names_csv: Path, desc: dict) -> pd.DataFrame:
    cols = ["def_key", "standard_name", "sign_flip", "units", "description", "notes"]
    user = (pd.read_csv(names_csv, dtype=str, keep_default_na=False)
            if names_csv.exists() else pd.DataFrame(columns=cols))
    user = user.set_index("def_key") if len(user) else pd.DataFrame(columns=cols[1:])

    firsts = model.groupby("def_key", sort=False).first()
    firsts["proposed_name"] = disambiguate(firsts.reset_index()).values

    rows = []
    for key, g in model.groupby("def_key", sort=False):
        first = firsts.loc[key]
        used = (g.groupby("pipeline")["name"]
                 .apply(lambda s: ", ".join(sorted(set(s)))))
        known = next((desc[n.upper()] for n in g["name"] if n.upper() in desc), None)
        auto = {
            "standard_name": first["proposed_name"],
            "sign_flip": majority_sign(g) if first["function"] in FUNC_SUFFIX else "none",
            "units": UNITS.get(first["quantity"], ""),
            "description": (f"{first['segment_desc']} {first['function'].lower().replace('_', ' ')}"
                            f" relative to {first['reference_desc']}"
                            + (f" - {known['method']}" if known and known["method"] else "")),
            "notes": "",
        }
        if key in user.index:
            u = user.loc[key]
            auto.update({c: u[c] for c in cols[1:] if c in u and str(u[c]).strip()})
        rows.append({
            "def_key": key,
            **auto,
            "function": first["function"],
            "segment": first["segment"],
            "segment_desc": first["segment_desc"],
            "reference_frame": first["reference_frame"],
            "references_as_written": ", ".join(sorted({r or "(blank)" for r in g["reference"]})),
            "cardan_by_movement": cardan_by_movement(g),
            "resolution_cs": first["resolution_cs"],
            "n_pipelines": g["pipeline"].nunique(),
            "pipelines": ", ".join(sorted(g["pipeline"].unique())),
            "movements": "; ".join(sorted({m.strip() for v in g["movement"] for m in v.split(";") if m.strip()})),
            "systems": ", ".join(sorted(set(g["system"]))),
            "names_used": " | ".join(f"{p}: {n}" for p, n in used.items()),
        })
    defs = pd.DataFrame(rows).sort_values(["n_pipelines", "standard_name"], ascending=[False, True])

    # Keep user rows for definitions no longer present in any script.
    missing = [k for k in user.index if k not in set(defs["def_key"])]
    if missing:
        extra = user.loc[missing].reset_index()
        extra["notes"] = (extra["notes"] + " [not found in current scripts]").str.strip()
        defs = pd.concat([defs, extra], ignore_index=True)
    return defs


def find_conflicts(model: pd.DataFrame, metrics: pd.DataFrame, defs: pd.DataFrame,
                   cfg: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def add(severity, kind, subject, detail):
        rows.append({"severity": severity, "type": kind, "subject": subject, "detail": detail})

    def where(g):
        return ", ".join(sorted({f"{p}" for p in g["pipeline"]}))

    if len(model):
        # 1. Same name, different definition (the dangerous one)
        for name, g in model.groupby(model["name"].str.upper()):
            if g["def_key"].nunique() > 1:
                detail = " || ".join(
                    f"{k}  [{where(gg)}]" for k, gg in g.groupby("def_key"))
                add("HIGH", "SAME_NAME_DIFFERENT_DEFINITION", name, detail)

        # 2. Same definition, different names (e.g. LEFT_KNEE_ANGLE vs L_KNEE_ANGLE).
        #    Expected - standard_names.csv maps them all to one name.
        for key, g in model.groupby("def_key"):
            names = sorted(set(g["name"]))
            if len(names) > 1:
                detail = " || ".join(f"{n} [{where(g[g['name'] == n])}]" for n in names)
                add("INFO", "SAME_DEFINITION_DIFFERENT_NAMES", key,
                    detail + "  -> stored as " + defs.set_index("def_key").at[key, "standard_name"])

        # 3. Unknown segment codes, and deviations from the lab standards
        seg_check = model[~model["function"].isin(["TARGET_PATH", "MODEL_COG"])]
        trunk_std = LAB_STANDARDS["trunk_segment"]
        lab_std = LAB_STANDARDS["lab_reference"]
        for col in ("segment", "reference"):
            for code, g in seg_check.groupby(seg_check[col].str.upper()):
                if code not in SEGMENTS:
                    add("MEDIUM", "UNKNOWN_SEGMENT_CODE", code,
                        f"used as {col} in {where(g)}: not a standard V3D code")
                elif code in TRUNK_CODES and code != trunk_std:
                    add("MEDIUM", "NOT_LAB_STANDARD_TRUNK", code,
                        f"trunk is {code} as {col} in {where(g)}; lab standard is {trunk_std}")

        labish = seg_check[seg_check["reference_frame"].isin(LAB_SUFFIX)]
        for ref, g in labish.groupby(labish["reference"].str.upper()):
            if ref != lab_std:
                add("MEDIUM", "NOT_LAB_STANDARD_REFERENCE", ref or "(blank)",
                    f"{len(g)} calculations in {where(g)} use '{ref or '(blank)'}'; "
                    f"lab standard is {lab_std}"
                    + ("  (VLB is a virtual lab segment built in the script - switching to "
                       "LAB may change values if it is rotated)" if ref != "" else ""))

        # 4. Cardan sequence: chosen per movement on purpose, so only a problem
        #    when one movement uses two sequences for the same calculation.
        angles = by_movement(model[model["function"].isin(FUNC_SUFFIX)])
        for (key, mv), g in angles.groupby(["def_key", "movement"]):
            if g["cardan"].nunique() > 1:
                detail = " || ".join(f"{c} [{where(gg)}]" for c, gg in g.groupby("cardan"))
                add("HIGH", "CARDAN_DIFFERS_WITHIN_MOVEMENT", f"{key} ({mv})",
                    detail + f"  -> fix in V3D: pick one sequence for {mv}")

        # 5. Sign flips that the ingest will normalize to the standard convention
        if "sign_correction" in model:
            flips = model[model["sign_correction"] != ""]
            for key, g in flips.groupby("def_key"):
                std_sign = defs.set_index("def_key").at[key, "sign_flip"]
                detail = " || ".join(
                    f"{n} [{p}]: flip {c}" for (n, p, c), _ in
                    g.groupby(["name", "pipeline", "sign_correction"]))
                add("INFO", "SIGN_NORMALIZED_ON_INGEST", key,
                    f"standard sign_flip={std_sign}; {detail}")

    # 6. Metric name reused with a different definition by pipelines of the
    #    SAME movement (different movements may define a metric differently).
    if len(metrics):
        mm = by_movement(metrics)
        for (name, mv), g in mm.groupby([mm["name"].str.upper(), "movement"]):
            if g["pipeline"].nunique() > 1 and g["definition"].nunique() > 1:
                detail = " || ".join(f"{d} [{where(gg)}]" for d, gg in g.groupby("definition"))
                add("HIGH", "METRIC_NAME_DIFFERENT_DEFINITION", f"{name} ({mv})", detail)

    # 7. Duplicate standard names in the master list
    dup = defs[defs["standard_name"].duplicated(keep=False)]
    for n, g in dup.groupby("standard_name"):
        add("HIGH", "DUPLICATE_STANDARD_NAME", n,
            "several definitions share this standard_name: " + " || ".join(g["def_key"]))

    # 8. Pipelines whose movement/system still needs filling in
    for _, r in cfg.iterrows():
        for col in ("movement", "system"):
            if r[col].strip() in ("", "unknown"):
                add("INFO", f"CONFIG_{col.upper()}_UNKNOWN", r["file"],
                    f"set '{col}' for this script in dictionary/pipelines.csv")

    order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
    df = pd.DataFrame(rows, columns=["severity", "type", "subject", "detail"])
    return df.sort_values(["severity", "type", "subject"], key=lambda s: s.map(order) if s.name == "severity" else s)


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
README = [
    ("What this is", "Variable dictionary generated from every .v3s pipeline under the scanned folder."),
    ("Definitions", "One row per unique model-based calculation (function + segment + reference + resolution CS). "
                    "Cardan sequence is chosen per movement and shown in cardan_by_movement - it is stored as metadata, not part of the name. "
                    "sign_flip is the standard sign convention (components negated, or 'none'); exports that differ get "
                    "sign_correction applied at ingest (see Signals_ModelBased). "
                    "This is the master list. standard_name/units/description/notes come from standard_names.csv - edit that file, not this workbook."),
    ("Signals_ModelBased", "Every Compute_Model_Based_Data command, with the name each pipeline used and its def_key."),
    ("Signals_Derived", "Signals created by Evaluate_Expression, normalization, filtering, etc."),
    ("Metrics / Events", "Every metric and event each pipeline creates."),
    ("Exports", "What each pipeline writes out of V3D and in which format - this is what the HDF5 ingest will read."),
    ("Conflicts", "HIGH = will silently mix different measurements if pooled by name. Resolve these first."),
    ("Templated names", "Names containing ::PARAM are filled in by V3D at run time; template_values lists the known values."),
    ("Re-running", "python build_dictionary.py  - pipelines.csv and standard_names.csv edits are preserved."),
]
SEV_FILL = {"HIGH": "F8CBAD", "MEDIUM": "FFE699", "INFO": "DDEBF7"}


def write_xlsx(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            if len(df.columns) and len(df):
                ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="305496")
            for i, col in enumerate(df.columns, 1):
                lengths = [len(str(col))] + [len(str(v)) for v in df[col].head(300)]
                ws.column_dimensions[get_column_letter(i)].width = min(max(10, max(lengths) + 2), 70)
            if name == "Conflicts":
                for r, sev in enumerate(df["severity"], 2):
                    fill = PatternFill("solid", fgColor=SEV_FILL.get(sev, "FFFFFF"))
                    for c in range(1, len(df.columns) + 1):
                        ws.cell(r, c).fill = fill
                        ws.cell(r, c).alignment = Alignment(wrap_text=c == 4, vertical="top")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                    help="folder to scan for .v3s files (default: this script's folder)")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: <root>/dictionary)")
    args = ap.parse_args()

    root = args.root.resolve()
    out_dir = (args.out or root / OUT_DIRNAME).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    scripts = discover_scripts(root, out_dir)
    if not scripts:
        print(f"No .v3s files found under {root}")
        return 1
    print(f"Scanning {len(scripts)} .v3s/.mdh files under {root}")

    parsed = {s: parse_v3s(s) for s in scripts}
    cfg = load_pipeline_config(out_dir / "pipelines.csv", root, scripts, parsed)
    cfg.to_csv(out_dir / "pipelines.csv", index=False)
    cfg_by_file = {r["file"]: r for r in cfg.to_dict("records")}

    tables = defaultdict(list)
    for s in scripts:
        rel = s.relative_to(root).as_posix()
        for kind, rows in extract(s, rel, parsed[s], cfg_by_file[rel]).items():
            tables[kind].extend(rows)

    frames = {k: pd.DataFrame(v) for k, v in tables.items()}
    for k in ("model", "derived", "metrics", "events", "exports"):
        frames.setdefault(k, pd.DataFrame())

    desc = load_existing_descriptions(root, out_dir)
    for k in ("metrics", "derived", "events"):
        df = frames[k]
        if len(df):
            df["existing_description"] = df["name"].str.upper().map(
                lambda n: " - ".join(x for x in (desc.get(n, {}).get("measure", ""),
                                                 desc.get(n, {}).get("method", "")) if x))

    model = frames["model"]
    defs = build_definitions(model, out_dir / "standard_names.csv", desc) if len(model) else pd.DataFrame()
    if len(defs):
        defs[["def_key", "standard_name", "sign_flip", "units", "description", "notes"]].to_csv(
            out_dir / "standard_names.csv", index=False)
        std = dict(zip(defs["def_key"], defs["standard_name"]))
        std_sign = dict(zip(defs["def_key"], defs["sign_flip"]))
        model.insert(model.columns.get_loc("name") + 1, "standard_name", model["def_key"].map(std))
        model.insert(model.columns.get_loc("negate") + 1, "sign_correction",
                     [sign_correction(n, std_sign[k]) for n, k in zip(model["negate"], model["def_key"])])

    conflicts = find_conflicts(model, frames["metrics"], defs, cfg)

    pipe_summary = cfg.copy()
    for k, label in (("model", "n_model_signals"), ("derived", "n_derived"),
                     ("metrics", "n_metrics"), ("events", "n_events"), ("exports", "n_exports")):
        counts = frames[k].groupby("file").size() if len(frames[k]) else pd.Series(dtype=int)
        pipe_summary[label] = pipe_summary["file"].map(counts).fillna(0).astype(int)

    xlsx = out_dir / "v3d_dictionary.xlsx"
    try:
        write_xlsx(xlsx, {
            "README": pd.DataFrame(README, columns=["sheet / topic", "notes"]),
            "Pipelines": pipe_summary,
            "Definitions": defs,
            "Signals_ModelBased": model,
            "Signals_Derived": frames["derived"],
            "Metrics": frames["metrics"],
            "Events": frames["events"],
            "Exports": frames["exports"],
            "Conflicts": conflicts,
        })
    except PermissionError:
        print(f"\nCould not write {xlsx} - is it open in Excel? Close it and re-run.")
        return 1

    print(f"\n  pipelines:            {cfg['pipeline'].nunique()}  ({len(cfg)} scripts)")
    print(f"  model-based signals:  {len(model)} commands -> {len(defs)} unique definitions")
    print(f"  derived signals:      {len(frames['derived'])}")
    print(f"  metrics:              {len(frames['metrics'])}")
    print(f"  events:               {len(frames['events'])}")
    print(f"  exports:              {len(frames['exports'])}")
    if len(conflicts):
        print("  conflicts:            " + ", ".join(
            f"{n} {s}" for s, n in conflicts["severity"].value_counts().items()))
    print(f"\nWrote:\n  {out_dir / 'pipelines.csv'}\n  {out_dir / 'standard_names.csv'}\n  {xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
