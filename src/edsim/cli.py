"""Command-line interface of EDsim.

Options are in Spanish, as in the design; the code behind them is in English.
The CLI is a thin layer: it parses arguments, runs ``compare_mm1`` and hands
the results to ``edsim.queueing.report`` for the table, the CSV and the plot.
"""

import argparse
from importlib.metadata import version
from pathlib import Path

from edsim.queueing.replications import compare_mm1
from edsim.queueing.report import format_comparison, plot_sweep, write_sweep_csv

DEFAULT_RHOS = "0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,0.95"
CSV_NAME = "barrido.csv"
PLOT_NAME = "barrido_wq.png"


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


def _compare(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
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


def _sweep(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
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
    out_dir = Path(args.salida)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / CSV_NAME
    plot_path = out_dir / PLOT_NAME
    write_sweep_csv(points, csv_path, duration=args.duracion, warmup=args.warmup, seed=args.semilla)
    plot_sweep(points).savefig(plot_path, dpi=150)
    print(f"\nCSV: {csv_path}\nGráfica: {plot_path}")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``edsim`` parser with its ``mm1 comparar`` and ``mm1 barrido`` subcommands."""
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

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args, args.subparser)
