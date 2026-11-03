"""Cache offered work by raw center values and exact profile fingerprint."""

from pathlib import Path

import streamlit as st

from edsim.runs import (
    OfferedWork,
    RunConfigurationError,
    center_from_values,
    config_fingerprint,
    load_profile,
    offered_work,
)


@st.cache_data(max_entries=3, show_spinner=False)
def cached_offered_work(
    raw_items: tuple[tuple[str, object], ...], profile_path: str, profile_fingerprint: str
) -> OfferedWork:
    """Fingerprint is an explicit cache argument even when the path is unchanged."""
    try:
        profile = load_profile(profile_path)
    except (OSError, ValueError) as error:
        raise RunConfigurationError(f"{profile_path}: {error}") from error
    return offered_work(center_from_values(dict(raw_items)), profile, days=7)


def preview_work(values: dict[str, object], profile_path: str | Path) -> OfferedWork:
    """Serialize raw numeric fields and fingerprint the profile on every rerun."""
    raw_items = tuple(
        (key, tuple(value) if isinstance(value, list | tuple) else value)
        for key, value in sorted(values.items())
    )
    try:
        fingerprint = config_fingerprint(profile_path)
    except OSError as error:
        raise RunConfigurationError(f"{profile_path}: {error}") from error
    return cached_offered_work(raw_items, str(profile_path), fingerprint)
