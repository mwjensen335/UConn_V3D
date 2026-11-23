"""Dashboard for the V3D HDF5 database.

    streamlit run dashboard.py

Tabs: Overview (what's in the database), Curves (signals for every trial,
raw or time-normalized between two events), Metrics (per-trial values).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import v3d_db as db

# Categorical palette, fixed order (validated light-mode slots). Colors follow the
# entity: each subject/trial keeps its color regardless of what else is selected.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MAX_SERIES = len(SERIES)

st.set_page_config(page_title="V3D Database", layout="wide")


# Every loader takes the database path + its modification time, so switching
# files or rebuilding one refreshes the cache automatically.
@st.cache_data
def load(path: str, mtime: float):
    return db.trials(db_path=path), db.sessions(db_path=path)


@st.cache_data
def load_metrics(path: str, mtime: float):
    return db.metrics(db_path=path)


@st.cache_data
def load_events(path: str, mtime: float):
    return db.events(db_path=path)


@st.cache_data
def load_curves(path, mtime, movement, variant, signal, component, start, end):
    return db.curves(movement, signal, component=component, variant=variant,
                     start_event=start, end_event=end, db_path=path)


@st.cache_data
def load_signal_names(path, mtime, movement, variant):
    return db.signal_names(movement, variant, db_path=path)


@st.cache_data
def load_metrics_wide(path, mtime, movement, variant):
    return db.metrics_wide(movement, variant, db_path=path)


@st.cache_data
def is_mock(path: str, mtime: float) -> bool:
    import h5py
    with h5py.File(path, "r") as h5:
        return bool(h5.attrs.get("mock", False))


def color_map(keys) -> dict:
    """Stable entity -> color, by sorted order across the whole database."""
    return {k: SERIES[i % MAX_SERIES] for i, k in enumerate(sorted(keys, key=str))}


def style(fig: go.Figure, x_title: str, y_title: str, height=460) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10), hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(title=x_title, showgrid=False, zeroline=False),
        yaxis=dict(title=y_title, gridcolor="rgba(128,128,128,0.18)", zeroline=False),
    )
    return fig


HERE = Path(__file__).resolve().parent
files = sorted((HERE / "database").glob("*.h5")) + sorted((HERE / "demo").glob("*.h5"))
if not files:
    st.error("No database yet. Run `python rtp_ingest.py` (real data), "
             "`python make_mock_database.py` (mock) or `python make_demo_database.py` (synthetic demo) first.")
    st.stop()

names = [p.name for p in files]
default = names.index(db.DEFAULT_DB.name) if db.DEFAULT_DB.name in names else 0
db_file = files[names.index(st.sidebar.radio("Database", names, index=default, key="db_file"))]
DB = str(db_file)
mtime = db_file.stat().st_mtime
trials, sessions = load(DB, mtime)

st.title("V3D Database")
if is_mock(DB, mtime):
    import h5py
    with h5py.File(DB, "r") as _f:
        note = str(_f.attrs.get("note", "synthetic subjects"))
    st.warning(f"**NOT REAL DATA** - {note}. For demonstrating the layout only.", icon="⚠️")
st.caption(f"{db_file.name} - built {pd.Timestamp.fromtimestamp(mtime):%Y-%m-%d %H:%M}. "
           "Rebuild with `python rtp_ingest.py`.")

tab_overview, tab_curves, tab_metrics = st.tabs(["Overview", "Curves", "Metrics"])

# ----------------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------------
with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Subjects", trials["subject"].nunique())
    c2.metric("Sessions", trials[["subject", "session"]].drop_duplicates().shape[0])
    c3.metric("Movements", trials["movement"].nunique())
    c4.metric("Trials", len(trials))

    st.subheader("Trials per movement")
    st.dataframe(
        trials.groupby(["movement", "variant"])
              .agg(subjects=("subject", "nunique"), trials=("trial_path", "size"),
                   signals=("n_signals", "max"), metrics=("n_metrics", "max"))
              .reset_index(),
        hide_index=True, width="stretch")

    st.subheader("Sessions")
    st.dataframe(sessions, hide_index=True, width="stretch")

    with st.expander("All trials"):
        st.dataframe(trials.drop(columns=["trial_path"]), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------
# Curves
# ----------------------------------------------------------------------------
with tab_curves:
    f1, f2, f3, f4 = st.columns([2, 1, 3, 1])
    movement = f1.selectbox("Movement", sorted(trials["movement"].unique()), key="c_mov")
    variants = sorted(trials.loc[trials["movement"] == movement, "variant"].unique())
    variant = f2.selectbox("Variant", variants, key="c_var")
    names = load_signal_names(DB, mtime, movement, variant)
    default = next((i for i, n in enumerate(names) if "Knee Angles" in n), 0)
    signal = f3.selectbox("Signal", names, index=default, key="c_sig")
    component = f4.selectbox("Component", ["X", "Y", "Z"], key="c_comp")

    ev = load_events(DB, mtime)
    ev_names = sorted(ev.loc[(ev["movement"] == movement) & (ev["variant"] == variant), "name"].unique())
    g1, g2, g3, g4 = st.columns([1, 2, 2, 2])
    normalize = g1.toggle("Normalize", value=bool(ev_names),
                          help="Cut each trial between two events and resample to 0-100 %")
    start = end = None
    if normalize and ev_names:
        s_def = next((i for i, n in enumerate(ev_names) if n.endswith("PlotStart")), 0)
        e_def = next((i for i, n in enumerate(ev_names) if n.endswith("PlotEnd")), 0)
        start = g2.selectbox("From event", ev_names, index=s_def, key="c_start")
        end = g3.selectbox("To event", ev_names, index=e_def, key="c_end")

    subjects_here = sorted(trials.loc[(trials["movement"] == movement) & (trials["variant"] == variant), "subject"].unique())
    chosen = g4.multiselect("Subjects", subjects_here, default=subjects_here[:MAX_SERIES], key="c_subj")

    data = load_curves(DB, mtime, movement, variant, signal, component, start, end)
    data = data[data["subject"].isin(chosen)]
    if data.empty:
        st.info("No data for this selection (the events may be missing for these trials).")
    else:
        by_subject = len(chosen) > 1
        if by_subject and len(chosen) > MAX_SERIES:
            st.warning(f"Showing the first {MAX_SERIES} subjects; colors repeat beyond that.")
        colors = color_map(trials["subject"].unique()) if by_subject else color_map(data["trial"].unique())
        fig = go.Figure()
        for (subj, trial), g in data.groupby(["subject", "trial"]):
            key = subj if by_subject else trial
            label = f"{subj}" if by_subject else f"Trial {trial}"
            first = not any(tr.name == label for tr in fig.data)
            fig.add_trace(go.Scatter(
                x=g["x"], y=g["value"], mode="lines", name=label, legendgroup=label, showlegend=first,
                line=dict(width=2, color=colors[key]), opacity=0.85 if not by_subject else 0.5,
                hovertemplate=f"{subj} trial {trial}<br>%{{x:.1f}}: %{{y:.2f}}<extra></extra>"))
        if by_subject:  # subject means on top
            for subj, g in data.groupby("subject"):
                mean = g.groupby("x")["value"].mean()
                fig.add_trace(go.Scatter(x=mean.index, y=mean.values, mode="lines", name=f"{subj} mean",
                                         legendgroup=subj, showlegend=False,
                                         line=dict(width=3, color=colors[subj]),
                                         hovertemplate=f"{subj} mean<br>%{{x:.1f}}: %{{y:.2f}}<extra></extra>"))
        x_title = f"% of {start} to {end}" if start else "Time (s)"
        st.plotly_chart(style(fig, x_title, f"{signal} - {component}"))
        st.caption("Thin lines are individual trials" + ("; thick lines are subject means." if by_subject else "."))

        with st.expander("Table view"):
            wide = data.pivot_table(index="x", columns=["subject", "trial"], values="value")
            wide.columns = [f"{s} t{t}" for s, t in wide.columns]
            st.dataframe(wide.round(3), width="stretch")
            st.download_button("Download CSV", wide.to_csv().encode(), f"{movement}_{variant}_{signal}_{component}.csv")

# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
with tab_metrics:
    allm = load_metrics(DB, mtime)
    f1, f2, f3 = st.columns([2, 1, 4])
    movement_m = f1.selectbox("Movement", sorted(allm["movement"].unique()), key="m_mov")
    variant_m = f2.selectbox("Variant", sorted(allm.loc[allm["movement"] == movement_m, "variant"].unique()), key="m_var")
    m = allm[(allm["movement"] == movement_m) & (allm["variant"] == variant_m)].copy()
    m["metric"] = m["name"] + m["component"].where(~m["component"].isin(["X", ""]), "").radd(" ").str.rstrip()
    metric_names = sorted(m["metric"].unique())
    m_def = next((i for key in ("Jump_height", "FlightTime", "Knee Angles_max") for i, n in enumerate(metric_names)
                  if key.lower() in n.lower()), 0)
    metric = f3.selectbox("Metric", metric_names, index=m_def, key="m_metric")
    sel = m[m["metric"] == metric]

    colors = color_map(trials["subject"].unique())
    fig = go.Figure()
    for subj, g in sel.groupby("subject"):
        fig.add_trace(go.Scatter(
            x=[subj] * len(g), y=g["value"], mode="markers", name=subj,
            marker=dict(size=11, color=colors[subj], line=dict(width=2, color="white")),
            customdata=g[["trial", "session"]],
            hovertemplate="%{x} trial %{customdata[0]}<br>%{customdata[1]}<br>%{y:.3f}<extra></extra>"))
    fig.update_layout(showlegend=sel["subject"].nunique() > 1)
    st.plotly_chart(style(fig, "Subject", metric, height=380))

    st.subheader("Summary")
    st.dataframe(sel.groupby(["subject", "session"])["value"].agg(["count", "mean", "std", "min", "max"])
                    .round(4).reset_index(), hide_index=True, width="stretch")

    with st.expander(f"All metrics for {movement_m} / {variant_m} (one row per trial)"):
        wide = load_metrics_wide(DB, mtime, movement_m, variant_m)
        st.dataframe(wide, hide_index=True, width="stretch")
        st.download_button("Download CSV", wide.to_csv(index=False).encode(), f"{movement_m}_{variant_m}_metrics.csv")
