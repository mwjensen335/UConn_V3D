# Variable dictionary

The lab's V3D pipelines each name and define variables their own way. For example, one pipeline's `LEFT_KNEE_ANGLE` is another's `L_KNEE_ANGLE`, and some identically named variables are computed differently. `build_dictionary.py` reads every pipeline (`.v3s`) and model template (`.mdh`) in the repository and catalogues every calculation, so the variables can be standardized before data are pooled.

```bash
python build_dictionary.py
```

## Files (`dictionary/`)

| File | Edited by | Contents |
|---|---|---|
| `pipelines.csv` | hand | Which pipeline, movement and capture system each script belongs to |
| `standard_names.csv` | hand | Master list: one row per unique calculation, with `standard_name`, `sign_flip`, `units`, `description`, `notes` |
| `v3d_dictionary.xlsx` | generated | Report: Definitions, every signal / metric / event / export, and **Conflicts** |

Hand edits to the two CSVs are kept when the script is re-run. New scripts are added with guessed values marked "auto-guessed, please check".

## What counts as the same variable

A **definition** is the V3D function plus the segment, reference segment and resolution coordinate system. For example, `JOINT_ANGLE | LSK | LTH` is the knee angle under any name. Two things are deliberately left out of the definition:

- **Cardan sequence**: chosen per movement and recorded as metadata (`cardan_by_movement`).
- **Sign flips** (`NEGATEX/Y/Z`): each variable has one standard sign convention (`sign_flip`). Exports that differ are corrected at import (`sign_correction`).

## Decisions so far

| Decision | Rule |
|---|---|
| Angle (Cardan) sequence | Set **per movement**. Different sequences across movements are allowed; two pipelines of the same movement must agree |
| Gait ankle sequence | **XYZ**. `example-gait-pipeline` (XZY) to be updated in V3D |
| Signs | Normalized to one convention per variable |
| Left/right naming | `LEFT_`/`L_` and similar spellings are naming only and map to one standard name |
| Trunk segment | **RTX** (not RTA) |
| Lab reference | **LAB** (not blank, `VLB` or `Virtual Lab`). Note that VLB is a virtual lab segment built in some scripts, so switching to LAB may change values if it is rotated |

## Conflict levels (Conflicts tab)

- **HIGH:** would silently mix different measurements if pooled by name: the same name with a different definition, two Cardan sequences within one movement, or a metric defined differently within one movement.
- **MEDIUM:** deviations from the lab standards above, and unknown segment codes.
- **INFO:** spelling differences resolved by standard names, and sign corrections applied at import.

Current status: 2 HIGH (gait ankle sequence, a V3D fix) and 7 MEDIUM (lab reference and trunk naming in older pipelines, plus `LFT_S`/`RFT_S` segments, probably defined in the missing `Lower_body.mdh`).

## Not yet covered

The RTP-Assessment knee, hip, pelvis, thorax and arm angles and knee/hip kinetics are not defined in any file here yet; they are most likely in `Lower_body.mdh` (referenced by the pipeline, on the lab PC). Until then, the dictionary covers the RTP ankle, foot, GRF and COP calculations only.
