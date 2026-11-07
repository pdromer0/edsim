"""Keep raw drafts and pending actions independent of page widget keys."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from edsim.runs import read_center_values
from edsim_app import defaults


@dataclass
class CenterDraft:
    """Raw current values and the original on-disk snapshot."""

    source: Path
    values: dict[str, object]
    saved_values: dict[str, object]

    @property
    def dirty(self) -> bool:
        """Compare raw values, including equivalent percentage/fraction edits."""
        return self.values != self.saved_values


def cancel_pending(key: str) -> None:
    """Cancel one action without changing the draft."""
    st.session_state.pop(key, None)


def load_source(source: str | Path) -> None:
    """Replace a draft only after successfully reading its new source."""
    source = Path(source)
    values = read_center_values(source)
    st.session_state.center_draft = CenterDraft(source, values, deepcopy(values))
    st.session_state.variant_name = "" if source == defaults.CENTER_PATH else source.stem
    cancel_pending("pending_source")
    cancel_pending("pending_overwrite")


def accept_source(source: str | Path) -> None:
    """Report source read failures while preserving the existing draft."""
    try:
        load_source(source)
    except (OSError, ValueError) as error:
        cancel_pending("pending_source")
        st.session_state.source_notice = f"No se puede leer el origen: {error}"


def choose_source() -> None:
    """Request confirmation before abandoning unsaved raw values."""
    source = Path(st.session_state.source_widget)
    draft = st.session_state.center_draft
    cancel_pending("pending_overwrite")
    if source == draft.source:
        cancel_pending("pending_source")
    elif draft.dirty:
        st.session_state.pending_source = source
    else:
        accept_source(source)


def update_value(key: str, index: int | None, widget: str) -> None:
    """Copy just one widget into durable state and cancel overwrite consent."""
    draft = st.session_state.center_draft
    if index is None:
        draft.values[key] = st.session_state[widget]
    else:
        draft.values[key][index] = st.session_state[widget]
    cancel_pending("pending_overwrite")


def update_variant_name() -> None:
    """Persist the proposed filename independently of the text input."""
    st.session_state.variant_name = st.session_state.variant_name_widget
    cancel_pending("pending_overwrite")


def source_is_current(draft: CenterDraft) -> bool:
    """Check raw values on every rerun, never replacing an edited draft."""
    try:
        return read_center_values(draft.source) == draft.saved_values
    except (OSError, ValueError):
        return False


def execution_settings() -> dict[str, object]:
    """Initialize durable settings separately from the execution widgets."""
    return st.session_state.setdefault(
        "simulation_settings",
        {
            "clinical_path": str(defaults.CLINICAL_PROFILES_PATH),
            "days": defaults.SIMULATION_DAYS,
            "warmup_days": min(defaults.SIMULATION_WARMUP_DAYS, defaults.SIMULATION_DAYS - 1),
            "seed": "2026",
            "run_id": "",
            "run_id_mode": "automatic",
        },
    )


def update_setting(field: str, widget: str) -> None:
    """Remember inputs and keep warmup inside the newly selected horizon."""
    settings = execution_settings()
    settings[field] = st.session_state[widget]
    if field == "days":
        settings["warmup_days"] = min(settings["warmup_days"], settings["days"] - 1)


def edit_run_id() -> None:
    """An explicit identifier edit enters manual mode until reset by the user."""
    settings = execution_settings()
    settings["run_id"] = st.session_state.run_id_widget
    settings["run_id_mode"] = "manual"


def use_run_suggestion(suggestion: str) -> None:
    """Return to automatic mode and adopt the currently available suggestion."""
    settings = execution_settings()
    settings["run_id"] = suggestion
    settings["run_id_mode"] = "automatic"
