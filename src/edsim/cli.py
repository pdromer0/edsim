"""Command-line interface of EDsim.

Options are in Spanish, as in the design; the code behind them is in English.
The CLI is a thin layer: it parses arguments, runs the package (``compare_mm1``,
``simulate_arrivals``, ``validate_arrivals``, ``simulate_run``,
``validate_engine``, ``validate_profiles``, ``simulate_replicas``,
``sensitivity``) and hands the results to the report modules for the tables,
the CSV files and the plots.

Exit codes: 0 if all goes well; 1 if ``llegadas validar``, ``motor validar``
or ``perfiles validar`` runs and some check fails, ``motor simular`` finds a
broken invariant, ``calibracion evaluar`` finds a fit target out of its band or
``calibracion sensibilidad`` finds no staffing that passes the targets of its
knob (the files are written anyway, to find out why); 2 for usage
errors, including a missing or invalid configuration, invalid limits or a
``--salida`` that is not a directory, before anything is printed or computed
and before any file is created.
"""

import argparse
from collections.abc import Callable
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
from edsim.calibration.evaluate import (
    DRAIN_DAYS,
    FIT_SEED,
    check_knob_targets,
    choose_staffing,
    compliant_staffing,
    evaluate_staffings,
    sensitivity,
    simulate_replicas,
    summarize_targets,
)
from edsim.calibration.report import (
    format_check,
    format_choice,
    format_evaluation,
    format_sensitivity_row,
    sensitivity_header,
    write_evaluation_csv,
    write_levels_csv,
    write_replicas_csv,
    write_sensitivity_csv,
)
from edsim.calibration.staffing import DOCTORS, KNOBS, U_MAX, U_MIN, U_STEP, u_grid
from edsim.calibration.targets import FIT, load_targets
from edsim.calibration.window import (
    ANNUAL,
    ANNUAL_REPLICAS,
    START_REPLICAS,
    WINDOWS,
    replica_start_dates,
    window_replicas,
    window_start_dates,
)
from edsim.checks import check_count
from edsim.engine.center import CenterConfig, load_center
from edsim.engine.engine import check_horizon, default_run_id
from edsim.engine.report import (
    format_engine_validation,
    format_run_summary,
    plot_census,
    plot_hourly_census,
    plot_mg1,
    plot_waits_by_level,
)
from edsim.engine.validation import check_engine_validation_counts, validate_engine
from edsim.profiles.config import load_profiles
from edsim.profiles.report import FALSE_ALARM, PLOTS, format_profiles_validation
from edsim.profiles.validation import (
    DEFAULT_MIXING_PATIENTS,
    check_profiles_validation_counts,
    validate_profiles,
)
from edsim.queueing.replications import compare_mm1
from edsim.queueing.report import format_comparison, plot_sweep, write_sweep_csv
from edsim.runs import simulate_run, validate_run_id

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

DEFAULT_CENTER = "config/centro.toml"
DEFAULT_PROVISIONAL_CENTER = "tests/data/centro_ejemplo.toml"
"""Center of the provisional model, with ``[triaje]``, ``[duraciones]`` and ``[pruebas]``.

``config/centro.toml`` has no provisional block since task 4.9: ``motor validar``,
which validates the engine with the provisional model, uses this one by default.
"""
EVENTS_FILE = "eventos.jsonl"
EPISODES_CSV = "ground_truth_episodios.csv"
GROUND_TRUTH_DAYS_CSV = "ground_truth_dias.csv"
CENSUS_PLOT = "censo.png"
WAITS_PLOT = "esperas_por_nivel.png"
MG1_PLOT = "mg1.png"
HOURLY_CENSUS_PLOT = "censo_por_hora.png"

DEFAULT_PROFILES = "config/perfiles.toml"
PROFILE_PLOTS = tuple(name for name, _ in PLOTS)

DEFAULT_TARGETS = "config/objetivos.toml"
EVALUATION_CSV = "evaluacion.csv"
REPLICAS_CSV = "evaluacion_replicas.csv"
LEVELS_CSV = "evaluacion_niveles.csv"
SENSITIVITY_CSV = "sensibilidad_{knob}.csv"


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


def _load_file[T](
    path: str, option: str, loader: Callable[[str], T], parser: argparse.ArgumentParser
) -> tuple[T, str]:
    """Load a configuration file and its fingerprint, or stop with a usage error (code 2)."""
    try:
        return loader(path), config_fingerprint(path)
    # OSError: missing file or a directory. ValueError: invalid configuration,
    # and also invalid TOML, because tomllib.TOMLDecodeError is a ValueError.
    except (OSError, ValueError) as e:
        parser.error(f"{option} {path}: {e}")


def _load_config(args: argparse.Namespace, parser: argparse.ArgumentParser) -> ArrivalProfile:
    """Load the profile and its fingerprint, or stop with a usage error (code 2)."""
    profile, args.huella = _load_file(args.config, "--config", load_profile, parser)
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


def _engine_header(args: argparse.Namespace) -> str:
    return (
        f"Motor · centro {args.centro} (huella {args.huella_centro})"
        f" · llegadas {args.llegadas} (huella {args.huella_llegadas})"
    )


def _load_engine_configs(args: argparse.Namespace, parser: argparse.ArgumentParser):
    center, args.huella_centro = _load_file(args.centro, "--centro", load_center, parser)
    profile, args.huella_llegadas = _load_file(args.llegadas, "--llegadas", load_profile, parser)
    return center, profile


def _check_provisional_center(
    center: CenterConfig, args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Stop with a usage error (code 2) if the provisional model gets a center without its block."""
    if not center.has_provisional:
        parser.error(
            f"--centro {args.centro}: el modelo provisional necesita las tablas [triaje], "
            "[duraciones] y [pruebas] del centro, y este no las tiene; su centro es "
            f"{DEFAULT_PROVISIONAL_CENTER}"
        )


def _model_line(args: argparse.Namespace) -> str:
    if args.perfiles is None:
        return "Modelo provisional"
    return f"Modelo clínico · perfiles {args.perfiles} (huella {args.huella_perfiles})"


def _simulate_engine(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    run_id = default_run_id(args.semilla) if args.run_id is None else args.run_id
    try:
        validate_run_id(run_id)
    except ValueError as error:
        parser.error(f"--run-id: {error}; indica un --run-id explícito válido")
    if args.salida is None:
        args.salida = str(Path("resultados/ejecuciones") / run_id)
    out_dir = _output_dir(args, parser)
    if out_dir.exists() or out_dir.is_symlink():
        parser.error(f"--salida {out_dir}: ya existe; elige otro --run-id o --salida")
    center, _ = _load_engine_configs(args, parser)
    # The clinical model is the default (decision 44): without --provisional, the
    # profiles are --perfiles or config/perfiles.toml.
    if args.provisional:
        _check_provisional_center(center, args, parser)
    else:
        if args.perfiles is None:
            args.perfiles = DEFAULT_PROFILES
        _, args.huella_perfiles = _load_file(args.perfiles, "--perfiles", load_profiles, parser)
    try:
        check_horizon(args.dias, args.calentamiento)
    except ValueError as error:
        parser.error(str(error))
    print(
        f"{_engine_header(args)}\n{_model_line(args)}"
        f"\n{args.dias} días ({args.calentamiento} de calentamiento)"
        f" · semilla {args.semilla} · run_id {run_id}\n",
        flush=True,
    )
    try:
        result = simulate_run(
            args.centro,
            args.llegadas,
            args.dias,
            args.semilla,
            output_dir=out_dir,
            warmup_days=args.calentamiento,
            run_id=run_id,
            origin="cli",
            profiles=args.perfiles,
        )
    except FileExistsError:
        parser.error(f"--salida {out_dir}: ya existe; elige otro --run-id o --salida")
    print(format_run_summary(result.analysis, result.violations))
    print(
        f"\nLog: {out_dir / EVENTS_FILE}\nCSV: {out_dir / EPISODES_CSV}"
        f"\nCSV: {out_dir / GROUND_TRUTH_DAYS_CSV}"
    )
    return 1 if result.violations else 0


def _validate_engine(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    center, profile = _load_engine_configs(args, parser)
    _check_provisional_center(center, args, parser)
    try:
        check_engine_validation_counts(replicas=args.replicas)
    except ValueError as e:
        parser.error(str(e))
    print(
        f"{_engine_header(args)}\n{args.replicas} réplicas · semilla {args.semilla}\n\n"
        "Validando el motor: invariantes, leyes operacionales, M/G/1, Mₜ/G/∞ y condiciones"
        " extremas. Con los valores por defecto tarda unos 2 minutos.\n",
        flush=True,
    )
    validation = validate_engine(center, profile, seed=args.semilla, replicas=args.replicas)
    print(format_engine_validation(validation.results))

    # The plots are written even if a check fails: they help to find out why.
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = (
        (CENSUS_PLOT, plot_census(validation.long_run, center, profile.start_date)),
        (WAITS_PLOT, plot_waits_by_level(validation.long_run.metrics)),
        (MG1_PLOT, plot_mg1(validation.mg1, validation.result("mg1").details[0])),
        (HOURLY_CENSUS_PLOT, plot_hourly_census(validation.hourly)),
    )
    print()
    for name, fig in figures:
        fig.savefig(out_dir / name, dpi=150)
        print(f"Gráfica: {out_dir / name}")
    return 0 if validation.passed else 1


def _validate_profiles(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    profiles, huella_perfiles = _load_file(args.perfiles, "--perfiles", load_profiles, parser)
    arrival_profile, huella_llegadas = _load_file(args.llegadas, "--llegadas", load_profile, parser)
    if args.semilla < 0:
        parser.error(f"--semilla debe ser un entero no negativo; se recibió {args.semilla}")
    try:
        mixing, year = check_profiles_validation_counts(profiles, arrival_profile, args.pacientes)
    except ValueError as error:
        parser.error(f"--pacientes: {error}")
    print(
        f"Perfiles · {args.perfiles} (huella {huella_perfiles})"
        f" · llegadas {args.llegadas} (huella {huella_llegadas})\n"
        f"{mixing} pacientes por contexto en la mezcla · {year} en la muestra del año"
        f" · semilla {args.semilla}\n\n"
        "Validando el muestreador: mezcla de motivos, triaje, pruebas y duraciones. Con los"
        " valores por defecto tarda unos 30 segundos.\n",
        flush=True,
    )
    validation = validate_profiles(
        profiles, arrival_profile, seed=args.semilla, patients=args.pacientes
    )
    print(format_profiles_validation(validation))

    # The plots are written even if a check fails: they help to find out why.
    out_dir.mkdir(parents=True, exist_ok=True)
    print()
    for name, plot in PLOTS:
        plot(validation.figures).savefig(out_dir / name, dpi=150)
        print(f"Gráfica: {out_dir / name}")
    return 0 if validation.passed else 1


def _load_calibration(args: argparse.Namespace, parser: argparse.ArgumentParser):
    """Load the four files and check the window and the counts, or stop with code 2
    before simulating. Sets ``args.replicas`` (the window's default without
    ``--replicas``) and ``args.fechas``, the start date of each replication."""
    center, args.huella_centro = _load_file(args.centro, "--centro", load_center, parser)
    profile, args.huella_llegadas = _load_file(args.llegadas, "--llegadas", load_profile, parser)
    profiles, args.huella_perfiles = _load_file(args.perfiles, "--perfiles", load_profiles, parser)
    targets, args.huella_objetivos = _load_file(args.objetivos, "--objetivos", load_targets, parser)
    try:
        args.replicas = window_replicas(args.ventana, args.replicas)
    except ValueError as error:
        parser.error(
            f"la ventana anual tiene {ANNUAL_REPLICAS} réplicas, una por mes: quita --replicas"
            f" o usa --ventana inicio ({error})"
        )
    try:
        check_count("replicas", args.replicas, 2)
        check_horizon(args.dias, args.calentamiento)
    except ValueError as error:
        parser.error(str(error))
    args.fechas = window_start_dates(args.ventana, profile)
    args.fechas_replicas = replica_start_dates(args.ventana, profile, args.replicas)
    args.inicio = profile.start_date
    return center, profile, profiles, targets


def _calibration_parameters(args: argparse.Namespace) -> dict:
    return {
        "centro": args.centro,
        "huella_centro": args.huella_centro,
        "llegadas": args.llegadas,
        "huella_llegadas": args.huella_llegadas,
        "perfiles": args.perfiles,
        "huella_perfiles": args.huella_perfiles,
        "objetivos": args.objetivos,
        "huella_objetivos": args.huella_objetivos,
        "ventana": args.ventana,
        "replicas": args.replicas,
        "dias": args.dias,
        "calentamiento": args.calentamiento,
        "semilla": args.semilla,
    }


def _window_text(args: argparse.Namespace) -> str:
    if args.ventana == ANNUAL:
        return (
            f"ventana anual (una réplica por mes, desde el primer lunes de cada mes de"
            f" {args.inicio.year})"
        )
    return f"ventana inicio (todas desde {args.inicio.isoformat()})"


def _calibration_header(args: argparse.Namespace) -> str:
    return (
        f"{_engine_header(args)}\n"
        f"Perfiles {args.perfiles} (huella {args.huella_perfiles})"
        f" · objetivos {args.objetivos} (huella {args.huella_objetivos})\n"
        f"{args.replicas} réplicas de {args.dias} días ({args.calentamiento} de calentamiento"
        f" y {DRAIN_DAYS} de vaciado) · {_window_text(args)} · semilla {args.semilla}"
    )


def _evaluate_calibration(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    center, profile, profiles, targets = _load_calibration(args, parser)
    print(f"{_calibration_header(args)}\n", flush=True)
    replicas = simulate_replicas(
        center,
        profile,
        profiles,
        targets,
        replicas=args.replicas,
        days=args.dias,
        warmup_days=args.calentamiento,
        seed=args.semilla,
        start_dates=args.fechas,
    )
    results = summarize_targets(replicas, targets)
    print(format_evaluation(results, replicas, args.fechas_replicas, annual=args.ventana == ANNUAL))

    # The files are written even if a target fails: they help to find out why.
    out_dir.mkdir(parents=True, exist_ok=True)
    parameters = _calibration_parameters(args)
    write_evaluation_csv(results, replicas, out_dir / EVALUATION_CSV, parameters)
    write_replicas_csv(results, replicas, args.fechas_replicas, out_dir / REPLICAS_CSV, parameters)
    write_levels_csv(results, replicas, out_dir / LEVELS_CSV, parameters)
    print()
    for name in (EVALUATION_CSV, REPLICAS_CSV, LEVELS_CSV):
        print(f"CSV: {out_dir / name}")
    return 1 if any(r.target.use == FIT and not r.passed for r in results) else 0


def _calibration_sensitivity(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    center, profile, profiles, targets = _load_calibration(args, parser)
    try:
        check_knob_targets(targets, args.mando)
        u_grid(args.u_min, args.u_max, args.paso)
    except ValueError as error:
        parser.error(str(error))
    if args.comprobacion == args.semilla:
        parser.error(
            f"la semilla de comprobación ({args.comprobacion}) tiene que ser distinta de la de"
            f" ajuste ({args.semilla}) (regla 3)"
        )
    check_text = (
        ""
        if args.comprobacion is None
        else f"; comprobación con la semilla {args.comprobacion}, que puede vetar la elección"
    )
    print(
        f"{_calibration_header(args)}\nSensibilidad del mando {args.mando} con u de"
        f" {args.u_min:g} a {args.u_max:g} en pasos de {args.paso:g}; el otro mando, como en"
        f" el centro{check_text}\n\n{sensitivity_header(targets, args.mando)}",
        flush=True,
    )
    rows = sensitivity(
        center,
        profile,
        profiles,
        targets,
        args.mando,
        replicas=args.replicas,
        days=args.dias,
        warmup_days=args.calentamiento,
        seed=args.semilla,
        u_min=args.u_min,
        u_max=args.u_max,
        step=args.paso,
        start_dates=args.fechas,
        on_row=lambda row: print(format_sensitivity_row(row, args.mando), flush=True),
    )
    if args.comprobacion is None:
        chosen = choose_staffing(rows, args.mando)
        seeds = None
    else:
        checked = []

        def check(row):
            # The same staffing with the check seed, the same window and the rest of the
            # options; asked only for the candidates the choice needs, in its order.
            (row_checked,) = evaluate_staffings(
                center,
                profile,
                profiles,
                targets,
                args.mando,
                [row.staffing],
                replicas=args.replicas,
                days=args.dias,
                warmup_days=args.calentamiento,
                seed=args.comprobacion,
                start_dates=args.fechas,
            )
            checked.append(row_checked)
            return row_checked

        chosen = choose_staffing(rows, args.mando, check=check)
        seeds = (args.semilla, args.comprobacion)
        print(f"\n{format_check(args.mando, args.comprobacion, checked)}")
    compliant = compliant_staffing(rows) if args.mando == DOCTORS else None
    print(f"\n{format_choice(args.mando, chosen, compliant, seeds=seeds)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SENSITIVITY_CSV.format(knob=args.mando)
    write_sensitivity_csv(rows, args.mando, chosen, compliant, path, _calibration_parameters(args))
    print(f"\nCSV: {path}")
    return 0 if chosen is not None else 1


def _add_engine_options(parser: argparse.ArgumentParser, center: str = DEFAULT_CENTER) -> None:
    parser.add_argument(
        "--centro",
        default=center,
        metavar="FICHERO",
        help="configuración del centro en TOML (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--llegadas",
        default=DEFAULT_CONFIG,
        metavar="FICHERO",
        help="perfil de llegadas en TOML (por defecto: %(default)s)",
    )


def _add_calibration_options(parser: argparse.ArgumentParser) -> None:
    _add_engine_options(parser)
    parser.add_argument(
        "--perfiles",
        default=DEFAULT_PROFILES,
        metavar="FICHERO",
        help="perfiles clínicos en TOML (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--objetivos",
        default=DEFAULT_TARGETS,
        metavar="FICHERO",
        help="objetivos de calibración en TOML (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--ventana",
        choices=WINDOWS,
        default=ANNUAL,
        help="anual: una réplica por mes, la m desde el primer lunes del mes m+1 del año de "
        "fecha_inicio, de modo que la media es la del año (tarea 4.6c); inicio: todas desde "
        "fecha_inicio, como en la tarea 4.6b (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--replicas",
        type=int,
        default=None,
        metavar="R",
        help=f"réplicas, cada una con un hijo de la semilla: {ANNUAL_REPLICAS} con la ventana "
        f"anual, la única que admite; {START_REPLICAS} por defecto con la ventana inicio",
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=14,
        metavar="N",
        help="días completos de cada réplica, con el calentamiento y sin el día de vaciado "
        "(por defecto: %(default)s)",
    )
    parser.add_argument(
        "--calentamiento",
        type=int,
        default=2,
        metavar="N",
        help="días completos de calentamiento, fuera de la ventana (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=FIT_SEED,
        metavar="N",
        help="semilla maestra: la de ajuste es 2026; la de comprobación, 2027, que puede vetar "
        "la plantilla elegida y no elegirla; y 2028, la comprobación independiente después de "
        "un veto (por defecto: %(default)s)",
    )
    parser.add_argument(
        "--salida",
        default="resultados/calibracion",
        metavar="DIR",
        help="directorio de salida; se crea si no existe (por defecto: %(default)s)",
    )


def _add_engine_output_options(
    parser: argparse.ArgumentParser, *, simulation: bool = False
) -> None:
    output_help = (
        "directorio de salida, que no debe existir (por defecto: resultados/ejecuciones/<run_id>)"
        if simulation
        else None
    )
    _add_output_options(parser, output_help=output_help)
    parser.set_defaults(salida=None if simulation else "resultados/motor")


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


def _add_output_options(parser: argparse.ArgumentParser, *, output_help: str | None = None) -> None:
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
        help=output_help or "directorio de salida; se crea si no existe (por defecto: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``edsim`` parser: ``mm1``, ``llegadas``, ``motor``, ``perfiles`` and
    ``calibracion``."""
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

    engine = commands.add_parser(
        "motor",
        help="motor de eventos: simulación y validación",
        description="Motor de eventos discretos del servicio de urgencias.",
    )
    engine_actions = engine.add_subparsers(dest="accion", required=True, metavar="accion")

    simulate = engine_actions.add_parser(
        "simular",
        help="simula el centro y guarda el log y el ground truth",
        description=f"Simula N días y guarda en el directorio de salida {EVENTS_FILE} (el "
        f"log de eventos), {EPISODES_CSV} y {GROUND_TRUTH_DAYS_CSV} (el ground truth). "
        "Comprueba las invariantes e imprime un resumen derivado del log. Termina con "
        "código 1 si alguna invariante falla. Simula el modelo clínico, el de por defecto: "
        f"cada paciente sale de los perfiles ({DEFAULT_PROFILES} o --perfiles), y la "
        "ejecución guarda también una copia de ellos. Con --provisional, el modelo "
        "provisional del hito 3, que se queda para la validación del motor y necesita un "
        "centro con [triaje], [duraciones] y [pruebas], como "
        f"{DEFAULT_PROVISIONAL_CENTER}.",
    )
    _add_engine_options(simulate)
    model = simulate.add_mutually_exclusive_group()
    model.add_argument(
        "--perfiles",
        default=None,
        metavar="FICHERO",
        help=f"perfiles clínicos en TOML (por defecto: {DEFAULT_PROFILES})",
    )
    model.add_argument(
        "--provisional",
        action="store_true",
        help="simula el modelo provisional del hito 3 en lugar del clínico; necesita un "
        f"--centro con su bloque provisional, como {DEFAULT_PROVISIONAL_CENTER}",
    )
    simulate.add_argument(
        "--dias",
        type=int,
        default=14,
        metavar="N",
        help="días completos simulados, con el calentamiento (por defecto: %(default)s)",
    )
    simulate.add_argument(
        "--calentamiento",
        type=int,
        default=2,
        metavar="N",
        help="días completos de calentamiento, fuera de las métricas (por defecto: %(default)s)",
    )
    simulate.add_argument(
        "--run-id",
        type=validate_run_id,
        default=None,
        metavar="ID",
        help="identificador de la ejecución en el log (por defecto: r y la semilla)",
    )
    _add_engine_output_options(simulate, simulation=True)
    simulate.set_defaults(handler=_simulate_engine, subparser=simulate)

    engine_validate = engine_actions.add_parser(
        "validar",
        help="valida el motor y guarda cuatro gráficas",
        description="Ejecuta la validación del motor (invariantes, Little, utilización, "
        "M/G/1, Mₜ/G/∞, capacidad infinita y más médicos), imprime la tabla y guarda "
        f"{CENSUS_PLOT}, {WAITS_PLOT}, {MG1_PLOT} y {HOURLY_CENSUS_PLOT}. Tarda unos "
        "2 minutos. Termina con código 1 si alguna comprobación falla. Usa el modelo "
        "provisional, que tiene teoría conocida (M/G/1), con su centro: por defecto "
        f"{DEFAULT_PROVISIONAL_CENTER}.",
    )
    _add_engine_options(engine_validate, center=DEFAULT_PROVISIONAL_CENTER)
    engine_validate.add_argument(
        "--replicas",
        type=int,
        default=20,
        metavar="R",
        help="réplicas de la M/G/1 y de la Mₜ/G/∞ (por defecto: %(default)s)",
    )
    _add_engine_output_options(engine_validate)
    engine_validate.set_defaults(handler=_validate_engine, subparser=engine_validate)

    profiles = commands.add_parser(
        "perfiles",
        help="perfiles clínicos: validación del muestreador",
        description="Perfiles clínicos de los pacientes (hito 4).",
    )
    profile_actions = profiles.add_subparsers(dest="accion", required=True, metavar="accion")
    profiles_validate = profile_actions.add_parser(
        "validar",
        help="valida el muestreador clínico sin el motor y guarda cuatro gráficas",
        description="Sortea pacientes con el muestreador clínico, sin el motor, y los compara "
        "con lo exacto de los perfiles: la mezcla de motivos por contexto, el triaje (niveles "
        "asignados y matriz real × asignado), las pruebas y las duraciones. Imprime una tabla "
        f"con una fila por comprobación y guarda {', '.join(PROFILE_PLOTS)}. Termina con "
        f"código 1 si alguna comprobación falla. {FALSE_ALARM}",
    )
    profiles_validate.add_argument(
        "--perfiles",
        default=DEFAULT_PROFILES,
        metavar="FICHERO",
        help="perfiles clínicos en TOML (por defecto: %(default)s)",
    )
    profiles_validate.add_argument(
        "--llegadas",
        default=DEFAULT_CONFIG,
        metavar="FICHERO",
        help="perfil de llegadas en TOML, para la fecha de inicio y el peso de cada contexto "
        "(por defecto: %(default)s)",
    )
    profiles_validate.add_argument(
        "--pacientes",
        type=int,
        default=None,
        metavar="N",
        help="pacientes de cada muestra: N por contexto en la mezcla (24 × N en total) y N "
        "en la muestra del año del triaje, las pruebas y las duraciones (por defecto, "
        f"{DEFAULT_MIXING_PATIENTS} por contexto y un año del perfil de llegadas)",
    )
    _add_output_options(profiles_validate)
    profiles_validate.set_defaults(
        handler=_validate_profiles, subparser=profiles_validate, salida="resultados/perfiles"
    )

    calibration = commands.add_parser(
        "calibracion",
        help="calibración del centro base: evaluación y sensibilidad",
        description="Calibración del centro base contra los objetivos de config/objetivos.toml "
        "(hito 4).",
    )
    calibration_actions = calibration.add_subparsers(dest="accion", required=True, metavar="accion")
    evaluate = calibration_actions.add_parser(
        "evaluar",
        help="compara el centro con los objetivos en varias réplicas",
        description="Simula R réplicas del modelo clínico con números aleatorios comunes (un "
        "día de vaciado después de la ventana; con la ventana anual, una réplica por mes) y "
        "compara cada objetivo con su horquilla: "
        "media entre réplicas, IC al 95 % con la t de Student, porcentaje de días fuera y "
        "resultado (pasa si la media cae dentro y el IC no es más ancho que la horquilla). "
        "Informa también el valor de cada réplica y la media por paciente de todas, que no "
        "decide. "
        f"Guarda {EVALUATION_CSV}, {REPLICAS_CSV} y {LEVELS_CSV}. Termina con código 1 si "
        "falla algún objetivo de ajuste; los de comprobación se informan.",
    )
    _add_calibration_options(evaluate)
    evaluate.set_defaults(handler=_evaluate_calibration, subparser=evaluate)

    sensitivity_parser = calibration_actions.add_parser(
        "sensibilidad",
        help="evalúa las plantillas de la regla para un mando",
        description="Evalúa todos los objetivos con cada plantilla distinta que da la regla de "
        "la plantilla equivalente (⌈carga del turno / u⌉) para un mando, con el otro mando "
        "como en el centro, e indica la elección (la más cercana a la referencia entre las "
        "que pasan; con --comprobacion, la primera que pasa también con esa semilla) y, para "
        "los médicos, el centro cumplidor. Guarda "
        f"{SENSITIVITY_CSV.format(knob='<mando>')}. Termina con código 1 si ninguna plantilla "
        "pasa los objetivos del mando.",
    )
    sensitivity_parser.add_argument(
        "--mando",
        required=True,
        choices=KNOBS,
        help="mando que se mueve: enfermeria_triaje o medicos",
    )
    sensitivity_parser.add_argument(
        "--comprobacion",
        type=int,
        default=None,
        metavar="SEMILLA",
        help="semilla de comprobación, que puede vetar la elección y no elegir (decisión 41): "
        "las candidatas que pasan con la semilla de ajuste se evalúan con esta, con la misma "
        "ventana y el resto de opciones, en el orden de la elección y solo hasta la primera "
        "que pasa; la elegida es esa (sin la opción, la elección es la de la semilla de ajuste)",
    )
    sensitivity_parser.add_argument(
        "--u-min",
        type=float,
        default=U_MIN,
        metavar="U",
        help="u más bajo de la rejilla (por defecto: %(default)s)",
    )
    sensitivity_parser.add_argument(
        "--u-max",
        type=float,
        default=U_MAX,
        metavar="U",
        help="u más alto de la rejilla (por defecto: %(default)s)",
    )
    sensitivity_parser.add_argument(
        "--paso",
        type=float,
        default=U_STEP,
        metavar="P",
        help="paso de la rejilla de u (por defecto: %(default)s)",
    )
    _add_calibration_options(sensitivity_parser)
    sensitivity_parser.set_defaults(handler=_calibration_sensitivity, subparser=sensitivity_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code; the ``edsim`` script exits with it."""
    args = build_parser().parse_args(argv)
    return args.handler(args, args.subparser)
