"""Tables and CSV files of ``edsim calibracion evaluar`` and ``sensibilidad``.

The CSV files are tidy (one row per target, per replication and target, per
level or per staffing and target) and every row carries the parameters of
the run: the four files with their fingerprints, the window, the
replications, the days, the warm-up and the seed, so that a row of the
calibration log can be traced back to the command that produced it.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from edsim.calibration.evaluate import (
    CENSORED_WARNING,
    COMPLIANCE_LEVELS,
    COMPLIANCE_SHARE_OUT,
    DRAIN_DAYS,
    KNOB_TARGETS,
    LevelShare,
    ReplicaValues,
    SensitivityRow,
    TargetResult,
    level_breakdown,
    passes_fit,
    pooled_value,
)
from edsim.calibration.staffing import DOCTORS
from edsim.calibration.targets import FIT, Target

PARAMETER_COLUMNS = (
    "centro",
    "huella_centro",
    "llegadas",
    "huella_llegadas",
    "perfiles",
    "huella_perfiles",
    "objetivos",
    "huella_objetivos",
    "ventana",
    "replicas",
    "dias",
    "calentamiento",
    "semilla",
)
"""Columns of the parameters of the run, at the end of every CSV row."""

EVALUATION_COLUMNS = (
    "objetivo",
    "medida",
    "niveles",
    "estadistico",
    "umbral",
    "uso",
    "referencia",
    "horquilla_min",
    "horquilla_max",
    "media",
    "ic_min",
    "ic_max",
    "anchura_ic",
    "dias_fuera",
    "media_dentro",
    "ic_estrecho",
    "resultado",
    "media_por_paciente",
    *PARAMETER_COLUMNS,
)

REPLICA_COLUMNS = (
    "replica",
    "fecha_inicio",
    "llegados_ventana",
    "censurados",
    "objetivo",
    "valor",
    "dias_fuera",
    *PARAMETER_COLUMNS,
)

LEVEL_COLUMNS = ("objetivo", "nivel", "porcentaje", "contribucion", *PARAMETER_COLUMNS)

SENSITIVITY_COLUMNS = (
    "mando",
    "manana",
    "tarde",
    "noche",
    "u_min",
    "u_max",
    "censurados_max",
    *(f"fuera_manchester_c_nivel_{level}" for level in COMPLIANCE_LEVELS),
    *(f"dias_fuera_c_nivel_{level}" for level in COMPLIANCE_LEVELS),
    *(f"dias_medidos_c_nivel_{level}" for level in COMPLIANCE_LEVELS),
    "objetivo",
    "media",
    "ic_min",
    "ic_max",
    "dias_fuera",
    "resultado",
    "elegida",
    "cumplidor",
    *PARAMETER_COLUMNS,
)


def _outcome(passed: bool) -> str:
    return "pasa" if passed else "FALLA"


def _levels(target: Target) -> str:
    return " ".join(str(level) for level in target.levels)


def _staff(staff: Sequence[int]) -> str:
    return f"[{', '.join(str(n) for n in staff)}]"


def _params(parameters: Mapping[str, object]) -> list[object]:
    return [parameters[name] for name in PARAMETER_COLUMNS]


def _optional(value: object) -> object:
    return "" if value is None else value


# --- Evaluation -------------------------------------------------------------------------------

_NAME_WIDTH = 30


def _censored_lines(replicas: Sequence[ReplicaValues]) -> list[str]:
    worst = max(replicas, key=lambda r: r.censored_share)
    lines = [
        f"Censurados (llegados en la ventana y sin salida al final del día de vaciado, "
        f"{DRAIN_DAYS} día): máximo {worst.censored} de {worst.arrivals}"
        f" ({100 * worst.censored_share:.2f} %) en una réplica;"
        f" {sum(r.censored for r in replicas)} en total"
    ]
    if worst.censored_share > CENSORED_WARNING:
        lines.append(
            f"AVISO: alguna réplica pasa del {100 * CENSORED_WARNING:g} % de censurados: las "
            "esperas pueden estar sesgadas a la baja"
        )
    return lines


def _breakdown_lines(target: Target, shares: Sequence[LevelShare]) -> list[str]:
    lines = [
        f"Desglose por nivel de {target.name} (porcentaje del nivel; contribución a la cifra"
        " global en puntos)"
    ]
    for s in shares:
        lines.append(f"    nivel {s.level}: {s.percentage:6.1f} %   {s.contribution:6.2f} puntos")
    lines.append(f"    total: {sum(s.contribution for s in shares):.2f} %")
    return lines


_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_CELL = 9


def _replica_lines(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    start_dates: Sequence[date],
    annual: bool,
) -> list[str]:
    """The value of each target in each replication, one column per replication."""
    labels = [
        f"{_MONTHS[d.month - 1]} {d.day}" if annual else f"r{i} {d.day}/{d.month}"
        for i, d in enumerate(start_dates)
    ]
    title = (
        "Por réplica (ventana anual: una por mes, desde el primer lunes; el valor de cada"
        " objetivo en los pacientes de la réplica)"
        if annual
        else "Por réplica (el valor de cada objetivo en los pacientes de la réplica)"
    )
    lines = [title, f"{'':<{_NAME_WIDTH}}" + "".join(f"{x:>{_CELL}}" for x in labels)]
    lines.append(
        f"{'llegados':<{_NAME_WIDTH}}" + "".join(f"{r.arrivals:>{_CELL}}" for r in replicas)
    )
    lines.append(
        f"{'censurados':<{_NAME_WIDTH}}" + "".join(f"{r.censored:>{_CELL}}" for r in replicas)
    )
    for r in results:
        lines.append(
            f"{r.target.name:<{_NAME_WIDTH}}" + "".join(f"{v:>{_CELL}.2f}" for v in r.values)
        )
    return lines


def _pooled_lines(
    results: Sequence[TargetResult], replicas: Sequence[ReplicaValues], annual: bool
) -> list[str]:
    what = (
        "con la ventana anual, la del año: pondera cada mes por sus pacientes"
        if annual
        else "pondera cada réplica por sus pacientes"
    )
    lines = [
        f"Media por paciente de todas las réplicas ({what}; se informa y no decide, la regla 4"
        " usa la media entre réplicas)",
        f"{'objetivo':<{_NAME_WIDTH}}{'entre réplicas':>16}{'por paciente':>14}",
    ]
    for r in results:
        pooled = pooled_value(replicas, r.target)
        lines.append(f"{r.target.name:<{_NAME_WIDTH}}{r.mean:>16.2f}{pooled:>14.2f}")
    return lines


def format_evaluation(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    start_dates: Sequence[date],
    *,
    annual: bool = False,
) -> str:
    """The table of ``calibracion evaluar``: one row per target, then the censored
    patients, the value of each replication (with the annual window, the profile
    by month), the mean per patient, the breakdown by level of each percentage
    and the outcome.

    Args:
        start_dates: The date on which each replication starts.
        annual: Whether the replications are those of the annual window.
    """
    lines = [
        f"{'objetivo':<{_NAME_WIDTH}}{'uso':<14}{'media':>8}  {'IC al 95 %':<20}"
        f"{'horquilla':<12}{'días fuera':>11}  resultado"
    ]
    for r in results:
        t = r.target
        interval = f"[{r.summary.ci_low:.2f}, {r.summary.ci_high:.2f}]"
        band = f"[{t.band[0]:g}, {t.band[1]:g}]"
        lines.append(
            f"{t.name:<{_NAME_WIDTH}}{t.use:<14}{r.mean:>8.2f}  {interval:<20}{band:<12}"
            f"{100 * r.share_days_out:>9.1f} %  {_outcome(r.passed)}"
        )
    lines += ["", *_censored_lines(replicas)]
    lines += ["", *_replica_lines(results, replicas, start_dates, annual)]
    lines += ["", *_pooled_lines(results, replicas, annual)]
    for r in results:
        if r.target.is_percentage:
            lines += ["", *_breakdown_lines(r.target, level_breakdown(replicas, r.target))]
    failed = [r.target.name for r in results if r.target.use == FIT and not r.passed]
    checks = [r.target.name for r in results if r.target.use != FIT and not r.passed]
    lines.append("")
    lines.append(
        f"Resultado: FALLAN objetivos de ajuste: {', '.join(failed)}"
        if failed
        else "Resultado: todos los objetivos de ajuste pasan"
    )
    if checks:
        lines.append(
            f"Comprobación (se informa, no cambia el resultado): fallan {', '.join(checks)}"
        )
    return "\n".join(lines)


def write_evaluation_csv(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    path: Path,
    parameters: Mapping[str, object],
) -> None:
    """One row per target: the band, the mean, its interval, the days out, the
    outcome and the mean per patient of all the replications (``pooled_value``)."""
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(EVALUATION_COLUMNS)
        for r in results:
            t = r.target
            writer.writerow(
                [
                    t.name,
                    t.measure,
                    _levels(t),
                    t.statistic,
                    _optional(t.threshold),
                    t.use,
                    _optional(t.reference),
                    t.band[0],
                    t.band[1],
                    repr(r.mean),
                    repr(r.summary.ci_low),
                    repr(r.summary.ci_high),
                    repr(r.ci_width),
                    repr(r.share_days_out),
                    r.within,
                    r.narrow,
                    "pasa" if r.passed else "falla",
                    repr(pooled_value(replicas, t)),
                    *_params(parameters),
                ]
            )


def write_replicas_csv(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    start_dates: Sequence[date],
    path: Path,
    parameters: Mapping[str, object],
) -> None:
    """One row per replication and target: its start date, its value, its days out
    and its censored."""
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REPLICA_COLUMNS)
        for i, rep in enumerate(replicas):
            for r in results:
                writer.writerow(
                    [
                        i,
                        start_dates[i].isoformat(),
                        rep.arrivals,
                        rep.censored,
                        r.target.name,
                        repr(r.values[i]),
                        repr(r.days_out[i]),
                        *_params(parameters),
                    ]
                )


def write_levels_csv(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    path: Path,
    parameters: Mapping[str, object],
) -> None:
    """One row per percentage target and level: its percentage and its contribution."""
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LEVEL_COLUMNS)
        for r in results:
            if not r.target.is_percentage:
                continue
            for s in level_breakdown(replicas, r.target):
                writer.writerow(
                    [
                        r.target.name,
                        s.level,
                        repr(s.percentage),
                        repr(s.contribution),
                        *_params(parameters),
                    ]
                )


# --- Sensitivity ------------------------------------------------------------------------------


def _cell_width(target: Target) -> int:
    return max(len(target.name), 12) + 2


def sensitivity_header(targets: Sequence[Target], knob: str) -> str:
    """The header of the table of ``calibracion sensibilidad``."""
    head = f"{'plantilla':<14}{'u':<17}"
    head += "".join(f"{t.name:<{_cell_width(t)}}" for t in targets)
    head += f"{'censurados':>11}"
    if knob == DOCTORS:
        head += "  días fuera de Manchester (C) / días medidos, sumados; niveles 2 a 5"
    return head


def format_sensitivity_row(row: SensitivityRow, knob: str) -> str:
    """One row of the table: each target as ``mean pasa`` or ``mean FALLA``."""
    s = row.staffing
    line = f"{_staff(s.staff):<14}{f'{s.u_low:.4f}–{s.u_high:.4f}':<17}"
    for r in row.results:
        line += f"{f'{r.mean:.2f} {_outcome(r.passed)}':<{_cell_width(r.target)}}"
    line += f"{100 * row.max_censored_share:>9.2f} %"
    if knob == DOCTORS:
        days = row.compliance_days
        line += "  " + " ".join(
            f"{days[level - 1][0]:>4}/{days[level - 1][1]:<4}" for level in COMPLIANCE_LEVELS
        )
    return line


def format_check(knob: str, seed: int, checked: Sequence[SensitivityRow]) -> str:
    """The check of the candidates with the check seed, in the order of the choice, until
    one passes its fit targets: each one with its mean and interval, vetoed or chosen."""
    names, _ = KNOB_TARGETS[knob]
    lines = [
        f"Comprobación con la semilla {seed} (las candidatas en el orden de la elección, hasta"
        f" la primera que pasa {', '.join(names)}; decisión 41):"
    ]
    for row in checked:
        cells = "; ".join(
            f"{name} {r.mean:.2f} [{r.summary.ci_low:.2f}, {r.summary.ci_high:.2f}]"
            f" {'pasa' if r.passed else 'FALLA'}"
            for name in names
            for r in (row.result(name),)
        )
        verdict = "elegida" if passes_fit(row, knob) else "vetada"
        lines.append(f"  {_staff(row.staffing.staff):<13} {cells} → {verdict}")
    if not checked:
        lines.append("  ninguna candidata pasa con la semilla de ajuste: no hay nada que comprobar")
    return "\n".join(lines)


def format_choice(
    knob: str,
    chosen: SensitivityRow | None,
    compliant: SensitivityRow | None = None,
    *,
    seeds: tuple[int, int] | None = None,
) -> str:
    """The lines below the table: the staffing chosen and, for the doctors, the compliant one.

    Args:
        seeds: The fit seed and the check seed, when the check seed may veto the choice
            (``choose_staffing`` with ``check``); without them, the choice is the one of
            the fit seed, and the line says that the check seed may veto it.
    """
    names, chooser = KNOB_TARGETS[knob]
    passing = ", ".join(names)
    if seeds is not None:
        passing += f" con las semillas {seeds[0]} y {seeds[1]}"
    lines = []
    if chosen is None:
        lines.append(f"Elección: ninguna plantilla de la regla pasa {passing}; no se fuerza")
    else:
        r = chosen.result(chooser)
        aim = "a la referencia" if r.target.reference is not None else "al centro de la horquilla"
        veto = (
            ""
            if seeds is not None
            else ", con la semilla de ajuste; la de comprobación puede vetarla (--comprobacion,"
            " decisión 41)"
        )
        lines.append(
            f"Elección (entre las que pasan {passing}, la más cercana {aim} de"
            f" {chooser}, {r.target.aim:g}): {_staff(chosen.staffing.staff)}"
            f" con u de {chosen.staffing.u_low:.4f} a {chosen.staffing.u_high:.4f};"
            f" {chooser} {r.mean:.2f}{veto}"
        )
    if knob == DOCTORS:
        if compliant is None:
            lines.append(
                f"Cumplidor: ninguna plantilla deja los niveles 2 a 5 con un máximo del"
                f" {100 * float(COMPLIANCE_SHARE_OUT):g} % de días fuera de Manchester (C),"
                " sumados en las réplicas"
            )
        else:
            lines.append(
                f"Cumplidor (u más alto con los niveles 2 a 5 a un máximo del"
                f" {100 * float(COMPLIANCE_SHARE_OUT):g} % de días fuera de Manchester con el"
                " reloj C, días sumados en las réplicas):"
                f" {_staff(compliant.staffing.staff)} con u de {compliant.staffing.u_low:.4f}"
                f" a {compliant.staffing.u_high:.4f}"
            )
    return "\n".join(lines)


def write_sensitivity_csv(
    rows: Sequence[SensitivityRow],
    knob: str,
    chosen: SensitivityRow | None,
    compliant: SensitivityRow | None,
    path: Path,
    parameters: Mapping[str, object],
) -> None:
    """One row per staffing and target."""
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(SENSITIVITY_COLUMNS)
        for row in rows:
            s = row.staffing
            out = row.compliance_out
            days = row.compliance_days
            for r in row.results:
                writer.writerow(
                    [
                        knob,
                        *s.staff,
                        s.u_low,
                        s.u_high,
                        repr(row.max_censored_share),
                        *(repr(out[level - 1]) for level in COMPLIANCE_LEVELS),
                        *(days[level - 1][0] for level in COMPLIANCE_LEVELS),
                        *(days[level - 1][1] for level in COMPLIANCE_LEVELS),
                        r.target.name,
                        repr(r.mean),
                        repr(r.summary.ci_low),
                        repr(r.summary.ci_high),
                        repr(r.share_days_out),
                        "pasa" if r.passed else "falla",
                        row is chosen,
                        row is compliant,
                        *_params(parameters),
                    ]
                )
