# HDF5 database layout

One file holds every subject, session and trial. It's built by `rtp_ingest.py` from each Qualisys session folder's `session_data.xml` (V3D XML export) and `session.xml` (subject/session details).

## Structure

```
rtp_database.h5                                  attrs: schema_version, created
│
├── subjects/
│   └── RTP_006/                                 attrs: sex, dominance
│       └── 2026-06-18_markerless/               attrs: date, system, height_m, weight_kg,
│           │                                           injured_side, injury, event_mode
│           ├── counter-movement-jump/
│           │   └── bilateral/
│           │       ├── trial_01/                attrs: source_file, type_name, n_frames, rate_hz,
│           │       │   │                               time_start, time_end, source_export
│           │       │   └── signals/
│           │       │       ├── LINK_MODEL_BASED/ORIGINAL/Left Knee Angles   float32 (frames × 3)
│           │       │       ├── LINK_MODEL_BASED/ORIGINAL/Left Knee Moment   ...
│           │       │       └── DERIVED/PROCESSED/Left_RFD                   ...
│           │       ├── trial_02/ ...
│           │       └── trial_03/ ...
│           ├── squat-jump/bilateral/trial_01 ...
│           ├── squatting/{bilateral,left,right}/trial_01 ...
│           └── static/bilateral/trial_01
│
└── tables/                                      flat tables across ALL subjects
    ├── trials/    one row per trial
    ├── events/    one row per event occurrence
    └── metrics/   one row per metric value
```

Path pattern: `/subjects/<ID>/<date>_<system>/<movement>/<variant>/trial_NN/signals/<V3D type>/<V3D folder>/<signal name>`

- **movement / variant** come from the Qualisys trial name. `Squatting Markerless Left 2` becomes movement `squatting`, variant `left`, trial 2. A trial with no side word gets the variant `bilateral`.
- **system** (`markerless` / `markered`) comes from the trial name.
- The **static** trial appears in every session export but is stored once per session.

## Signals

Each signal dataset is `float32`, shaped `(n_frames, n_components)`, gzip-compressed. Attributes:

| Attribute | Meaning |
|---|---|
| `name` | V3D signal name (e.g. `Left Knee Angles`) |
| `components` | Component order of the columns, e.g. `XYZ` |
| `frame_start`, `frame_end` | V3D frame numbers of the first/last row |
| `time_start`, `time_end` | Seconds |

Frames that V3D exported as `nodata` are stored as `NaN`.

## Tables

Each table is a group of equal-length column datasets (strings are UTF-8).

**`tables/trials`:** `trial_path, subject, session, date, system, movement, variant, trial, source_file, n_frames, rate_hz, time_start, time_end, n_signals, n_events, n_metrics`

**`tables/events`:** `trial_path, name, time` (seconds; an event that occurs twice has two rows)

**`tables/metrics`:** `trial_path, folder, name, component, value, aggregate`. `aggregate` is true for V3D's own `_MEAN`/`_STDDEV` rows; `v3d_db.metrics()` drops them by default, so compute summaries from the per-trial values instead.

`trial_path` joins every table to the trial group, and to the other tables.

## Reading it

Python: `v3d_db.py` wraps all of this:

```python
import v3d_db as db
db.trials(); db.events(); db.metrics(); db.metrics_wide("squat-jump")
db.load_signal(trial_path, "Left Knee Moment")             # DataFrame: time, frame, X, Y, Z
db.curves("squatting", "Left Knee Angles", variant="left",
          start_event="LeftPlotStart", end_event="LeftPlotEnd", points=101)
```

MATLAB: `h5disp`, `h5read`, `h5readatt`. Note that MATLAB returns arrays transposed (components × frames).

Any HDF5 viewer (HDFView, or the VS Code "H5Web" extension) can browse the file.

## Design choices

- **Rebuilt, not edited.** The file is regenerated from the V3D exports each run and written to a temporary file that is swapped in at the end. HDF5 does not handle concurrent writers or interrupted writes well, so there is one writer, and the exports stay the source of truth.
- **Raw trials, not averages.** Every frame of every trial is kept. Averaging and time-normalization happen at analysis time (`v3d_db.curves`).
- **V3D names for now.** Signals keep the names V3D exported. Mapping to the lab's standard names and sign convention is the next step (see `variable_dictionary.md`).
- **Size:** about 14 MB per subject for these four tests, so 30 subjects is about 400 MB.
