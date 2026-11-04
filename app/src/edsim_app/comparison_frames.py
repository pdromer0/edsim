"""Spanish presentation of supplied comparison results, without analytical logic."""

import pandas as pd

from edsim.runs import (
    SUMMARY_MEASURES,
    DifferenceSummary,
    PairingInfo,
    RunComparison,
    RunSummaryComparison,
)
from edsim_app.frames import FIELDS, format_change_value, format_created_at, format_number

METADATA_LABELS = {
    "format_version": "Versión del formato",
    "run_id": "Ejecución",
    "created_at": "Fecha de creación (UTC+1)",
    "origin": "Origen",
    "edsim_version": "Versión de EDsim",
    "variant": "Variante",
    "center_fingerprint": "Huella del centro",
    "center_path": "Ruta del centro",
    "profile_path": "Ruta del perfil",
    "invariant_violations": "Violaciones de invariantes",
    "window_arrivals": "Llegadas en la ventana",
    "simulation_seconds": "Duración de la simulación (s)",
    "seed": "Semilla",
    "profile_fingerprint": "Huella del perfil",
    "days": "Días",
    "warmup_days": "Calentamiento (días)",
}
KPI_PRESENTATION = {
    "arrivals_per_day": ("Llegadas por día", "pacientes/día", 1),
    "census_mean": ("Censo medio", "pacientes", 2),
    "stay_mean": ("Estancia media", "min", 1),
    "stay_p90": ("Estancia p90", "min", 1),
    "door_to_doctor_mean": ("Puerta-médico media", "min", 1),
    "door_to_doctor_p90": ("Puerta-médico p90", "min", 1),
    "displaced_episodes": ("Episodios desalojados", "episodios", 0),
    "total_displacements": ("Desalojos totales", "desalojos", 0),
    "admission_share": ("Ingreso", "%", 1),
}
DRAW_LABELS = {
    "level": "Nivel",
    "triage_time": "Triaje",
    "assessment_time": "Valoración",
    "reassessment_time": "Reevaluación",
    "needs_tests": "Pruebas",
    "test_turnaround": "Respuesta de pruebas",
    "admitted": "Destino",
}


def signed_number(value: float | None, digits: int = 1, *, percentage: bool = False) -> str:
    """Format a supplied signed delta without rounding before classification."""
    text = format_number(value, digits, percentage=percentage)
    return f"+{text}" if value is not None and value > 0 else text


def comparison_kpis_frame(summary: RunSummaryComparison) -> pd.DataFrame:
    """Display the nine supplied differences, with admission delta in percentage points."""
    rows = []
    for kpi in summary.kpis:
        label, unit, digits = KPI_PRESENTATION[kpi.field]
        share = kpi.field == "admission_share"
        delta = signed_number(kpi.difference, digits, percentage=share)
        if share:
            delta = delta.replace(" %", " pp")
        rows.append(
            {
                "Indicador": label,
                "Unidad": unit,
                "A": format_number(kpi.a, digits, percentage=share),
                "B": format_number(kpi.b, digits, percentage=share),
                "B − A": delta,
                "Cambio relativo": signed_number(kpi.relative_change, percentage=True),
            }
        )
    return pd.DataFrame(rows)


def comparison_levels_frame(summary: RunSummaryComparison) -> pd.DataFrame:
    """Place each level's n, five means/p90 and Manchester fraction side by side."""
    rows = []
    labels = dict(SUMMARY_MEASURES)
    for level in summary.levels:
        row = {"Nivel": level.level, "n A": level.a.n, "n B": level.b.n}
        for side, value in (("A", level.a), ("B", level.b)):
            for wait in value.waits:
                for statistic in ("mean", "p90"):
                    title = "media" if statistic == "mean" else "p90"
                    row[f"{labels[wait.measure].capitalize()} {title} {side} (min)"] = (
                        format_number(getattr(wait, statistic))
                    )
            row[f"Máximo Manchester {side} (min)"] = format_number(value.max_wait)
            row[f"Superan el máximo {side}"] = format_number(value.exceeded_share, percentage=True)
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_configuration_frames(
    summary: RunSummaryComparison,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Preserve metadata values and normalized TOML differences."""
    metadata = pd.DataFrame(
        [
            {
                "Campo": METADATA_LABELS.get(d.field, d.field),
                "A": format_created_at(d.a) if d.field == "created_at" else str(d.a),
                "B": format_created_at(d.b) if d.field == "created_at" else str(d.b),
            }
            for d in summary.metadata_differences
        ],
        columns=["Campo", "A", "B"],
    )
    field_labels = {key: label for key, label, _, _ in FIELDS}
    center = pd.DataFrame(
        [
            {
                "Parámetro": field_labels[d.key],
                "Clave del centro": d.key,
                "A": format_change_value(d.before),
                "B": format_change_value(d.after),
            }
            for d in summary.center_differences
        ],
        columns=["Parámetro", "Clave del centro", "A", "B"],
    )
    return metadata, center


def draw_differences_frame(pairing: PairingInfo) -> pd.DataFrame:
    """Include zero changes, and draws that patients did not use."""
    return pd.DataFrame(
        [
            {"Sorteo": DRAW_LABELS[d.field], "Pacientes distintos": d.changed, "Total": d.total}
            for d in pairing.draw_differences
        ]
    )


def difference_histogram_frame(summary: DifferenceSummary) -> pd.DataFrame:
    """Expose the core's histogram; no binning or equal-patient counting in the app."""
    return pd.DataFrame(
        [
            {
                "Desde (min)": bin.left,
                "Hasta (min)": bin.right,
                "Pacientes": bin.n,
                "Efecto": "Mejoran" if bin.right <= 0 else "Empeoran",
            }
            for bin in summary.histogram
        ],
        columns=["Desde (min)", "Hasta (min)", "Pacientes", "Efecto"],
    )


def affected_episodes_frame(comparison: RunComparison) -> pd.DataFrame:
    """Present the core's ordered top ten, preserving signed changes and both levels."""
    return pd.DataFrame(
        [
            {
                "Episodio": e.episode_id,
                "Nivel A": e.level_a,
                "Nivel B": e.level_b,
                "Estancia A (min)": format_number(e.stay_a),
                "Estancia B (min)": format_number(e.stay_b),
                "B − A (min)": signed_number(e.stay_difference),
            }
            for e in comparison.most_affected
        ]
    )
