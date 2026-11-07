"""Cache the demand sample independently of the center's staffing."""

from pathlib import Path

import streamlit as st

from edsim.runs import (
    ArrivalProfile,
    CenterConfig,
    ClinicalProfiles,
    OfferedLoad,
    OfferedWork,
    RunConfigurationError,
    center_from_values,
    config_fingerprint,
    load_profile,
    load_profiles,
    offered_load,
    offered_work_from_load,
)


def load_preview_inputs(arrival_path: str | Path, clinical_path: str | Path):
    """Wrap only configuration reads; analytical errors remain visible."""
    try:
        arrivals = load_profile(arrival_path)
        arrival_fingerprint = config_fingerprint(arrival_path)
    except (OSError, ValueError) as error:
        raise RunConfigurationError(
            f"No se puede cargar el perfil de llegadas: {arrival_path}: {error}"
        ) from error
    try:
        profiles = load_profiles(clinical_path)
        fingerprint = config_fingerprint(clinical_path)
    except (OSError, ValueError) as error:
        raise RunConfigurationError(
            f"No se pueden cargar los perfiles clínicos: {clinical_path}: {error}"
        ) from error
    return arrivals, arrival_fingerprint, profiles, fingerprint


@st.cache_resource(max_entries=3, show_spinner=False)
def cached_offered_load(
    arrival_fingerprint: str,
    clinical_fingerprint: str,
    clinical_values: tuple,
    days: int,
    sample_size: int,
    sample_seed: int,
    _center: CenterConfig,
    _arrivals: ArrivalProfile,
    _profiles: ClinicalProfiles,
) -> OfferedLoad:
    """Hash only inputs affecting demand; excluded objects supply that exact input."""
    with st.spinner("Calculando la carga prevista con los perfiles…"):
        return offered_load(
            _center,
            _arrivals,
            days,
            profiles=_profiles,
            sample_size=sample_size,
            sample_seed=sample_seed,
        )


def preview_work(
    values: dict[str, object],
    profile_path: str | Path,
    clinical_path: str | Path,
) -> OfferedWork:
    """Fingerprint files on every rerun and apply staffing without resampling."""
    arrivals, arrival_fp, profiles, clinical_fp = load_preview_inputs(profile_path, clinical_path)
    center = center_from_values(values)
    clinical_values = (center.results_wait_outside,)
    load = cached_offered_load(
        arrival_fp,
        clinical_fp,
        clinical_values,
        7,
        50_000,
        73_001,
        center,
        arrivals,
        profiles,
    )
    return offered_work_from_load(center, load)
