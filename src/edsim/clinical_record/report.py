"""The texts of ``edsim registro`` in the terminal, in Spanish as the rest of the CLI.

``validar`` prints the profiles of the file, one block each, so the file can be read at a glance;
``generar`` prints where the recording went and the account that balances. The module only formats:
it does not read files or import the runs.
"""

from collections.abc import Mapping
from pathlib import Path

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
