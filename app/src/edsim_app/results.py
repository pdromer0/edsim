"""Share read-only analyses by catalog, run identifier and exact metadata hash."""

import streamlit as st

from edsim.runs import RunResults, RunStore, read_run_results


@st.cache_resource(max_entries=4, show_spinner="Leyendo y analizando la ejecución…")
def cached_run_results(catalog_root: str, run_id: str, fingerprint: str) -> RunResults:
    """Invalidate recreated runs; callers open the header before every lookup.

    Consumers must treat all nested arrays and mappings as read-only, since
    this cache returns the same object to every caller.
    """
    return read_run_results(RunStore(catalog_root), run_id)
