"""The texts of ``edsim registro`` in the terminal, in Spanish as the rest of the CLI.

``validar`` prints the profiles of the file, one block each, so the file can be read at a glance;
``generar`` prints where the recording went and the account that balances; ``comparar`` prints the
reconciliation and the table «indicador, verdad, registrado, diferencia». The module only formats:
it does not read files or import the runs.
"""

from collections.abc import Mapping
from pathlib import Path

from edsim.clinical_record.compare import Comparison, DelayStats
from edsim.clinical_record.profiles import RecordProfiles
from edsim.clinical_record.record import SYSTEMS, RecordProfile, Timed

_SYSTEM_NAMES = {"admision": "admisión", "triaje": "triaje", "his": "HIS", "lab": "laboratorio"}


def _g(value: float) -> str:
    return f"{value:g}"


def _timed(timed: Timed) -> str:
    median, p90 = timed.minutes
    return f"{_g(timed.rate)} (mediana {_g(median)} min, p90 {_g(p90)} min)"


def format_profile(profile: RecordProfile) -> str:
    """One profile: its rates, its delays by system and its clocks."""
    delays = "\n".join(
        f"    {_SYSTEM_NAMES[system]}: {_timed(profile.delay[system])}" for system in SYSTEMS
    )
    clocks = " · ".join(f"{_SYSTEM_NAMES[system]} {profile.clock[system]:+g}" for system in SYSTEMS)
    return (
        f"{profile.name}\n"
        f"  olvido {_g(profile.forget)} · campo vacío {_g(profile.empty)} · "
        f"valor erróneo {_g(profile.wrong)}\n"
        f"  duplicado: {_timed(profile.duplicate)}\n"
        f"  corrección (de los erróneos): {_timed(profile.correction)}\n"
        f"  retraso por sistema:\n{delays}\n"
        f"  reloj (minutos): {clocks}"
    )


def format_profiles(path: str | Path, fingerprint: str, profiles: RecordProfiles) -> str:
    """What ``validar`` prints: the file, its fingerprint and every profile."""
    names = ", ".join(profiles)
    header = f"Registro clínico · {path} (huella {fingerprint}) · {len(profiles)} perfiles: {names}"
    return "\n\n".join([header, *(format_profile(profiles[name]) for name in profiles)])


def format_recording(info: Mapping[str, object], folder: str | Path) -> str:
    """What ``generar`` prints: where it went and the account, which balances.

    Args:
        info: The content of ``registro.json``.
        folder: The folder of the recording.
    """
    c = info["cuenta"]
    return "\n".join(
        [
            f"Registro clínico de {info['run_id_origen']} · perfil {info['perfil']} · "
            f"semilla {info['semilla']} · horizonte {_g(info['horizonte'])} min",
            f"Ejecución derivada: {info['run_id']}",
            f"Carpeta: {folder}",
            f"Huella de los perfiles: {info['huella']}",
            "La cuenta cuadra:",
            f"  hechos de pacientes {c['hechos_pacientes']} = {c['bien']} bien + "
            f"{c['con_despistes']} con despistes + {c['perdido']} perdidos + "
            f"{c['pendiente']} pendientes al corte",
            f"  hechos de recursos {c['hechos_recursos']} = {c['recursos_bien']} bien + "
            f"{c['recursos_pendiente']} pendientes al corte",
            f"  registros escritos {c['registros']} = {c['bien']} bien + "
            f"{c['con_despistes']} con despistes + {c['recursos_bien']} de recursos + "
            f"{c['duplicado']} duplicados + {c['correccion']} correcciones",
            f"  correcciones {c['correccion']} escritas + {c['correccion_pendiente']} pendientes "
            f"al corte = {c['erroneos_con_correccion']} valores erróneos con corrección",
        ]
    )


_INDICATOR_LABELS = {
    "time_to_triage": "Tiempo hasta el triaje (mediana, min)",
    "time_to_doctor": "Tiempo hasta el médico (mediana, min)",
    "mean_in_department": "Pacientes en urgencias (media por hora)",
    "arrivals": "Llegadas (registros de llegada)",
}
_MISSING = "—"


def _value(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return _MISSING
    text = f"{value:g}"
    return f"+{text}" if signed and value > 0 and not text.startswith("-") else text


def _indicator_label(key: str) -> str:
    if key.startswith("level_"):
        return f"Nivel {key.removeprefix('level_')} en el triaje (%)"
    return _INDICATOR_LABELS[key]


def format_indicators(comparison: Comparison) -> str:
    """The table «indicador, verdad, registrado, diferencia» (recorded minus truth)."""
    header = ("Indicador", "Verdad", "Registrado", "Diferencia")
    body = [
        (
            _indicator_label(row.key),
            _value(row.truth),
            _value(row.recorded),
            _value(row.difference, signed=True),
        )
        for row in comparison.rows()
    ]
    widths = [max(len(line[i]) for line in (header, *body)) for i in range(4)]

    def line(cells: tuple[str, ...]) -> str:
        first, *numbers = (
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(cells, widths, strict=True))
        )
        return "  " + "  ".join([first, *numbers]).rstrip()

    return "\n".join(line(cells) for cells in (header, *body))


def _delay(stats: DelayStats) -> str:
    if stats.count == 0:
        return "n = 0"
    return f"n = {stats.count} · mediana {_value(stats.median)} min · p90 {_value(stats.p90)} min"


def format_comparison(
    comparison: Comparison,
    *,
    run_id: str,
    derived_run_id: str,
    profile: str,
    seed: int,
    source: str,
) -> str:
    """What ``comparar`` prints: the reconciliation, the delay of each system and the indicators.

    Args:
        comparison: The result of ``compare``.
        run_id: The true run.
        derived_run_id: The run of the recording.
        profile: The profile of the recording.
        seed: The seed of the recording.
        source: Where the records come from, such as ``ficheros``.
    """
    r = comparison.reconciliation
    k = r.by_kind
    s = r.slips
    clock_share = f" ({100 * s.only_clock / s.rows:.1f} %)" if s.rows else ""
    delays = "\n".join(
        f"    {_SYSTEM_NAMES[system]}: {_delay(r.delay[system])}" for system in SYSTEMS
    )
    return "\n".join(
        [
            f"Comparación de {run_id} · perfil {profile} · semilla {seed}",
            f"Ejecución derivada: {derived_run_id} · lo registrado sale de {source}",
            "",
            "Conciliación (la cuenta cuadra):",
            f"  hechos de la verdad {r.facts} = {k['bien']} bien + {k['con_despistes']} con "
            f"despistes + {k['perdido']} perdidos + {k['pendiente']} pendientes al corte",
            f"  registros escritos {r.records} = {k['bien']} bien + {k['con_despistes']} con "
            f"despistes + {k['duplicado']} duplicados + {k['correccion']} correcciones",
            f"  correcciones pendientes al corte: {k['correccion_pendiente']}",
            f"  con despistes ({s.rows}): reloj {s.clock} · retraso {s.delay} · valor erróneo "
            f"{s.wrong} · campo vacío {s.empty} (se solapan) · solo reloj {s.only_clock}"
            f"{clock_share}",
            "",
            "Retraso por sistema (registro menos hecho, de lo escrito para su propio hecho):",
            delays,
            "",
            "Indicadores ingenuos (primer registro de cada tipo, sin vacíos ni correcciones):",
            format_indicators(comparison),
        ]
    )
