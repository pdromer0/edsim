"""Present public run metadata as Spanish tables without importing Streamlit."""

import json
import math
from collections.abc import Mapping, Sequence
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
    level_one_clocks,
    window_clocks,
    window_pretriage,
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
    ("camas.espera", "Espera de cama (min)", False, ("mediana", "p90")),
    ("camas.factor_turno", "Factor de la espera de cama por turno", False, SHIFTS),
    (
        "camas.factor_estacion",
        "Factor de la espera de cama por estación",
        False,
        ("invierno", "primavera", "verano", "otoño"),
    ),
)


def format_change_value(value: int | float | tuple[int | float, ...] | None) -> str:
    """Present differences with decimal commas, separators and a dash for missing values."""
    if value is None:
        return "—"
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
    "Modelo",
    "Huella de perfiles clínicos",
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
                "Clínico" if info.is_clinical else "Provisional",
                info.clinical_profiles_fingerprint[:8] if info.is_clinical else "—",
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
            ("Puerta-médico (A) media", kpis.door_to_doctor_mean, "min", 1, False),
            ("Puerta-médico (A) p90", kpis.door_to_doctor_p90, "min", 1, False),
            ("Episodios desalojados", kpis.displaced_episodes, "episodios", 0, False),
            ("Desalojos totales", kpis.total_displacements, "desalojos", 0, False),
            ("Ingreso", kpis.admission_share, "%", 1, True),
        ],
        columns=["Indicador", "Valor", "Unidad", "Decimales", "Porcentaje"],
    )


def waits_frame(result: RunResults) -> pd.DataFrame:
    """Present level waits and integer Manchester exceedances, retaining numbers."""
    clocks = {
        row.level: row
        for row in window_clocks(result.analysis.table, result.info.warmup_days, result.info.days)
    }
    rows = []
    for metrics, compliance in zip(
        result.analysis.metrics.by_level, result.compliance.by_level, strict=True
    ):
        row = {"Nivel": metrics.level, "n": metrics.n}
        for measure, label in SUMMARY_MEASURES:
            row[f"{label.capitalize()} media (min)"] = metrics.mean[measure]
            row[f"{label.capitalize()} p90 (min)"] = metrics.p90[measure]
        c = clocks[metrics.level].clocks[2]
        row["Desde la clasificación (C) media (min)"] = c.mean
        row["Desde la clasificación (C) p90 (min)"] = c.p90
        row.update(
            {
                "Máximo Manchester (min)": compliance.max_wait,
                "Pacientes que superan el máximo": compliance.exceeded,
                "Superan el máximo": compliance.exceeded_share,
                "Días fuera de objetivo": compliance.share_out,
            }
        )
        if result.outcome is not None:
            # With abandonment (H5-8): those who left after the maximum are in
            # "Pacientes que superan el máximo"; those who left before, out of n.
            row["Se van después del máximo"] = compliance.left_late
            row["Censurados (se van antes)"] = compliance.censored
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
    "initial_box_wait": "Espera inicial de box (min)",
    "results_box_wait": "Espera de box al volver (min)",
    "doctor_wait": "Espera de médico (min)",
    "initial_doctor_wait": "Espera inicial de médico (min)",
    "door_to_doctor": "Puerta-médico (min)",
    "stay": "Estancia (min)",
}


OUTCOME_EPISODE_COLUMNS = {
    "left": "Se va sin ser visto (min)",
    "left_from": "Se va desde",
    "bed_requested": "Pide cama (min)",
    "bed_assigned": "Recibe cama (min)",
    "bed_wait": "Espera de cama (min)",
    "hallway": "Pasillo",
}
LEFT_FROM_LABELS = {
    "triaje": "Esperando el triaje",
    "box": "Esperando box",
    "medico": "Esperando médico en el box",
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
    if result.outcome is not None:
        # The outcome of milestone 5 (task 5.4): abandonment, bed and hallway.
        for field, label in OUTCOME_EPISODE_COLUMNS.items():
            frame[label] = [getattr(record, field) for record in table]
        frame["Se va desde"] = frame["Se va desde"].map(LEFT_FROM_LABELS)
        frame["Pasillo"] = frame["Pasillo"].map({True: "Sí", False: "No"})
    frame["Llegada (UTC+1)"] = wall_times(result, [record.arrival for record in table])
    frame["Nivel"] = frame["Nivel"].astype("Int64")
    if result.observed is not None:
        profile_frame = pd.DataFrame(
            [observed_profile_row(result.observed[e.episode_id], result.profiles) for e in table],
            columns=["Edad", "Sexo", "Medio", "Motivo", "Pruebas"],
        )
        profile_frame["Edad"] = profile_frame["Edad"].astype("Int64")
        frame = pd.concat([frame, profile_frame], axis=1)
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
    "waiting_bed": "Esperando cama",
}


def episode_state_label(state: str, *, results_room: bool = False, hallway: bool = False) -> str:
    """Present the physical location while preserving the core's state names.

    The state says what the patient does; the marks, where it is (H5-11): the
    results room or, for an admitted patient displaced from its box, the hallway.
    """
    if results_room:
        return "Sala de resultados · " + (
            "espera de box" if state == "waiting_box" else "espera de pruebas"
        )
    if hallway:
        return "Pasillo · " + EPISODE_STATE_LABELS[state].lower()
    return EPISODE_STATE_LABELS[state]


def plain_payload(value: object) -> object:
    """Convert immutable nested log containers to JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {key: plain_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain_payload(item) for item in value]
    return value


def episode_timeline_frames(
    episode: EpisodeSegments, result: RunResults
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convert core intervals and markers to naive UTC+1 wall-clock tables."""
    columns = ["Inicio", "Fin", "Estado", "Box", "Duración (min)", "Carril"]
    rows = [
        {
            "Inicio": segment.start,
            "Fin": segment.end,
            "Estado": episode_state_label(
                segment.state, results_room=segment.results_room, hallway=segment.hallway
            ),
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
                name: json.dumps(plain_payload(event.payload), ensure_ascii=False)
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
        "patience": "Paciencia",
        "bed_wait": "Espera de cama",
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


CLOCK_LABELS = {
    "door_to_doctor": "Puerta-médico (A)",
    "triage_start_to_doctor": "Desde el inicio del triaje (B)",
    "classified_to_doctor": "Desde la clasificación (C)",
}


def clocks_frame(result: RunResults) -> pd.DataFrame:
    """Present the core's three clocks for assigned levels two to five."""
    return pd.DataFrame(
        [
            {
                "Nivel asignado": level.level,
                "n": level.n,
                "Reloj": CLOCK_LABELS[clock.measure],
                "Media (min)": clock.mean,
                "Mediana (min)": clock.median,
                "p90 (min)": clock.p90,
            }
            for level in window_clocks(
                result.analysis.table, result.info.warmup_days, result.info.days
            )
            if level.level != 1
            for clock in level.clocks
        ]
    )


def level_one_clocks_frame(result: RunResults) -> pd.DataFrame:
    """Keep immediate attention separate from percentages of compliance."""
    level = level_one_clocks(result.analysis.table, result.info.warmup_days, result.info.days)
    return pd.DataFrame(
        [
            {
                "Reloj": label,
                "n": level.n,
                "Mediana (min)": level.median[name],
                "p90 (min)": level.p90[name],
            }
            for name, label in CLOCK_LABELS.items()
        ]
    )


def pretriage_frame(result: RunResults) -> pd.DataFrame:
    """Present pooled and daily pretriage supplied by the core, excluding level one."""
    value = window_pretriage(result.analysis.table, result.info.warmup_days, result.info.days)
    return pd.DataFrame(
        [
            {
                "Grupo": "Niveles 2–5" if group.group is None else f"Nivel {group.group}",
                "n": group.n,
                "10 min o menos": group.within_share,
                "Más de 5 min": group.over_share,
                "Días fuera": group.days_out,
                "Días con pacientes": group.days_with_patients,
            }
            for group in value.by_group
        ]
    )


def observed_distribution_frames(result: RunResults) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group observable data for arrivals in the window, including unfinished episodes."""
    records = [
        e
        for e in result.analysis.table
        if result.analysis.metrics.start <= e.arrival < result.analysis.metrics.end
    ]
    labels = []
    for e in records:
        reason = result.observed[e.episode_id].reason
        labels.append(result.profiles.reason(reason).name if reason else "Sin observar")

    def distribution(values, column):
        counts = pd.Series(values, dtype=object).value_counts(dropna=False, sort=False)
        return pd.DataFrame(
            [
                {column: label, "Pacientes": int(n), "Proporción": n / len(records)}
                for label, n in counts.items()
            ],
            columns=[column, "Pacientes", "Proporción"],
        )

    return distribution(labels, "Motivo"), distribution(
        [str(e.level) if e.level is not None else "Sin observar" for e in records], "Nivel asignado"
    )


def observed_profile_row(observed, profiles) -> dict:
    """Translate an observable profile without consulting hidden truth."""
    return {
        "Edad": observed.age,
        "Sexo": observed.sex.capitalize() if observed.sex else None,
        "Medio": {"ambulancia": "Ambulancia", "propios_medios": "Medios propios"}.get(
            observed.arrival_mode
        ),
        "Motivo": profiles.reason(observed.reason).name if observed.reason else None,
        "Pruebas": ", ".join(observed.tests) or "—",
    }


def clinical_truth_frames(value) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Present explicitly requested hidden truth and the individual test responses."""
    quality = {"correcto": "Correcto", "infratriaje": "Infratriaje", "sobretriaje": "Sobretriaje"}
    details = pd.DataFrame(
        [
            {"Dato clínico": label, "Verdad": str(item) if item is not None else "—"}
            for label, item in (
                ("Gravedad latente G", value.severity),
                ("Nivel asignado", value.assigned_level),
                ("Nivel real", value.true_level),
                ("Calidad del triaje", quality.get(value.quality, value.quality)),
                ("Salto", value.jump),
                ("Respuesta esperada de la ronda (min)", value.round_expected),
                ("Respuesta observada de la ronda (min)", value.round_observed),
            )
        ]
    )
    tests = pd.DataFrame(
        [
            {
                "Prueba": test.test,
                "Pedida": "Sí" if test.ordered else "No",
                "Resultado": test.result or "—",
                "Respuesta base (min)": test.base_turnaround,
                "Respuesta en la franja del pedido (min)": test.turnaround,
            }
            for test in value.tests
        ]
    )
    return details, tests
