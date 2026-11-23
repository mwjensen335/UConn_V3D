"""Stage Theia3D output so the V3D pipelines can find each trial.

Theia writes every trial as  <trial folder>\\pose_filt_0.c3d , e.g.

    S005\\squatting markerless 1\\pose_filt_0.c3d
    S005\\squatting markerless left 2\\pose_filt_0.c3d

so all files share one name and the trial type lives only in the folder name.
"1) OPEN-PROCESS_UCONN_kinematics.v3s" finds trials by FILE name
(*_DLS_*_pose_filt_0.c3d, *_SLSL_*, *_SLSR_*, *_Jump-landing_*), so this script
COPIES each trial into one folder with a descriptive name:

    S005_DLS_01_pose_filt_0.c3d
    S005_SLSL_02_pose_filt_0.c3d

Original Theia files are never moved, renamed or modified.

Usage
-----
    python stage_theia.py "D:\\Theia\\S005" --subject S005 --dry-run   # show the plan only
    python stage_theia.py "D:\\Theia\\S005" --subject S005             # copy

Then in V3D run script 1 and point it at the staged folder
(default: V3D_Input\\<SUBJECT> inside this project).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Which Theia file to use from each trial folder (filtered pose, person 0).
POSE_FILE = "pose_filt_0.c3d"

# Folder name -> trial code used by the V3D scripts. First match wins, so the
# more specific rules (left/right) must come before the general squat rule.
# Matching ignores case. Edit these if your folder names differ.
TRIAL_RULES = [
    ("Jump-landing", r"jump|landing|\bjl\b"),
    ("SLSL",         r"squat.*\bleft\b|\bleft\b.*squat|\bsls\s*l\b|\bslsl\b"),
    ("SLSR",         r"squat.*\bright\b|\bright\b.*squat|\bsls\s*r\b|\bslsr\b"),
    ("DLS",          r"squat|\bdls\b"),
]


def classify(folder_name: str) -> str | None:
    for code, pattern in TRIAL_RULES:
        if re.search(pattern, folder_name, flags=re.IGNORECASE):
            return code
    return None


def trial_number(folder_name: str) -> int | None:
    nums = re.findall(r"\d+", folder_name)
    return int(nums[-1]) if nums else None


def plan(source: Path, subject: str) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Return ([(source file, new name)], [pose files we could not classify])."""
    staged, unknown = [], []
    for pose in sorted(source.rglob(POSE_FILE)):
        folder = pose.parent.name
        code = classify(folder)
        num = trial_number(folder)
        if code is None or num is None:
            unknown.append(pose)
            continue
        staged.append((pose, f"{subject}_{code}_{num:02d}_{POSE_FILE}"))
    return staged, unknown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="one subject's Theia output folder")
    ap.add_argument("--subject", required=True, help="subject ID used in the new names, e.g. S005")
    ap.add_argument("--out", type=Path, default=None,
                    help="where to put the staged copies (default: V3D_Input/<SUBJECT> in this project)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be copied, copy nothing")
    args = ap.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        print(f"Not a folder: {source}")
        return 1
    subject = re.sub(r"[^A-Za-z0-9-]+", "", args.subject)
    out = (args.out or Path(__file__).resolve().parent / "V3D_Input" / subject).resolve()

    staged, unknown = plan(source, subject)

    # Two folders mapping to the same name would overwrite each other.
    names = [n for _, n in staged]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print("These trial folders map to the same name - rename a folder or edit TRIAL_RULES:")
        for n in dupes:
            for src, name in staged:
                if name == n:
                    print(f"  {src.parent.name!r:45} -> {name}")
        return 1

    print(f"Source:  {source}")
    print(f"Staging: {out}{'   (dry run - nothing copied)' if args.dry_run else ''}\n")
    for src, name in staged:
        print(f"  {str(src.relative_to(source)):55} -> {name}")
    if unknown:
        print("\nCould not tell the trial type / number for these (NOT copied):")
        for u in unknown:
            print(f"  {u.relative_to(source)}")

    counts = {code: sum(f"_{code}_" in n for n in names) for code, _ in TRIAL_RULES}
    print("\nTrials found: " + ", ".join(f"{c} {k}" for c, k in counts.items()))
    missing = [c for c, k in counts.items() if k == 0]
    if missing:
        print(f"WARNING: no {', '.join(missing)} trials - script 1 stops if any trial type is missing.")

    if args.dry_run or not staged:
        return 0

    out.mkdir(parents=True, exist_ok=True)
    for src, name in staged:
        shutil.copy2(src, out / name)
    print(f"\nCopied {len(staged)} files. In V3D, run script 1 and select:\n  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
