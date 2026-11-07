"""Share read-only analyses by catalog, run identifier and exact metadata hash."""

from collections.abc import Mapping
from dataclasses import replace

import streamlit as st

from edsim.runs import (
    EpisodeEventIndex,
    EpisodeTruth,
    Event,
    RunResults,
    RunStore,
    build_episode_event_index,
    read_episode_events,
    read_run_episode_truth,
    read_run_results,
    window_compliance,
)


@st.cache_resource(max_entries=4, show_spinner="Leyendo y analizando la ejecución…")
def cached_run_results(catalog_root: str, run_id: str, fingerprint: str) -> RunResults:
    """Invalidate recreated runs; callers open the header before every lookup.

    Consumers must treat all nested arrays and mappings as read-only, since
    this cache returns the same object to every caller.
    """
    result = read_run_results(RunStore(catalog_root), run_id)
    return replace(
        result,
        compliance=window_compliance(
            result.analysis.table,
            result.info.warmup_days,
            result.info.days,
            measure="classified_to_doctor",
        ),
    )


@st.cache_resource(max_entries=4, show_spinner="Indexando los eventos de la ejecución…")
def cached_episode_event_index(
    catalog_root: str, run_id: str, fingerprint: str
) -> EpisodeEventIndex:
    """Build an independent read-only index only when Episodios is opened."""
    return build_episode_event_index(RunStore(catalog_root), run_id)


@st.cache_resource(max_entries=128, show_spinner=False)
def cached_episode_events(
    catalog_root: str, run_id: str, fingerprint: str, episode_id: str
) -> tuple[Event, ...]:
    """Retain small immutable cards without keeping the complete log in memory."""
    index = cached_episode_event_index(catalog_root, run_id, fingerprint)
    return read_episode_events(RunStore(catalog_root), run_id, episode_id, index)


@st.cache_resource(max_entries=4, show_spinner="Leyendo la verdad de los episodios…")
def cached_episode_truth(
    catalog_root: str, run_id: str, fingerprint: str
) -> Mapping[str, EpisodeTruth]:
    """Read exact draws once, lazily on the truth toggle, by immutable run identity."""
    return read_run_episode_truth(RunStore(catalog_root), run_id)
