"""Tables and CSV files of ``edsim calibracion evaluar`` and ``sensibilidad``.

The CSV files are tidy (one row per target, per replication and target, per
level or per staffing and target) and every row carries the parameters of
the run: the four files with their fingerprints, the replications, the days,
the warm-up and the seed, so that a row of the calibration log can be traced
back to the command that produced it.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
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
    *PARAMETER_COLUMNS,
)

REPLICA_COLUMNS = (
    "replica",
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


def format_evaluation(results: Sequence[TargetResult], replicas: Sequence[ReplicaValues]) -> str:
    """The table of ``calibracion evaluar``: one row per target, then the censored
    patients, the breakdown by level of each percentage and the outcome."""
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
    results: Sequence[TargetResult], path: Path, parameters: Mapping[str, object]
) -> None:
    """One row per target: the band, the mean, its interval, the days out and the outcome."""
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
                    *_params(parameters),
                ]
            )


def write_replicas_csv(
    results: Sequence[TargetResult],
    replicas: Sequence[ReplicaValues],
    path: Path,
    parameters: Mapping[str, object],
) -> None:
    """One row per replication and target: its value, its days out and its censored."""
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REPLICA_COLUMNS)
        for i, rep in enumerate(replicas):
            for r in results:
                writer.writerow(
                    [
                        i,
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


def _share(x: float) -> str:
    """A share as a percentage; ``—`` for a level without patients."""
    return f"{'—':>7}" if math.isnan(x) else f"{100 * x:5.1f} %"


def _cell_width(target: Target) -> int:
    return max(len(target.name), 12) + 2


def sensitivity_header(targets: Sequence[Target], knob: str) -> str:
    """The header of the table of ``calibracion sensibilidad``."""
    head = f"{'plantilla':<14}{'u':<17}"
    head += "".join(f"{t.name:<{_cell_width(t)}}" for t in targets)
    head += f"{'censurados':>11}"
    if knob == DOCTORS:
        head += "  fuera de Manchester (C), niveles 2 a 5"
    return head


def format_sensitivity_row(row: SensitivityRow, knob: str) -> str:
    """One row of the table: each target as ``mean pasa`` or ``mean FALLA``."""
    s = row.staffing
    line = f"{_staff(s.staff):<14}{f'{s.u_low:.4f}–{s.u_high:.4f}':<17}"
    for r in row.results:
        line += f"{f'{r.mean:.2f} {_outcome(r.passed)}':<{_cell_width(r.target)}}"
    line += f"{100 * row.max_censored_share:>9.2f} %"
    if knob == DOCTORS:
        out = row.compliance_out
        line += "  " + " ".join(_share(out[level - 1]) for level in COMPLIANCE_LEVELS)
    return line


def format_choice(
    knob: str, chosen: SensitivityRow | None, compliant: SensitivityRow | None = None
) -> str:
    """The lines below the table: the staffing chosen and, for the doctors, the compliant one."""
    names, chooser = KNOB_TARGETS[knob]
    lines = []
    if chosen is None:
        lines.append(
            f"Elección: ninguna plantilla de la regla pasa {', '.join(names)}; no se fuerza"
        )
    else:
        r = chosen.result(chooser)
        aim = "a la referencia" if r.target.reference is not None else "al centro de la horquilla"
        lines.append(
            f"Elección (entre las que pasan {', '.join(names)}, la más cercana {aim} de"
            f" {chooser}, {r.target.aim:g}): {_staff(chosen.staffing.staff)}"
            f" con u de {chosen.staffing.u_low:.4f} a {chosen.staffing.u_high:.4f};"
            f" {chooser} {r.mean:.2f}"
        )
    if knob == DOCTORS:
        if compliant is None:
            lines.append(
                f"Cumplidor: ninguna plantilla deja los niveles 2 a 5 con un máximo del"
                f" {100 * COMPLIANCE_SHARE_OUT:g} % de días fuera de Manchester (C)"
            )
        else:
            lines.append(
                f"Cumplidor (u más alto con los niveles 2 a 5 a un máximo del"
                f" {100 * COMPLIANCE_SHARE_OUT:g} % de días fuera de Manchester con el reloj C):"
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
            for r in row.results:
                writer.writerow(
                    [
                        knob,
                        *s.staff,
                        s.u_low,
                        s.u_high,
                        repr(row.max_censored_share),
                        *(repr(out[level - 1]) for level in COMPLIANCE_LEVELS),
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
