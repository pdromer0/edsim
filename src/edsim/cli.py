"""Command-line interface of EDsim.

Options are in Spanish, as in the design; the code behind them is in English.
The CLI is a thin layer: it parses arguments, runs the package (``compare_mm1``,
``simulate_arrivals``, ``validate_arrivals``) and hands the results to the
report modules for the tables, the CSV files and the plots.

Exit codes: 0 if all goes well; 1 if ``llegadas validar`` runs and some test
fails (the plots are written anyway); 2 for usage errors, including a missing
or invalid configuration, the limits of ``validar`` or a ``--salida`` that is
not a directory, before anything is computed or any file is created.
"""

import argparse
from importlib.metadata import version
from pathlib import Path

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.arrivals.report import (
    config_fingerprint,
    format_validation,
    plot_daily_residuals,
    plot_hourly_profile,
    plot_rescaled_qq,
    write_arrivals_csv,
    write_days_csv,
)
from edsim.arrivals.thinning import simulate_arrivals
from edsim.arrivals.validation import check_validation_counts, validate_arrivals
from edsim.queueing.replications import compare_mm1
from edsim.queueing.report import format_comparison, plot_sweep, write_sweep_csv

DEFAULT_RHOS = "0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,0.95"
CSV_NAME = "barrido.csv"
PLOT_NAME = "barrido_wq.png"

DEFAULT_CONFIG = "config/llegadas.toml"
ARRIVALS_CSV = "llegadas.csv"
DAYS_CSV = "dias.csv"
HOURLY_PLOT = "perfil_horario.png"
QQ_PLOT = "qq_reescalado.png"
RESIDUALS_PLOT = "recuentos_diarios.png"
SHORT_DAYS = 14
"""Days of each short run of test e, as in the specification."""


def parse_rhos(text: str) -> tuple[float, ...]:
    """Parse a comma-separated list of utilizations, each strictly in (0, 1)."""
    rhos = []
    for part in text.split(","):
        try:
            rho = float(part)
        except ValueError:
            raise argparse.ArgumentTypeError(f"'{part.strip()}' no es un número") from None
        # Written this way, NaN is rejected too.
        if not 0 < rho < 1:
            raise argparse.ArgumentTypeError(
                f"cada ρ debe estar entre 0 y 1, sin incluirlos; se recibió {rho:g}"
            )
        rhos.append(rho)
    return tuple(rhos)


def _add_experiment_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--duracion",
        type=float,
        default=10_000.0,
        metavar="T",
        help="tiempo observado por réplica, tras el calentamiento (por defecto: %(default)g)",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=1_000.0,
        metavar="T",
        help="tiempo inicial descartado en cada réplica (por defecto: %(default)g)",
    )
    parser.add_argument(
        "--replicas",
        type=int,
        default=20,
        metavar="R",
        help="número de réplicas independientes (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=2026,
        metavar="N",
        help="semilla maestra del experimento (por defecto: %(default)s)",
    )


def _output_dir(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    """The ``--salida`` directory, or a usage error (code 2) if it cannot be one.

    It is checked before computing anything, so that a long run is not lost
    at the end. The directory itself is still created only after the run:
    the nearest existing path (``--salida`` or a parent) must be a directory.
    """
    out_dir = Path(args.salida)
    for path in (out_dir, *out_dir.parents):
        if path.exists():
            if not path.is_dir():
                parser.error(f"--salida {args.salida}: {path} existe y no es un directorio")
            break
    return out_dir


def _compare(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        c = compare_mm1(args.lam, args.mu, args.duracion, args.warmup, args.replicas, args.semilla)
    except ValueError as e:
        parser.error(str(e))
    print(
        f"M/M/1 · λ = {args.lam:g}, μ = {args.mu:g}, ρ = {args.lam / args.mu:g}"
        f" · {args.replicas} réplicas · duración {args.duracion:g}"
        f" · warmup {args.warmup:g} · semilla {args.semilla}\n"
    )
    print(format_comparison(c))
    return 0


def _sweep(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    points = []
    for rho in args.rhos:
        try:
            c = compare_mm1(rho, 1.0, args.duracion, args.warmup, args.replicas, args.semilla)
        except ValueError as e:
            parser.error(str(e))
        wq = c.metric("wq")
        print(f"ρ = {rho:g}: Wq simulada {wq.summary.mean:.4f}, teórica {wq.theory:.4f}")
        points.append((rho, c))

    # The directory is created only once every simulation has succeeded.
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / CSV_NAME
    plot_path = out_dir / PLOT_NAME
    write_sweep_csv(points, csv_path, duration=args.duracion, warmup=args.warmup, seed=args.semilla)
    plot_sweep(points).savefig(plot_path, dpi=150)
    print(f"\nCSV: {csv_path}\nGráfica: {plot_path}")
    return 0


def _load_config(args: argparse.Namespace, parser: argparse.ArgumentParser) -> ArrivalProfile:
    """Load the profile and its fingerprint, or stop with a usage error (code 2)."""
    try:
        profile = load_profile(args.config)
        args.huella = config_fingerprint(args.config)
    # OSError: missing file or a directory. ValueError: invalid profile, and
    # also invalid TOML, because tomllib.TOMLDecodeError is a ValueError.
    except (OSError, ValueError) as e:
        parser.error(f"--config {args.config}: {e}")
    return profile


def _run_parameters(args: argparse.Namespace) -> dict:
    return {
        "config": args.config,
        "fingerprint": args.huella,
        "days": args.dias,
        "seed": args.semilla,
    }


def _generate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    profile = _load_config(args, parser)
    try:
        arrivals, days = simulate_arrivals(profile, args.dias, args.semilla)
    except ValueError as e:
        parser.error(str(e))

    # The directory is created only once the simulation has succeeded.
    out_dir.mkdir(parents=True, exist_ok=True)
    arrivals_path = out_dir / ARRIVALS_CSV
    days_path = out_dir / DAYS_CSV
    write_arrivals_csv(arrivals, profile.start_date, arrivals_path, **_run_parameters(args))
    write_days_csv(days, days_path, **_run_parameters(args))
    print(
        f"Llegadas · {args.config} (huella {args.huella}) · {args.dias} días"
        f" · semilla {args.semilla}: {len(arrivals)} llegadas\n"
        f"\nCSV: {arrivals_path}\nCSV: {days_path}"
    )
    return 0


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    profile = _load_config(args, parser)
    try:
        check_validation_counts(args.dias, args.replicas, args.ejecuciones_cortas, SHORT_DAYS)
    except ValueError as e:
        parser.error(str(e))
    print(
        f"Llegadas · {args.config} (huella {args.huella}) · CV {profile.daily_cv:g}"
        f" · {args.dias} días · {args.replicas} réplicas"
        f" · {args.ejecuciones_cortas} ejecuciones cortas de {SHORT_DAYS} días"
        f" · semilla {args.semilla}\n"
    )
    try:
        validation = validate_arrivals(
            profile,
            args.dias,
            args.replicas,
            args.semilla,
            short_runs=args.ejecuciones_cortas,
            short_days=SHORT_DAYS,
        )
    except ValueError as e:
        parser.error(str(e))
    print(format_validation(validation.results))

    # The plots are written even if a test fails: they help to find out why.
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = (
        (HOURLY_PLOT, plot_hourly_profile(profile, validation.arrivals, validation.days)),
        (QQ_PLOT, plot_rescaled_qq(profile, validation.arrivals, validation.days)),
        (RESIDUALS_PLOT, plot_daily_residuals(profile, validation.replications)),
    )
    print()
    for name, fig in figures:
        fig.savefig(out_dir / name, dpi=150)
        print(f"Gráfica: {out_dir / name}")
    return 0 if validation.passed else 1


def _add_arrival_options(parser: argparse.ArgumentParser, days: int) -> None:
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        metavar="FICHERO",
        help="perfil de llegadas en TOML (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=days,
        metavar="N",
        help="días completos simulados (por defecto: %(default)s)",
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--semilla",
        type=int,
        default=2026,
        metavar="N",
        help="semilla maestra (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--salida",
        default="resultados/llegadas",
        metavar="DIR",
        help="directorio de salida; se crea si no existe (por defecto: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``edsim`` parser with its ``mm1`` and ``llegadas`` subcommands."""
    parser = argparse.ArgumentParser(
        prog="edsim",
        description="Simulador de urgencias hospitalarias que genera datos "
        "sintéticos para un laboratorio de analítica",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('edsim')}")
    commands = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    mm1 = commands.add_parser(
        "mm1",
        help="cola M/M/1: comparación con la teoría",
        description="Cola M/M/1 simulada frente a la teoría de colas.",
    )
    actions = mm1.add_subparsers(dest="accion", required=True, metavar="accion")

    compare = actions.add_parser(
        "comparar",
        help="compara la simulación con la teoría en una tabla",
        description="Ejecuta las réplicas de una M/M/1 e imprime, para Wq, W, Lq, L y ρ, "
        "la teoría, la media simulada, el IC al 95 %, el error relativo y si la teoría "
        "cae dentro del intervalo.",
    )
    compare.add_argument(
        "--lam",
        type=float,
        default=0.8,
        metavar="λ",
        help="tasa de llegadas λ (por defecto: %(default)g)",
    )
    compare.add_argument(
        "--mu",
        type=float,
        default=1.0,
        metavar="μ",
        help="tasa de servicio μ (por defecto: %(default)g)",
    )
    _add_experiment_options(compare)
    compare.set_defaults(handler=_compare, subparser=compare)

    sweep = actions.add_parser(
        "barrido",
        help="barre la utilización ρ y guarda un CSV y una gráfica",
        description=f"Para cada ρ, con μ = 1, ejecuta las réplicas y guarda en el directorio "
        f"de salida {CSV_NAME} (una fila por ρ y métrica) y {PLOT_NAME} (Wq teórica frente "
        "a ρ y puntos simulados con su IC al 95 %).",
    )
    sweep.add_argument(
        "--rhos",
        type=parse_rhos,
        default=DEFAULT_RHOS,
        metavar="LISTA",
        help="utilizaciones separadas por comas, cada una entre 0 y 1 sin incluirlos "
        "(por defecto: %(default)s)",
    )
    sweep.add_argument(
        "--salida",
        default="resultados/mm1",
        metavar="DIR",
        help="directorio de salida; se crea si no existe (por defecto: %(default)s)",
    )
    _add_experiment_options(sweep)
    sweep.set_defaults(handler=_sweep, subparser=sweep)

    arrivals = commands.add_parser(
        "llegadas",
        help="llegadas: generación y validación estadística",
        description="Llegadas como un proceso de Poisson no homogéneo, generadas por thinning.",
    )
    arrival_actions = arrivals.add_subparsers(dest="accion", required=True, metavar="accion")

    generate = arrival_actions.add_parser(
        "generar",
        help="genera las llegadas y guarda dos CSV",
        description=f"Genera las llegadas de N días y guarda en el directorio de salida "
        f"{ARRIVALS_CSV} (una fila por llegada) y {DAYS_CSV} (una fila por día, con el "
        "efecto diario Z y el resto del ground truth).",
    )
    _add_arrival_options(generate, days=28)
    _add_output_options(generate)
    generate.set_defaults(handler=_generate, subparser=generate)

    validate = arrival_actions.add_parser(
        "validar",
        help="valida las llegadas con cinco pruebas y guarda tres gráficas",
        description="Ejecuta las cinco pruebas (volumen, forma horaria, huecos "
        "reescalados, dispersión diaria y uniformidad de los p-valores), imprime la "
        f"tabla y guarda {HOURLY_PLOT}, {QQ_PLOT} y {RESIDUALS_PLOT}. Termina con "
        "código 1 si alguna prueba falla.",
    )
    _add_arrival_options(validate, days=364)
    validate.add_argument(
        "--replicas",
        type=int,
        default=20,
        metavar="R",
        help="réplicas de la prueba de dispersión (por defecto: %(default)s)",
    )
    validate.add_argument(
        "--ejecuciones-cortas",
        type=int,
        default=100,
        metavar="N",
        help=f"ejecuciones de {SHORT_DAYS} días de la prueba de uniformidad "
        "(por defecto: %(default)s)",
    )
    _add_output_options(validate)
    validate.set_defaults(handler=_validate, subparser=validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code; the ``edsim`` script exits with it."""
    args = build_parser().parse_args(argv)
    return args.handler(args, args.subparser)
