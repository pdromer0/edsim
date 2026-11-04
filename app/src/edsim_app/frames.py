"""Present public run metadata as Spanish tables without importing Streamlit."""

import json
import math
from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime

import pandas as pd
from pandas.io.formats.style import Styler

from edsim.runs import (
    SUMMARY_MEASURES,
    TIMEZONE,
    EpisodeRecord,
    EpisodeSegments,
    Event,
    OfferedWork,
    RunInfo,
    RunResults,
    TruthComparison,
    WindowKPIs,
    curve_blocks,
    curve_steps,
    episode_observed_time,
)

SHIFTS = ("mañana", "tarde", "noche")
LEVELS = tuple(f"nivel {i}" for i in range(1, 6))
FIELDS = (
    ("turnos.inicio", "Inicio de los turnos (horas)", True, SHIFTS),
    ("recursos.enfermeria_triaje", "Enfermería de triaje", True, SHIFTS),
    ("recursos.medicos", "Médicos", True, SHIFTS),
    ("recursos.boxes", "Boxes", True, ()),
    ("triaje.reparto_niveles", "Reparto de triaje (pesos)", False, LEVELS),
    ("duraciones.triaje", "Duración de triaje (min)", False, ("mediana", "p90")),
    ("duraciones.valoracion", "Duración de valoración (min)", False, ("mediana", "p90")),
    ("duraciones.reevaluacion", "Duración de reevaluación (min)", False, ("mediana", "p90")),
    ("duraciones.respuesta_pruebas", "Respuesta de pruebas (min)", False, ("mediana", "p90")),
    ("pruebas.probabilidad", "Probabilidad de pruebas", False, LEVELS),
    ("destino.probabilidad_ingreso", "Probabilidad de ingreso", False, LEVELS),
)


def format_change_value(value: int | float | tuple[int | float, ...]) -> str:
    """Present normalized differences with decimal commas and unambiguous separators."""
    if isinstance(value, tuple):
        return "[" + "; ".join(format_change_value(item) for item in value) + "]"
    return (str(value) if isinstance(value, int) else f"{value:.15g}").replace(".", ",")


def format_created_at(value: str) -> str:
    """Present an ISO creation timestamp as fixed UTC+1, to whole seconds."""
    return datetime.fromisoformat(value).astimezone(TIMEZONE).strftime("%d/%m/%Y %H:%M:%S")


COLUMNS = (
    "Ejecución",
    "Variante del centro",
    "Fecha de creación (UTC+1)",
    "Días",
    "Calentamiento (días)",
    "Semilla",
    "Huella del centro",
    "Llegadas por día",
    "Invariantes",
    "Origen",
)


def runs_frame(runs: Sequence[RunInfo]) -> pd.DataFrame:
    """Convert catalog metadata without changing its order or numeric values."""
    return pd.DataFrame(
        [
            (
                info.run_id,
                info.variant,
                format_created_at(info.created_at),
                info.days,
                info.warmup_days,
                info.seed,
                info.center_fingerprint[:8],
                info.arrivals_per_day,
                "correctas"
                if info.invariant_violations == 0
                else f"{info.invariant_violations} violaciones",
                "app" if info.origin == "app" else "CLI",
            )
            for info in runs
        ],
        columns=COLUMNS,
    )


def style_runs(frame: pd.DataFrame) -> Styler:
    """Use a decimal comma while keeping numeric columns sortable as numbers."""
    return frame.style.format({"Llegadas por día": "{:.1f}"}, decimal=",")


POOL_LABELS = {"medicos": "Médicos", "boxes": "Boxes", "enfermeria_triaje": "Enfermería de triaje"}
SHIFT_LABELS = ("Mañana", "Tarde", "Noche")


def offered_frame(work: OfferedWork, pool: str) -> pd.DataFrame:
    """Average 15-minute blocks with UTC+1 wall times immune to browser timezone shifts."""
    per_minute = (work.load[pool][:-1] + work.load[pool][1:]) / 2
    return pd.DataFrame(
        {
            "Fecha y hora": (
                pd.Timestamp(work.start_date, tz=TIMEZONE)
                + pd.to_timedelta(work.minutes[:-1:15], unit="min")
            ).tz_localize(None),
            "Carga ofrecida": per_minute.reshape(-1, 15).mean(axis=1),
            "Capacidad": work.capacity[pool][:-1].reshape(-1, 15).mean(axis=1),
        }
    )


def utilization_frame(work: OfferedWork) -> pd.DataFrame:
    """Present core utilization values without recomputing them from the chart."""
    return pd.DataFrame(
        [
            {
                "Recurso": label,
                "Turno": shift,
                "Utilización": value,
                "Estado": "Por encima de 1"
                if value > 1
                else "Por encima de 0,85"
                if value > 0.85
                else "Hasta 0,85",
            }
            for pool, label in POOL_LABELS.items()
            for shift, value in zip(SHIFT_LABELS, work.utilization[pool], strict=True)
        ]
    )


def style_utilization(frame: pd.DataFrame) -> Styler:
    """Highlight thresholds with text and color, preserving numeric values."""
    colors = {"Por encima de 1": "#ffdddd", "Por encima de 0,85": "#fff0cc"}
    return frame.style.format({"Utilización": "{:.1%}"}, decimal=",").map(
        lambda value: f"background-color: {colors[value]}" if value in colors else "",
        subset=["Estado"],
    )


def format_number(value: float | None, digits: int = 1, *, percentage: bool = False) -> str:
    """Format missing statistics and decimal commas without changing numeric data."""
    if value is None or math.isnan(value):
        return "—"
    suffix = " %" if percentage else ""
    return f"{value * 100 if percentage else value:.{digits}f}".replace(".", ",") + suffix


def kpis_frame(kpis: WindowKPIs) -> pd.DataFrame:
    """Keep numeric KPIs separate from their labels, units and display precision."""
    return pd.DataFrame(
        [
            ("Llegadas por día", kpis.arrivals_per_day, "pacientes/día", 1, False),
            ("Censo medio", kpis.census_mean, "pacientes", 2, False),
            ("Estancia media", kpis.stay_mean, "min", 1, False),
            ("Estancia p90", kpis.stay_p90, "min", 1, False),
            ("Puerta-médico media", kpis.door_to_doctor_mean, "min", 1, False),
            ("Puerta-médico p90", kpis.door_to_doctor_p90, "min", 1, False),
            ("Episodios desalojados", kpis.displaced_episodes, "episodios", 0, False),
            ("Desalojos totales", kpis.total_displacements, "desalojos", 0, False),
            ("Ingreso", kpis.admission_share, "%", 1, True),
        ],
        columns=["Indicador", "Valor", "Unidad", "Decimales", "Porcentaje"],
    )


def waits_frame(result: RunResults) -> pd.DataFrame:
    """Present level waits and integer Manchester exceedances, retaining numbers."""
    rows = []
    for metrics, compliance in zip(
        result.analysis.metrics.by_level, result.compliance.by_level, strict=True
    ):
        row = {"Nivel": metrics.level, "n": metrics.n}
        for measure, label in SUMMARY_MEASURES:
            row[f"{label.capitalize()} media (min)"] = metrics.mean[measure]
            row[f"{label.capitalize()} p90 (min)"] = metrics.p90[measure]
        row.update(
            {
                "Máximo Manchester (min)": compliance.max_wait,
                "Pacientes que superan el máximo": compliance.exceeded,
                "Superan el máximo": compliance.exceeded_share,
                "Días fuera de objetivo": compliance.share_out,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def style_waits(frame: pd.DataFrame) -> Styler:
    """Use Spanish decimal formatting and em dashes for unobserved statistics."""
    formats = {column: "{:.1f}" for column in frame if column.endswith("(min)")}
    formats.update({"Superan el máximo": "{:.1%}", "Días fuera de objetivo": "{:.1%}"})
    return frame.style.format(formats, decimal=",", na_rep="—")


CURVE_LABELS = {
    "census": "Censo",
    "waiting_triage": "Cola de triaje",
    "waiting_box": "Cola de box",
    "nurses_busy": "Enfermería de triaje ocupada",
    "doctors_busy": "Médicos ocupados",
    "boxes_busy": "Boxes ocupados",
}


def wall_times(result: RunResults, minutes: object) -> pd.DatetimeIndex:
    """Convert simulation minutes to UTC+1 clock time without a timezone offset."""
    return (
        pd.Timestamp(result.start_date, tz=TIMEZONE) + pd.to_timedelta(minutes, unit="min")
    ).tz_localize(None)


EPISODE_COLUMNS = {
    "episode_id": "Episodio",
    "arrival": "Llegada (UTC+1)",
    "triage_start": "Inicio de triaje (min)",
    "triage_end": "Fin de triaje (min)",
    "level": "Nivel",
    "first_box": "Primer box (min)",
    "first_assessment": "Primera valoración (min)",
    "decision": "Decisión (min)",
    "departure": "Salida (min)",
    "destination": "Destino",
    "displacements": "Desalojos",
    "triage_wait": "Espera de triaje (min)",
    "box_wait": "Espera de box (min)",
    "doctor_wait": "Espera de médico (min)",
    "initial_doctor_wait": "Espera inicial de médico (min)",
    "door_to_doctor": "Puerta-médico (min)",
    "stay": "Estancia (min)",
}


def episodes_frame(table: Sequence[EpisodeRecord], result: RunResults) -> pd.DataFrame:
    """Present every record field, final stay and observed lower bound unchanged."""
    frame = pd.DataFrame(
        [
            {label: getattr(record, field) for field, label in EPISODE_COLUMNS.items()}
            | {
                "Tiempo observado (min)": episode_observed_time(
                    record, result.analysis.curves.horizon
                )
            }
            for record in table
        ],
        columns=[*EPISODE_COLUMNS.values(), "Tiempo observado (min)"],
    )
    frame["Llegada (UTC+1)"] = wall_times(result, [record.arrival for record in table])
    frame["Nivel"] = frame["Nivel"].astype("Int64")
    return frame


def style_episodes(frame: pd.DataFrame) -> Styler:
    """Keep missing outcomes explicit and minutes numeric with Spanish display."""
    formats = {column: "{:.1f}" for column in frame if column.endswith("(min)")}
    formats.update({"Llegada (UTC+1)": lambda value: value.strftime("%d/%m/%Y %H:%M:%S")})
    return frame.style.format(formats, decimal=",", na_rep="—")


EPISODE_STATE_LABELS = {
    "waiting_triage": "Espera de triaje",
    "triage": "Triaje",
    "waiting_box": "Espera de box",
    "waiting_doctor": "En box esperando médico",
    "assessment": "Valoración",
    "waiting_tests": "En box esperando pruebas",
    "reassessment": "Reevaluación",
}


def episode_timeline_frames(
    episode: EpisodeSegments, result: RunResults
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convert core intervals and markers to naive UTC+1 wall-clock tables."""
    columns = ["Inicio", "Fin", "Estado", "Box", "Duración (min)", "Carril"]
    rows = [
        {
            "Inicio": segment.start,
            "Fin": segment.end,
            "Estado": EPISODE_STATE_LABELS[segment.state],
            "Box": segment.box,
            "Duración (min)": segment.end - segment.start,
            "Carril": "Recorrido",
        }
        for segment in episode.segments
    ]
    segments = pd.DataFrame(rows, columns=columns)
    band = episode.tests
    tests = pd.DataFrame(
        []
        if band is None
        else [
            {
                "Inicio": band.start,
                "Fin": band.end,
                "Estado": "Pruebas en curso",
                "Box": None,
                "Duración (min)": band.end - band.start,
                "Carril": "Pruebas",
            }
        ],
        columns=columns,
    )
    for frame in (segments, tests):
        frame["Inicio"] = wall_times(result, frame["Inicio"].tolist())
        frame["Fin"] = wall_times(result, frame["Fin"].tolist())
    displacements = pd.DataFrame(
        [
            {
                "Fecha y hora": point.time,
                "Box": point.box,
                "Desalojado por": point.displaced_by,
                "Carril": "Recorrido",
            }
            for point in episode.displacements
        ],
        columns=["Fecha y hora", "Box", "Desalojado por", "Carril"],
    )
    displacements["Fecha y hora"] = wall_times(result, displacements["Fecha y hora"].tolist())
    return segments, tests, displacements


def episode_events_frame(events: Sequence[Event]) -> pd.DataFrame:
    """Keep log field names, timestamps, payload keys and emission order intact."""
    names = [field.name for field in fields(Event)]
    return pd.DataFrame(
        [
            {
                name: json.dumps(dict(event.payload), ensure_ascii=False)
                if name == "payload"
                else getattr(event, name)
                for name in names
            }
            for event in events
        ],
        columns=names,
    )


def episode_truth_frame(comparisons: Sequence[TruthComparison]) -> pd.DataFrame:
    """Present supplied comparison statuses without recalculating clinical values."""
    labels = {
        "level": "Nivel",
        "triage_time": "Triaje",
        "assessment_time": "Valoración",
        "reassessment_time": "Reevaluación",
        "test_turnaround": "Respuesta de pruebas",
        "destination": "Destino",
    }
    statuses = {
        "match": "Coincide",
        "mismatch": "Discrepancia",
        "partial": "Parcial",
        "pending": "Pendiente",
        "unused": "No usada",
    }
    rows = []
    for row in comparisons:

        def display(value: object, field: str = row.field) -> str:
            if value is None:
                return "—"
            if field == "destination":
                return str(value).capitalize()
            return format_number(value, 0 if field == "level" else 1) + (
                "" if field == "level" else " min"
            )

        observed = display(row.observed)
        if row.status == "partial":
            observed = f"{format_number(row.observed)} de {display(row.drawn)}"
        rows.append(
            {
                "Dato": labels[row.field],
                "Sorteado": display(row.drawn),
                "Observado": observed,
                "Estado": statuses[row.status],
            }
        )
    return pd.DataFrame(rows, columns=["Dato", "Sorteado", "Observado", "Estado"])


def curve_frame(result: RunResults, name: str, week: int) -> pd.DataFrame:
    """Present one week's supplied exact blocks and capacity steps without mutation."""
    start = week * 7 * 1440
    end = min(start + 7 * 1440, result.analysis.curves.horizon)
    blocks = curve_blocks(result.analysis.curves, name, start, end)
    rows = []
    for label, values in (("Media", blocks.mean), ("Máximo", blocks.maximum)):
        # Repeat the last value only to draw the final block all the way to its end.
        rows.extend(
            {"Fecha y hora": time, "Serie": label, "Valor": float(value)}
            for time, value in zip(
                wall_times(result, blocks.edges), [*values, values[-1]], strict=True
            )
        )
    staff_name = {"nurses_busy": "nurses_staff", "doctors_busy": "doctors_staff"}.get(name)
    if staff_name is not None:
        steps = curve_steps(result.analysis.curves, staff_name, start, end)
        rows.extend(
            {"Fecha y hora": time, "Serie": "Plantilla vigente", "Valor": int(value)}
            for time, value in zip(
                wall_times(result, steps.edges), [*steps.values, steps.values[-1]], strict=True
            )
        )
    elif name == "boxes_busy":
        rows.extend(
            {"Fecha y hora": time, "Serie": "Boxes", "Valor": result.center.boxes}
            for time in wall_times(result, [start, end])
        )
    return pd.DataFrame(rows)


def occupancy_frame(result: RunResults) -> pd.DataFrame:
    """Keep all nine core ratios, including values above one, with Spanish labels."""
    shifts = dict(zip(("morning", "afternoon", "night"), SHIFT_LABELS, strict=True))
    return pd.DataFrame(
        [
            {
                "Recurso": POOL_LABELS[value.pool],
                "Turno": shifts[value.shift],
                "Ocupación": value.ratio,
                "Etiqueta": format_number(value.ratio, percentage=True),
            }
            for value in result.analysis.metrics.occupancy
        ]
    )


def hourly_census_frame(result: RunResults) -> pd.DataFrame:
    """Expose the core's 24 hour-of-day means as a fresh presentation table."""
    return pd.DataFrame({"Hora del día": range(24), "Censo medio": result.hourly_census.copy()})


def little_frame(result: RunResults) -> pd.DataFrame:
    """Present operational laws with their original units and the CLI's product."""
    labels = {"system": "Sistema", "triage_queue": "Cola de triaje", "box_queue": "Cola de box"}
    return pd.DataFrame(
        [
            {
                "Ámbito": labels[law.name],
                "L": law.l,
                "λ (pacientes/min)": law.lam,
                "W (min)": law.w,
                "λ·W": law.lam * law.w,
                "Error relativo": law.relative_error,
            }
            for law in result.analysis.little
        ]
    )


def style_little(frame: pd.DataFrame) -> Styler:
    """Preserve numbers while matching CLI precision for L, product and error."""
    return frame.style.format(
        {
            "L": "{:.4f}",
            "λ (pacientes/min)": "{:.6f}",
            "W (min)": "{:.4f}",
            "λ·W": "{:.4f}",
            "Error relativo": "{:.2%}",
        },
        decimal=",",
    )
