# V3D → HDF5 biomechanics pipeline

Takes motion capture data from **Qualisys** (markerless via Theia3D, or markered) through **Visual3D** and compiles every subject, session and trial into **one HDF5 file** that can be analyzed in Python or MATLAB, plus a dashboard for browsing it.

```
Qualisys capture ─► Theia3D (markerless) ─► Visual3D pipeline ─► session_data.xml ─► rtp_ingest.py ─► rtp_database.h5 ─► analysis / dashboard
                                            (runs per session,     (V3D XML export:   (Python)           (all subjects,
                                             Qualisys automation)   signals, events,                     one file)
                                                                    metrics)
```

## Status (November 2026)

| | |
|---|---|
| **Works end to end** | One pilot subject (RTP_006, markerless): counter-movement jump, squat jump, squatting (bilateral / left / right) and static. 16 trials, 44 signals per trial at 200 Hz (joint angles, moments, powers, GRF), 174 events, ~3,600 metric values. Stored values verified against the V3D export. |
| **Mock-up** | `mock_database.h5`: 10 **synthetic** subjects generated from the pilot subject, to show what multi-subject analysis and the dashboard look like at scale. Not real data. |
| **Variable dictionary** | Catalogue of every variable computed by the lab's 10 V3D pipelines, with conflicts flagged (see [docs/variable_dictionary.md](docs/variable_dictionary.md)). |
| **Open items** | See [Next steps](#next-steps). |

## Quick start

```bash
pip install -r requirements.txt

python rtp_ingest.py "path\to\RTP-Assessment\Data"   # build the real database from all subject folders
python make_mock_database.py                          # optional: 10-subject mock database
streamlit run dashboard.py                            # browse either database
```

The database is **rebuilt from the V3D exports on every run**. The exports are the source of truth, so a new subject means: add their folder, re-run.

## Try it without real data

**[docs/tutorial.ipynb](docs/tutorial.ipynb)** is a step-by-step walkthrough, readable on GitHub with all outputs and figures. It covers:
- opening the database and looking inside the file;
- plotting one trial with its events;
- time-normalizing every trial;
- pulling metrics into a table;
- body-weight normalization and limb symmetry (injured vs uninjured);
- a correlation;
- exporting to CSV.

It runs on **`demo/demo_database.h5`**, a **fully synthetic** dataset of 12 subjects with CMJ and squats, generated from simple movement models by `make_demo_database.py`. It contains no real subject data and is safe to share. The same code runs on the real database by changing one path.

## Using the data

**Python**

```python
import v3d_db as db

db.summary()                                              # subjects / movements / trial counts
cmj = db.metrics_wide("counter-movement-jump")            # one row per trial, one column per metric
knee = db.curves("counter-movement-jump", "Left Knee Angles", component="X",
                 start_event="LeftPlotStart", end_event="LeftPlotEnd")   # every trial, 0-100 %
```

**MATLAB** (HDF5 is read natively)

```matlab
f = 'database/rtp_database.h5';
h5disp(f, '/subjects/RTP_006', 'min')
knee = h5read(f, '/subjects/RTP_006/2026-06-18_markerless/counter-movement-jump/bilateral/trial_01/signals/LINK_MODEL_BASED/ORIGINAL/Left Knee Angles');
% MATLAB returns components x frames (3 x N): use knee' for N x 3
```

The full file layout is in [docs/hdf5_layout.md](docs/hdf5_layout.md).

## Dashboard

`streamlit run dashboard.py` opens a browser page with three tabs. Switch between the real and mock databases in the sidebar.

- **Overview:** subjects, sessions, trials per movement.
- **Curves:** any signal and component for every trial, raw time or normalized between two events, with subject means. There's a table view and a CSV download.
- **Metrics:** per-trial values of any metric by subject, with a summary table and a CSV of all metrics.

## Repository contents

| Path | What it is |
|---|---|
| `rtp_ingest.py` | Builds the HDF5 database from Qualisys/V3D session exports |
| `v3d_db.py` | Reads the database into pandas (tables, curves, normalization) |
| `dashboard.py` | Streamlit dashboard |
| `make_demo_database.py`, `demo/demo_database.h5` | Fully synthetic demo dataset (shareable), used by the tutorial |
| `make_mock_database.py` | Lab-only mock: perturbed copies of a real subject's trials (not shareable, not in the repo) |
| `build_dictionary.py`, `v3s_parser.py` | Parse every V3D pipeline (`.v3s`, `.mdh`) into the variable dictionary |
| `dictionary/` | The variable dictionary: `standard_names.csv` and `pipelines.csv` (edited by hand) and `v3d_dictionary.xlsx` (generated report) |
| `RTP-Assessment/` | Reference copies of the Qualisys RTP-Assessment V3D pipelines (CMJ, SJ, squatting, static) and `Theia.mdh`, with subject paths replaced by placeholders |
| `*.v3s` (root), `Theia3DxLESS-main/` | Other lab V3D pipelines (UCONN kinematics, gait, football throw, Theia LESS), catalogued by the dictionary. `Theia3DxLESS-main` is third-party (CC BY-NC-SA 4.0, J. Outerleys) |
| `docs/` | Detailed documentation |

`stage_theia.py`, `_debug/` and `4) EXPORT-DB_UCONN_kinematics.v3s` are from an earlier approach that exported from V3D directly. The Qualisys exports made them unnecessary for RTP data, and they are kept only for the UCONN pipeline.

## Data and privacy

- **No subject data is in this repository.** `.gitignore` excludes subject folders, capture files (`.qtm`, `.c3d`, video), V3D workspaces and all `.h5` databases.
- **The database stores only:** subject ID, sex, dominance, height, weight, injured side, injury and event mode. Names, date of birth, e-mail, comments and injury history from Qualisys `session.xml` are never read. The code also never uses the Qualisys subject folder name (`<LastName>_<ID>`).
- **The mock database is derived from a real subject's data**, so keep it off GitHub as well and share it only within the lab.
- **`demo/demo_database.h5` is the only database in the repository.** It's generated from equations, with no real subject behind it.

## Next steps

1. **`Lower_body.mdh`:** copy it (or the whole `RTP-Assessment\Templates\Assets\Models\` folder) from the lab PC. The knee/hip/pelvis/thorax/arm angles and knee/hip kinetics aren't defined in any file here yet, and are most likely in that template, so the dictionary can't describe them until it's added.
2. **Standard names and sign conventions in the database.** The database currently uses V3D's names (`Left Knee Angles`). Once the dictionary covers the RTP signals, the import can map them to the lab's standard names and apply the agreed sign convention.
3. **More subjects:** run more RTP subjects through Qualisys and re-run `rtp_ingest.py`. At about 14 MB per subject, 30 subjects is about 400 MB, so store the database on a local or lab drive, not OneDrive.
4. **V3D-side clean-up** listed in the dictionary's Conflicts tab: one gait angle sequence, LAB as the lab reference, RTX as the trunk.
5. **Markered data:** add a markered session once one is processed. The import already records `markered` or `markerless` per session.
