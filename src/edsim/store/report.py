"""The texts of ``edsim almacen`` in the terminal, in Spanish as the rest of the CLI.

``preparar`` prints the migrations it applied; ``consumir`` prints a progress line every 10
real seconds and a summary at the end, which with ``--run`` says how many events are missing;
``cargar-verdad`` prints how many rows it wrote to each table of ``verdad``.
"""

from collections.abc import Sequence

from edsim.store.consumer import ConsumeReport
from edsim.store.migrations import Migration
from edsim.store.postgres import safe_url
from edsim.store.truth import TruthLoad


def format_migrations(url: str, applied: Sequence[Migration]) -> str:
    """What ``preparar`` did: the migrations applied, or that there was nothing to apply."""
    names = ", ".join(migration.file_name for migration in applied)
    done = names or "ninguna (la base de datos ya estaba al día)"
    return f"Postgres {safe_url(url)}\nMigraciones aplicadas: {done}"


def format_counts(report: ConsumeReport) -> str:
    """The counters of a consumption: saved, repeated ignored and rejected."""
    parts = [
        f"{report.saved} guardados",
        f"{report.repeated} repetidos ignorados",
        f"{report.rejected} rechazados",
    ]
    if report.errors:
        parts.append(f"{report.errors} errores del cliente apartados")
    return " · ".join(parts)


def format_progress(report: ConsumeReport) -> str:
    """The progress line, every 10 seconds."""
    return f"+{report.seconds:.0f} s · {format_counts(report)}"


def format_consume_end(report: ConsumeReport, run_id: str | None) -> str:
    """The summary at the end: why it stopped, the counters and, with ``run_id``, what is
    missing."""
    counts = format_counts(report)
    if run_id is None:
        return f"Consumidor parado tras {report.seconds:.0f} s: {counts}"
    progress = report.progress
    if report.complete:
        return (
            f"{run_id}: completa en bronce, {progress.stored} eventos de {progress.published}"
            f" publicados ({report.seconds:.0f} s): {counts}"
        )
    why = "parado con Ctrl+C" if report.stopped else f"sin terminar tras {report.seconds:.0f} s"
    if progress is None or not progress.started:
        missing = "bronce aún no tiene su inicio"
    elif progress.published is None:
        missing = f"bronce tiene {progress.stored} eventos y aún no su fin"
    else:
        missing = f"faltan {progress.missing} de {progress.published} publicados"
    return f"{run_id}: {why}; {missing}: {counts}"


def format_truth_load(url: str, load: TruthLoad) -> str:
    """What ``cargar-verdad`` did: the rows of each table and the recordings of the ledger.

    A run without recordings says so and how to write them: its ledger stays empty, not an error.
    """
    counts = load.counts
    rows = (
        f"{counts['eventos']} eventos · {counts['episodios']} episodios · {counts['dias']} días"
        f" · {counts['libreta']} filas de libreta"
    )
    if load.recordings:
        ledger = f"Libreta de: {', '.join(load.recordings)}"
    else:
        ledger = (
            f"Sin libreta: {load.run_id} no tiene registros/ "
            f"(la escribe edsim registro generar {load.run_id} --perfil PERFIL)"
        )
    return (
        f"Postgres {safe_url(url)}\n"
        f"{load.run_id}: verdad cargada en {load.seconds:.1f} s: {rows}\n{ledger}"
    )
