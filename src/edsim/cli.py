"""Command-line interface of EDsim.

Options are in Spanish, as in the design; the code behind them is in English.
The CLI is a thin layer: it parses arguments, runs the package (``compare_mm1``,
``simulate_arrivals``, ``validate_arrivals``, ``simulate_run``,
``validate_engine``, ``validate_profiles``, ``simulate_replicas``,
``sensitivity``, and ``edsim.live`` for ``directo``) and hands the results to the
report modules for the tables, the CSV files, the plots and the lines of a live run.

Exit codes: 0 if all goes well; 1 if ``llegadas validar``, ``motor validar``
or ``perfiles validar`` runs and some check fails, ``motor simular`` finds a
broken invariant, ``calibracion evaluar`` finds a fit target out of its band or
``calibracion sensibilidad`` finds no staffing that passes the targets of its
knob (the files are written anyway, to find out why); 2 for usage
errors, including a missing or invalid configuration, invalid limits or a
``--salida`` that is not a directory, before anything is printed or computed
and before any file is created.

``directo`` (docs/specs/hito-6.md, "Precisiones para la 6.5"): 0 if the run ends
by its horizon or by an order ``parar``, and if ``preparar`` or ``control`` do
their job; 130 with Ctrl+C, after publishing the end; 1 if a message is not
delivered, the topics are missing or differ, the broker does not answer or the
``kafka`` extra is missing; 2 for usage errors, before connecting to Kafka.
"""

import argparse
import sys
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
    ALL_KNOBS,
    DRAIN_DAYS,
    FIT_SEED,
    check_knob_model,
    check_knob_targets,
    check_targets_apply,
    choose_staffing,
    compliant_staffing,
    evaluate_staffings,
    knob_settings,
    sensitivity,
    simulate_replicas,
    split_targets,
    summarize_targets,
)
from edsim.calibration.knobs import BED_WAIT, DEFAULT_GRIDS
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
from edsim.engine.clinical_sampler import ModelChoiceError, PatientModel, choose_model
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
from edsim.live.clock import SystemClock
from edsim.live.control import (
    MAX_SPEED,
    PAUSE,
    RESUME,
    SPEED,
    STOP,
    Command,
    NoControl,
    check_speed,
)
from edsim.live.directo import MemoryLiveSink, SinkError
from edsim.live.kafka import (
    ADMIN_CLIENT,
    CONNECT_TIMEOUT,
    MISSING_EXTRA_MESSAGE,
    BrokerUnavailableError,
    BrokerWatch,
    KafkaControl,
    KafkaSink,
    MissingKafkaExtraError,
    MissingTopicsError,
    OrderNotDeliveredError,
    TopicMismatchError,
    connect_producer,
    ensure_topics,
    pending_messages,
    publish_order,
)
from edsim.live.launch import PreparedRun, live_run_id, prepare_live, prepare_replay, run_prepared
from edsim.live.report import format_census, format_end, format_speed, format_status
from edsim.live.topics import TOPICS
from edsim.profiles.config import load_profiles
from edsim.profiles.report import FALSE_ALARM, PLOTS, format_profiles_validation
from edsim.profiles.validation import (
    DEFAULT_MIXING_PATIENTS,
    PATIENCE_YEARS,
    check_profiles_validation_counts,
    validate_profiles,
    year_patients,
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

DEFAULT_BOOTSTRAP = "localhost:9092"
DEFAULT_SPEED = 60.0
DEFAULT_RUNS = "resultados/ejecuciones"


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
    """Stop with a usage error (code 2) if the provisional model gets a center without its
    block, or one with ``[camas]`` instead of ``[destino]`` (``choose_model``)."""
    if not center.has_provisional:
        parser.error(
            f"--centro {args.centro}: el modelo provisional necesita las tablas [triaje], "
            "[duraciones] y [pruebas] del centro, y este no las tiene; su centro es "
            f"{DEFAULT_PROVISIONAL_CENTER}"
        )
    # A center with [camas] is of milestone 5, even with the provisional tables (task 5.3).
    try:
        choose_model(center, None, center_file=args.centro)
    except ModelChoiceError as error:
        parser.error(str(error))


def _model_line(args: argparse.Namespace) -> str:
    if args.perfiles is None:
        return "Modelo provisional"
    # motor simular sets the model; the live mode refuses milestone 5 before this line.
    if getattr(args, "modelo", None) is PatientModel.MILESTONE_5:
        return (
            "Modelo del hito 5 (abandono, destinos y espera de cama) · perfiles "
            f"{args.perfiles} (huella {args.huella_perfiles})"
        )
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
        profiles, args.huella_perfiles = _load_file(
            args.perfiles, "--perfiles", load_profiles, parser
        )
        # The blocks of the two files choose milestone 4 or 5 (decision 68); a block of
        # milestone 5 in only one of them is code 2, before writing anything.
        try:
            args.modelo = choose_model(
                center, profiles, center_file=args.centro, profiles_file=args.perfiles
            )
        except ModelChoiceError as error:
            parser.error(str(error))
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
    print(format_run_summary(result.analysis, result.violations, result.outcome))
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
        + (
            f"{PATIENCE_YEARS * year_patients(profiles, arrival_profile)} pacientes en la"
            f" paciencia y {year_patients(profiles, arrival_profile)} en los destinos"
            f" ({PATIENCE_YEARS} años y uno; --pacientes no los cambia)\n\n"
            "Validando el muestreador: mezcla de motivos, triaje, pruebas, duraciones,"
            " paciencia y destinos (bloque del hito 5). Con los valores por defecto tarda"
            " unos 90 segundos.\n"
            if profiles.outcome is not None
            else "Validando el muestreador: mezcla de motivos, triaje, pruebas y duraciones."
            " Con los valores por defecto tarda unos 30 segundos.\n"
        ),
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


def _split_targets(args: argparse.Namespace, parser: argparse.ArgumentParser, *loaded):
    """The targets that apply to the model of the two files, and those that do not (task
    5.6); a block of milestone 5 in only one of them is code 2, before simulating."""
    center, _, profiles, targets = loaded
    try:
        choose_model(center, profiles, center_file=args.centro, profiles_file=args.perfiles)
    except ModelChoiceError as error:
        parser.error(str(error))
    applicable, not_applicable = split_targets(targets, center, profiles)
    try:
        check_targets_apply(applicable, center, profiles)
    except ValueError as error:
        parser.error(str(error))
    return applicable, not_applicable


def _evaluate_calibration(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    center, profile, profiles, targets = loaded = _load_calibration(args, parser)
    targets, not_applicable = _split_targets(args, parser, *loaded)
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
    print(
        format_evaluation(
            results,
            replicas,
            args.fechas_replicas,
            annual=args.ventana == ANNUAL,
            not_applicable=not_applicable,
        )
    )

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


def _knob_grid_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict:
    """The options of the candidates of the knob: the grid of u for a knob of staff, the
    values for one of one number; the others are a usage error."""
    u_options = {"--u-min": args.u_min, "--u-max": args.u_max, "--paso": args.paso}
    if args.mando in KNOBS:
        if args.valores is not None:
            parser.error(f"--valores es de espera_cama y paciencia, no de {args.mando}")
        options = {
            "u_min": U_MIN if args.u_min is None else args.u_min,
            "u_max": U_MAX if args.u_max is None else args.u_max,
            "step": U_STEP if args.paso is None else args.paso,
        }
        try:
            u_grid(options["u_min"], options["u_max"], options["step"])
        except ValueError as error:
            parser.error(str(error))
        return options
    given = [name for name, value in u_options.items() if value is not None]
    if given:
        parser.error(
            f"{', '.join(given)}: la rejilla de u es de los mandos de plantilla; con"
            f" {args.mando}, --valores"
        )
    return {"values": args.valores}


def _candidates_text(args: argparse.Namespace, options: dict) -> str:
    if args.mando in KNOBS:
        return (
            f"con u de {options['u_min']:g} a {options['u_max']:g} en pasos de"
            f" {options['step']:g}; el otro mando, como en el centro"
        )
    grid = DEFAULT_GRIDS[args.mando] if options["values"] is None else options["values"]
    what = (
        "mediana de la espera de cama (min; p90 = 3 · mediana)"
        if args.mando == BED_WAIT
        else "factor de la paciencia sobre los perfiles"
    )
    return f"({what}) en {', '.join(f'{v:g}' for v in grid)}; el resto, como en los ficheros"


def _calibration_sensitivity(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    out_dir = _output_dir(args, parser)
    center, profile, profiles, targets = loaded = _load_calibration(args, parser)
    targets, not_applicable = _split_targets(args, parser, *loaded)
    try:
        # The model first: with milestone 4, the fit target of a knob of milestone 5 is
        # left out as not applicable, and its absence (or a grid option of a knob of
        # staff) would hide the cause.
        check_knob_model(args.mando, center, profiles)
    except ValueError as error:
        parser.error(str(error))
    options = _knob_grid_options(args, parser)
    try:
        check_knob_targets(targets, args.mando)
        knob_settings(args.mando, center, profiles, profile, **options)
    except ValueError as error:
        parser.error(str(error))
    if args.comprobacion == args.semilla:
        parser.error(
            f"la semilla de comprobación ({args.comprobacion}) tiene que ser distinta de la de"
            f" ajuste ({args.semilla}) (regla 3)"
        )
    outcome = choose_model(center, profiles) is PatientModel.MILESTONE_5
    check_text = (
        ""
        if args.comprobacion is None
        else f"; comprobación con la semilla {args.comprobacion}, que puede vetar la elección"
    )
    absent = (
        f"\nNo aplican (el modelo no tiene el bloque del hito 5): "
        f"{', '.join(t.name for t in not_applicable)}"
        if not_applicable
        else ""
    )
    print(
        f"{_calibration_header(args)}\nSensibilidad del mando {args.mando}"
        f" {_candidates_text(args, options)}{check_text}{absent}\n\n"
        f"{sensitivity_header(targets, args.mando, outcome=outcome)}",
        flush=True,
    )
    common = {
        "replicas": args.replicas,
        "days": args.dias,
        "warmup_days": args.calentamiento,
        "start_dates": args.fechas,
    }
    rows = sensitivity(
        center,
        profile,
        profiles,
        targets,
        args.mando,
        seed=args.semilla,
        on_row=lambda row: print(
            format_sensitivity_row(row, args.mando, outcome=outcome), flush=True
        ),
        **options,
        **common,
    )
    if args.comprobacion is None:
        chosen = choose_staffing(rows, args.mando)
        seeds = None
    else:
        checked = []

        def check(row):
            # The same candidate with the check seed, the same window and the rest of the
            # options; asked only for the candidates the choice needs, in its order.
            (row_checked,) = evaluate_staffings(
                center,
                profile,
                profiles,
                targets,
                args.mando,
                [row.setting],
                seed=args.comprobacion,
                **common,
            )
            checked.append(row_checked)
            return row_checked

        chosen = choose_staffing(rows, args.mando, check=check)
        seeds = (args.semilla, args.comprobacion)
        print(f"\n{format_check(args.mando, args.comprobacion, checked)}")
    compliant = compliant_staffing(rows) if args.mando == DOCTORS else None
    print(f"\n{format_choice(args.mando, chosen, compliant, seeds=seeds, rows=rows)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SENSITIVITY_CSV.format(knob=args.mando)
    write_sensitivity_csv(rows, args.mando, chosen, compliant, path, _calibration_parameters(args))
    print(f"\nCSV: {path}")
    return 0 if chosen is not None else 1


# --- edsim directo -------------------------------------------------------------------


def parse_values(text: str) -> tuple[float, ...]:
    """The values of ``--valores``: numbers separated by commas."""
    try:
        values = tuple(float(x) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"«{text}» no son números separados por comas, como 120,135,150"
        ) from None
    return values


def parse_speed(text: str) -> float | str:
    """A speed of the live run: ``max`` or a positive, finite number."""
    if text == MAX_SPEED:
        return MAX_SPEED
    try:
        return check_speed(float(text))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"la velocidad debe ser un número positivo o «max»; se recibió «{text}»"
        ) from None


def parse_bootstrap(text: str) -> str:
    """The address of the broker, ``HOST:PUERTO``."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError(f"«{text}» no es HOST:PUERTO, como {DEFAULT_BOOTSTRAP}")
    return text


KAFKA_ERRORS = (
    MissingKafkaExtraError,
    BrokerUnavailableError,
    MissingTopicsError,
    TopicMismatchError,
    TimeoutError,
    SinkError,
    OrderNotDeliveredError,
)
"""What ends a ``directo`` command with code 1: the extra, the broker, the topics or a
message that was not delivered."""


def _kafka_failure(error: Exception, bootstrap: str) -> int:
    """Print what went wrong with Kafka, in Spanish, and return code 1."""
    if isinstance(error, MissingKafkaExtraError):
        text = MISSING_EXTRA_MESSAGE
    elif isinstance(error, BrokerUnavailableError):
        text = (
            f"Error: no responde el broker de Kafka en {error.bootstrap} en {error.timeout:g} s:"
            " ¿está levantado? docker compose up --wait"
        )
    elif isinstance(error, MissingTopicsError):
        text = (
            f"Error: faltan topics en {bootstrap}; créalos con «edsim directo preparar» ({error})"
        )
    elif isinstance(error, TopicMismatchError):
        text = f"Error: los topics de {bootstrap} no son los de EDsim ({error})"
    elif isinstance(error, SinkError):
        text = f"Error: un mensaje no se entregó y el directo se paró ({error})"
    else:
        text = f"Error: {error}"
    print(text, file=sys.stderr, flush=True)
    return 1


def _warn(reason: str) -> None:
    print(f"Aviso: {reason}", file=sys.stderr, flush=True)


def _broker_watch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> BrokerWatch:
    """The watch of the Kafka clients of a command, with the file of ``--registro-kafka``."""
    log_path = getattr(args, "registro_kafka", None)
    try:
        return BrokerWatch(args.kafka, _warn, log_path=log_path)
    except OSError as error:
        parser.error(f"--registro-kafka {log_path}: {error}")


def _kafka_summary(watch: BrokerWatch | None) -> None:
    """Print what librdkafka wrote, if anything, and close the file of the lines."""
    if watch is None:
        return
    text = watch.summary()
    if text is not None:
        print(text, file=sys.stderr, flush=True)
    watch.close()


def _destination(args: argparse.Namespace) -> str:
    return "en memoria" if args.memoria else f"Kafka {args.kafka}"


def _run_live_command(
    args: argparse.Namespace, prepared: PreparedRun, clock, watch: BrokerWatch | None
) -> int:
    """Publish a prepared run in memory or in Kafka, printing the census, the status and
    the summary; the exit code. With Kafka, ``watch`` gets what librdkafka says, and what
    it wrote is summed up at the end, also after Ctrl+C or an error."""
    callbacks = {
        "on_start": lambda start: print(format_census(start), flush=True),
        "on_end": lambda start, end: print(format_end(start, end), flush=True),
        "on_status": lambda status: print(format_status(status), flush=True),
    }
    run_id = prepared.info.run_id
    try:
        if args.memoria:
            run_prepared(
                prepared,
                clock=clock,
                speed=args.velocidad,
                control=NoControl(),
                sink=MemoryLiveSink(),
                **callbacks,
            )
            return 0
        # Only check: creating is for `edsim directo preparar`.
        ensure_topics(
            args.kafka,
            TOPICS,
            create=False,
            connect_timeout=CONNECT_TIMEOUT,
            client_config=watch.config(ADMIN_CLIENT),
        )
        # Before the warm-up: the orders sent meanwhile apply when the live stream starts.
        control = KafkaControl(args.kafka, run_id, _warn, watch=watch)
        try:
            producer = connect_producer(args.kafka, run_id, watch=watch)
            with KafkaSink(producer, run_id) as sink:
                run_prepared(
                    prepared,
                    clock=clock,
                    speed=args.velocidad,
                    control=control,
                    sink=sink,
                    pending=lambda: pending_messages(producer),
                    **callbacks,
                )
        finally:
            control.close()
        return 0
    except KeyboardInterrupt:
        print("Interrumpido con Ctrl+C", file=sys.stderr, flush=True)
        return 130
    except KAFKA_ERRORS as error:
        return _kafka_failure(error, args.kafka)
    finally:
        _kafka_summary(watch)


def _check_kafka_log(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.memoria and args.registro_kafka is not None:
        parser.error("--registro-kafka guarda lo que escribe librdkafka: no vale con --memoria")


def _launch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _check_kafka_log(args, parser)
    if args.semilla < 0:
        parser.error(f"--semilla debe ser un entero no negativo; se recibió {args.semilla}")
    clock = SystemClock()
    wall = clock.wall()
    run_id = args.run_id
    if run_id is None:
        try:
            run_id = live_run_id(args.semilla, wall)
        except ValueError as error:
            parser.error(f"--run-id: {error}; indica un --run-id explícito válido")
    center, profile = _load_engine_configs(args, parser)
    profiles = None
    if args.provisional:
        _check_provisional_center(center, args, parser)
    else:
        if args.perfiles is None:
            args.perfiles = DEFAULT_PROFILES
        profiles, args.huella_perfiles = _load_file(
            args.perfiles, "--perfiles", load_profiles, parser
        )
    try:
        prepared = prepare_live(
            center,
            profile,
            args.dias,
            args.semilla,
            warmup_days=args.calentamiento,
            run_id=run_id,
            profiles=profiles,
            anchor_wall=wall if args.anclar else None,
        )
    except ValueError as error:
        parser.error(str(error))
    watch = None if args.memoria else _broker_watch(args, parser)
    anchored = ", anclado al calendario" if args.anclar else ""
    print(
        f"Directo · run_id {run_id} · velocidad {format_speed(args.velocidad)}"
        f" · {_destination(args)}\n{_engine_header(args)}\n{_model_line(args)}"
        f"\n{args.dias} días desde {prepared.info.start_date.isoformat()}"
        f" ({args.calentamiento} de calentamiento{anchored}) · W = {prepared.start:g} min"
        f" · horizonte {prepared.horizon:g} min · semilla {args.semilla}",
        flush=True,
    )
    return _run_live_command(args, prepared, clock, watch)


def _replay(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    _check_kafka_log(args, parser)
    try:
        prepared = prepare_replay(args.ejecuciones, args.run_id, warmup_days=args.calentamiento)
    except (OSError, ValueError) as error:
        parser.error(f"{args.run_id} en {args.ejecuciones}: {error}")
    watch = None if args.memoria else _broker_watch(args, parser)
    info = prepared.info
    print(
        f"Replay · run_id {info.run_id} · velocidad {format_speed(args.velocidad)}"
        f" · {_destination(args)}\nEjecución {Path(args.ejecuciones) / info.run_id}"
        f" · catálogo {info.schema_version} · semilla {info.seed}"
        f"\n{prepared.horizon / 1440:g} días desde {info.start_date.isoformat()} (la fecha del"
        f" primer evento) · W = {prepared.start:g} min · horizonte {prepared.horizon:g} min",
        flush=True,
    )
    return _run_live_command(args, prepared, SystemClock(), watch)


def _prepare_topics(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    watch = _broker_watch(args, parser)
    try:
        report = ensure_topics(
            args.kafka,
            TOPICS,
            connect_timeout=CONNECT_TIMEOUT,
            client_config=watch.config(ADMIN_CLIENT),
        )
    except KAFKA_ERRORS as error:
        return _kafka_failure(error, args.kafka)
    finally:
        _kafka_summary(watch)
    print(
        f"Kafka {args.kafka}\nCreados: {', '.join(report.created) or 'ninguno'}"
        f"\nYa estaban: {', '.join(report.existing) or 'ninguno'}"
    )
    return 0


def _control(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.velocidad is not None:
        command = Command(SPEED, args.velocidad)
        text = f"velocidad {format_speed(args.velocidad)}"
    else:
        order = PAUSE if args.pausar else RESUME if args.reanudar else STOP
        command = Command(order)
        text = order
    watch = _broker_watch(args, parser)
    try:
        producer = connect_producer(args.kafka, f"orden-{args.run}", watch=watch)
        try:
            offset = publish_order(
                producer, args.run, command, bootstrap=args.kafka, connect_timeout=CONNECT_TIMEOUT
            )
        finally:
            producer.poll(0)  # serve its logs and errors to the watch
    except KAFKA_ERRORS as error:
        return _kafka_failure(error, args.kafka)
    finally:
        _kafka_summary(watch)
    print(f"Orden {text} para {args.run} publicada en ed.control (offset {offset})")
    return 0


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


def _add_bootstrap_option(parser: argparse.ArgumentParser) -> argparse.Action:
    return parser.add_argument(
        "--kafka",
        type=parse_bootstrap,
        default=DEFAULT_BOOTSTRAP,
        metavar="HOST:PUERTO",
        help="dirección del broker de Kafka (por defecto: %(default)s)",
    )


def _add_kafka_log_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registro-kafka",
        default=None,
        metavar="FICHERO",
        help="guarda en FICHERO, con su hora, todas las líneas que escribe librdkafka; sin "
        "esta opción no van a la terminal y al final se imprime su recuento",
    )


def _add_live_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--velocidad",
        type=parse_speed,
        default=DEFAULT_SPEED,
        metavar="V",
        help="minutos simulados por minuto real, un número positivo, o max, sin esperas "
        "(por defecto: %(default)g)",
    )
    target = parser.add_mutually_exclusive_group()
    _add_bootstrap_option(target)
    target.add_argument(
        "--memoria",
        action="store_true",
        help="sin Kafka ni órdenes: publica en memoria e imprime el resumen",
    )
    _add_kafka_log_option(parser)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``edsim`` parser: ``mm1``, ``llegadas``, ``motor``, ``perfiles``,
    ``calibracion`` and ``directo``."""
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
        help="evalúa los candidatos de un mando: plantillas de la regla o valores",
        description="Evalúa todos los objetivos con cada candidato de un mando, con el resto "
        "como en el centro y los perfiles: para enfermeria_triaje y medicos, cada plantilla "
        "distinta que da la regla de la plantilla equivalente (⌈carga del turno / u⌉); para "
        "espera_cama (la mediana de [camas] espera, con p90 = 3 · mediana) y paciencia (un "
        "factor común sobre las medianas y los p90 de [abandono] paciencia), los valores de "
        "su rejilla (hito 5, tarea 5.6). Indica la elección (la más cercana a la referencia "
        "entre los que pasan; con --comprobacion, el primero que pasa también con esa "
        "semilla) y, para los médicos, el centro cumplidor. Guarda "
        f"{SENSITIVITY_CSV.format(knob='<mando>')}. Termina con código 1 si ningún candidato "
        "pasa los objetivos del mando.",
    )
    sensitivity_parser.add_argument(
        "--mando",
        required=True,
        choices=ALL_KNOBS,
        help="mando que se mueve: enfermeria_triaje, medicos, espera_cama o paciencia (los dos"
        " últimos, solo con el modelo del hito 5)",
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
        default=None,
        metavar="U",
        help=f"u más bajo de la rejilla, solo con los mandos de plantilla (por defecto: {U_MIN})",
    )
    sensitivity_parser.add_argument(
        "--u-max",
        type=float,
        default=None,
        metavar="U",
        help=f"u más alto de la rejilla, solo con los mandos de plantilla (por defecto: {U_MAX})",
    )
    sensitivity_parser.add_argument(
        "--paso",
        type=float,
        default=None,
        metavar="P",
        help=f"paso de la rejilla de u, solo con los mandos de plantilla (por defecto: {U_STEP})",
    )
    sensitivity_parser.add_argument(
        "--valores",
        type=parse_values,
        default=None,
        metavar="V1,V2,…",
        help="valores de espera_cama (mediana, en minutos) o de paciencia (factor), separados"
        " por comas (por defecto, su rejilla: espera_cama de 120 a 360 de 15 en 15; paciencia"
        " geométrica de 1 a 8, 2^(i/4))",
    )
    _add_calibration_options(sensitivity_parser)
    sensitivity_parser.set_defaults(handler=_calibration_sensitivity, subparser=sensitivity_parser)

    live = commands.add_parser(
        "directo",
        help="directo: los eventos en vivo, en Kafka o en memoria",
        description="El modo directo del hito 6: calienta sin emitir, publica el censo y "
        "después cada evento cuando le toca, al ritmo de --velocidad (docs/specs/hito-6.md).",
    )
    live_actions = live.add_subparsers(dest="accion", required=True, metavar="accion")

    prepare = live_actions.add_parser(
        "preparar",
        help="crea los topics que falten y comprueba los que existen",
        description="Crea en Kafka los cuatro topics del directo que falten (ed.patient.events, "
        "ed.resource.events, ed.runs y ed.control) y comprueba los que existen: particiones y "
        "marca de tiempo del broker. Termina con código 1 si alguno difiere o el broker no "
        "responde.",
    )
    _add_bootstrap_option(prepare)
    prepare.set_defaults(handler=_prepare_topics, subparser=prepare)

    launch = live_actions.add_parser(
        "lanzar",
        help="lanza un directo del motor",
        description="Calienta el motor hasta W sin emitir, publica el inicio en ed.runs y el "
        "censo, y después cada evento cuando le toca, hasta el horizonte, una orden parar o "
        "Ctrl+C (código 130, tras publicar el fin). Las opciones del modelo son las de motor "
        "simular, con el modelo clínico por defecto. Comprueba los topics sin crearlos (eso es "
        "de preparar). Cada 10 s reales imprime una línea de estado. No guarda una ejecución en "
        "resultados/: su batch es motor simular con el mismo --run-id.",
    )
    _add_engine_options(launch)
    launch_model = launch.add_mutually_exclusive_group()
    launch_model.add_argument(
        "--perfiles",
        default=None,
        metavar="FICHERO",
        help=f"perfiles clínicos en TOML (por defecto: {DEFAULT_PROFILES})",
    )
    launch_model.add_argument(
        "--provisional",
        action="store_true",
        help="el modelo provisional del hito 3 (catálogo 1); necesita un --centro con su "
        f"bloque provisional, como {DEFAULT_PROVISIONAL_CENTER}",
    )
    launch.add_argument(
        "--semilla",
        type=int,
        default=2026,
        metavar="N",
        help="semilla maestra (por defecto: %(default)s)",
    )
    launch.add_argument(
        "--dias",
        type=int,
        default=14,
        metavar="N",
        help="días completos, con el calentamiento: el horizonte (por defecto: %(default)s)",
    )
    launch.add_argument(
        "--calentamiento",
        type=int,
        default=2,
        metavar="N",
        help="días completos de calentamiento, sin emitir; con --anclar, días antes de hoy "
        "(por defecto: %(default)s)",
    )
    launch.add_argument(
        "--run-id",
        type=validate_run_id,
        default=None,
        metavar="ID",
        help="identificador de la ejecución (por defecto: r, la semilla, _ y la hora de "
        "arranque en +01:00, como r2026_20261106T172300)",
    )
    launch.add_argument(
        "--anclar",
        action="store_true",
        help="ancla al calendario: empieza --calentamiento días antes de hoy a las 0:00 y "
        "calienta hasta ahora (en +01:00), en vez de la fecha_inicio de --llegadas",
    )
    _add_live_options(launch)
    launch.set_defaults(handler=_launch, subparser=launch)

    replay = live_actions.add_parser(
        "reemitir",
        help="reemite una ejecución guardada",
        description="Reemite con el mismo pacer, censo y productor una ejecución guardada por "
        "motor simular: el horizonte, el calentamiento y la semilla de su run.json, la fecha de "
        "su primer evento y sus mismos run_id y event_id (los mismos bytes).",
    )
    replay.add_argument("run_id", metavar="RUN_ID", help="la ejecución que se reemite")
    replay.add_argument(
        "--calentamiento",
        type=int,
        default=None,
        metavar="N",
        help="días antes de W (por defecto: los de la ejecución)",
    )
    replay.add_argument(
        "--ejecuciones",
        default=DEFAULT_RUNS,
        metavar="DIR",
        help="carpeta de las ejecuciones guardadas (por defecto: %(default)s)",
    )
    _add_live_options(replay)
    replay.set_defaults(handler=_replay, subparser=replay)

    control = live_actions.add_parser(
        "control",
        help="manda una orden a un directo en marcha",
        description="Publica una orden en ed.control para el directo --run y espera su "
        "confirmación: cambiar la velocidad, pausar, reanudar o parar. El directo la atiende en "
        "menos de 0,2 s. Termina con código 1 si la orden no se entrega.",
    )
    control.add_argument(
        "--run", required=True, type=validate_run_id, metavar="RUN_ID", help="el directo"
    )
    order = control.add_mutually_exclusive_group(required=True)
    order.add_argument(
        "--velocidad",
        type=parse_speed,
        default=None,
        metavar="V",
        help="nueva velocidad: un número positivo o max",
    )
    order.add_argument("--pausar", action="store_true", help="congela el reloj simulado")
    order.add_argument("--reanudar", action="store_true", help="sigue desde donde se pausó")
    order.add_argument("--parar", action="store_true", help="termina el directo (fin parar)")
    _add_bootstrap_option(control)
    _add_kafka_log_option(control)
    control.set_defaults(handler=_control, subparser=control)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code; the ``edsim`` script exits with it."""
    args = build_parser().parse_args(argv)
    return args.handler(args, args.subparser)
