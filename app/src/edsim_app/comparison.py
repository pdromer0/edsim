"""Cache verified comparisons by both ordered, immutable run identities."""

import streamlit as st

from edsim.runs import RunComparison, compare_runs
from edsim_app.results import cached_episode_truth, cached_run_results


@st.cache_resource(max_entries=4, show_spinner="Comprobando y comparando los pacientes…")
def cached_run_comparison(
    root: str,
    run_a: str,
    fingerprint_a: str,
    run_b: str,
    fingerprint_b: str,
) -> RunComparison:
    """Reuse shared read-only results and truth; callers must reopen both headers."""
    return compare_runs(
        cached_run_results(root, run_a, fingerprint_a),
        cached_run_results(root, run_b, fingerprint_b),
        cached_episode_truth(root, run_a, fingerprint_a),
        cached_episode_truth(root, run_b, fingerprint_b),
    )
