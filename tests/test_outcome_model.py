"""El modelo del hito 5 en el motor (tarea 5.3), con los ficheros de ejemplo del hito 5.

``perfiles_h5_ejemplo.toml`` y ``centro_h5_ejemplo.toml`` eligen el modelo del hito 5
(decisión 68): ``child_streams(seed, 10)``, con los hijos 0 a 7 del hito 4 bit a bit y el
desenlace de los flujos 4 (destino), 8 (paciencia) y 9 (espera de cama). Los valores
esperados salen de generadores propios del test, no del muestreador.
"""

import dataclasses
import hashlib
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from clinical_factory import PLAIN, leaves, truth_lines

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import iter_arrivals
from edsim.engine.center import load_center
from edsim.engine.clinical_sampler import ClinicalSampler, PatientModel
from edsim.engine.engine import simulate_ed
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, JsonlSink, MemorySink
from edsim.engine.invariants import check_invariants
from edsim.engine.report import (
    CLINICAL_EPISODE_COLUMNS,
    OUTCOME_COLUMNS,
    OUTCOME_EPISODE_COLUMNS,
    ProfilesParameters,
    RunParameters,
    read_episodes_csv,
    write_episodes_csv,
)
from edsim.profiles.config import load_profiles
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
SEED = 2026
DAYS = 3
Z90 = 1.2815515655446004
"""El cuantil 0,9 de la normal estándar, escrito: no se calcula con el código probado."""


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_h5_ejemplo.toml")


@pytest.fixture(scope="module")
def arrival_profile():
    return load_profile(DATA / "llegadas_ejemplo.toml")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_h5_ejemplo.toml")


def sampled(center, arrival_profile, profiles, seed=SEED, days=DAYS):
    """Los sorteos de cada paciente, con las llegadas y los flujos de una ejecución."""
    streams = child_streams(seed, 10)
    sampler = ClinicalSampler(profiles, arrival_profile.start_date, center, streams[1:])
    return [sampler(a) for a in iter_arrivals(arrival_profile, days, streams[0])]


@pytest.fixture(scope="module")
def draws(center, arrival_profile, profiles):
    return sampled(center, arrival_profile, profiles)


# --- Los flujos del desenlace ----------------------------------------------------------------


def test_el_muestreador_es_del_hito_5(center, arrival_profile, profiles, draws):
    sampler = ClinicalSampler(
        profiles, arrival_profile.start_date, center, child_streams(SEED, 10)[1:]
    )
    assert sampler.model is PatientModel.MILESTONE_5
    assert len(draws) > 1000
    assert all(d.outcome is not None and d.outcome.truth is not None for d in draws)


def test_las_gumbel_son_las_del_hijo_4_cuatro_por_paciente(draws):
    # Un generador propio del hijo 4: las 4 Gumbel de cada paciente, en orden de llegada,
    # del primero al último. El flujo 4 es del OutcomeSampler y de nadie más.
    expected = np.random.default_rng(child_streams(SEED, 10)[4]).gumbel(size=(len(draws), 4))
    drawn = [d.outcome.truth.destination_draws for d in draws]

    assert drawn == [tuple(row) for row in expected.tolist()]


def test_las_normales_son_las_de_los_hijos_8_y_9(draws):
    n = len(draws)
    patience = np.random.default_rng(child_streams(SEED, 10)[8]).standard_normal(n)
    bed = np.random.default_rng(child_streams(SEED, 10)[9]).standard_normal(n)

    assert [d.outcome.truth.patience_z for d in draws] == patience.tolist()
    assert [d.outcome.truth.bed_z for d in draws] == bed.tolist()


def test_el_motor_lee_lo_sorteado(draws):
    # Lo que lee el motor es lo sorteado, y admitted solo acompaña al destino.
    for d in draws:
        truth = d.outcome.truth
        assert (d.outcome.patience, d.outcome.destination, d.outcome.bed_base) == (
            truth.patience,
            truth.destination,
            truth.bed_base,
        )
        assert d.admitted == (truth.destination == "ingreso")
    destinations = {d.outcome.destination for d in draws}
    assert destinations == {"alta", "ingreso", "traslado", "exitus"}


def test_cada_hijo_se_convierte_en_generador_una_sola_vez(
    center, arrival_profile, profiles, monkeypatch
):
    # Dos default_rng del mismo SeedSequence dan los mismos números: si el muestreador
    # clínico creara también su generador del hijo 4, las Gumbel no cambiarían y ninguna
    # huella lo vería. Se espía cada conversión de un SeedSequence en generador.
    streams = child_streams(SEED, 10)
    seen = []
    original = np.random.default_rng

    def spy(seed=None):
        seen.append(seed)
        return original(seed)

    monkeypatch.setattr(np.random, "default_rng", spy)
    ClinicalSampler(profiles, arrival_profile.start_date, center, streams[1:])

    counts = [sum(s is stream for s in seen) for stream in streams]
    assert counts == [0] + [1] * 9


def test_en_el_hito_4_el_hijo_4_tambien_tiene_un_solo_generador(arrival_profile, monkeypatch):
    # La guarda del espía: con el hito 4 el muestreador sí crea el generador del hijo 4
    # (la uniforme del destino provisional), una vez.
    streams = child_streams(SEED, 8)
    seen = []
    original = np.random.default_rng
    monkeypatch.setattr(
        np.random, "default_rng", lambda seed=None: seen.append(seed) or original(seed)
    )
    ClinicalSampler(
        load_profiles(DATA / "perfiles_ejemplo.toml"),
        arrival_profile.start_date,
        load_center(DATA / "centro_sala_ejemplo.toml"),
        streams[1:],
    )

    assert [sum(s is stream for s in seen) for stream in streams] == [0] + [1] * 7


@pytest.mark.parametrize("n", [7, 8, 10])
def test_el_hito_5_necesita_nueve_flujos(center, arrival_profile, profiles, n):
    with pytest.raises(ValueError, match="must have 9 SeedSequence with the milestone 5 model"):
        ClinicalSampler(
            profiles, arrival_profile.start_date, center, child_streams(SEED, n + 1)[1:]
        )


# --- La espera de cama sale del centro ------------------------------------------------------


def test_la_espera_base_es_la_lognormal_de_camas(draws):
    # [240, 720]: σ = ln(720/240) / z90 = 1,0986123 / 1,2815516. 1,2815516 × 0,857 =
    # 1,0982897; el resto, 0,0003226 / 1,2815516 = 0,0002517: σ = 0,8572517 (la
    # especificación da 0,8573; el plan decía 0,857249, una errata de la división).
    sigma = math.log(720 / 240) / Z90
    assert sigma == pytest.approx(0.8572517, abs=1e-7)
    for d in draws:
        truth = d.outcome.truth
        assert truth.bed_base == pytest.approx(240 * math.exp(sigma * truth.bed_z), rel=1e-12)


def test_otra_espera_de_cama_solo_cambia_la_espera_base(center, arrival_profile, profiles, draws):
    # [300, 900] tiene el mismo σ (900/300 = 3): cada espera base × 300/240 = 1,25, y ningún
    # otro sorteo del paciente cambia (números comunes).
    other = sampled(dataclasses.replace(center, bed_wait=(300.0, 900.0)), arrival_profile, profiles)

    assert len(other) == len(draws)
    for a, b in zip(draws, other, strict=True):
        assert b.outcome.bed_base == pytest.approx(1.25 * a.outcome.bed_base, rel=1e-12)
        assert dataclasses.replace(b.outcome.truth, bed_base=a.outcome.truth.bed_base) == (
            a.outcome.truth
        )
        assert b.clinical.truth == a.clinical.truth
        assert (b.level, b.triage_time, b.assessment_time, b.reassessment_time) == (
            a.level,
            a.triage_time,
            a.assessment_time,
            a.reassessment_time,
        )


def test_los_factores_de_cama_son_los_turnos_del_centro(center, arrival_profile, profiles):
    # Los turnos de [turnos] del centro, no las franjas de los perfiles (nota 2 del chat).
    moved = dataclasses.replace(center, shift_starts=(7, 14, 23))
    (first,) = sampled(moved, arrival_profile, profiles, days=1)[:1]
    beds = first.outcome.beds

    assert beds.shift_starts == (7, 14, 23) != profiles.shift_band_starts
    assert beds.shift_factors == (0.8, 1.0, 1.5)
    assert beds.season_factors == (1.0, 1.0, 1.0, 1.0)
    assert beds.start_date == arrival_profile.start_date


# --- El motor con los ficheros del hito 5 -----------------------------------------------------


@pytest.fixture(scope="module")
def simulated(center, arrival_profile, profiles):
    sink = MemorySink()
    result = simulate_ed(center, arrival_profile, DAYS, SEED, sink=sink, profiles=profiles)
    return sink.events, result


def test_el_motor_escribe_la_version_4_sin_violaciones(center, profiles, simulated):
    events, result = simulated

    assert {e.schema_version for e in events} == {OUTCOME_SCHEMA_VERSION}
    assert {"patient_left_wbs", "bed_requested", "bed_assigned"} <= {e.event_type for e in events}
    violations = check_invariants(
        events, center, ground_truth=result.ground_truth, inside=result.inside, profiles=profiles
    )
    assert violations == []


# --- Huellas, determinismo y números comunes --------------------------------------------------

# Huellas SHA-256 del modelo del hito 5 con los ejemplos del hito 5 (perfiles_h5_ejemplo,
# centro_h5_ejemplo y llegadas_ejemplo), semilla 2026 y 3 días: el log (eventos.jsonl) y
# el ground truth con truth_lines (clinical_factory). Generadas en la tarea 5.3, al añadir
# la verdad del desenlace; se regeneran solo con un cambio a propósito de los muestreadores,
# del motor del hito 5 o de EpisodeTruth, explicado en el commit, nunca para que un test pase.
H5_LOG_FINGERPRINT = "4e7312ce385d4d55133a141c64589316df94610a017904cbd2f8246c5a8d0e5a"
H5_TRUTH_FINGERPRINT = "609955d49c1baafbb68324dc0ae42243fa0e60283382ecb4ff476c5e61d1da8b"


def run_to_file(center, arrival_profile, profiles, path):
    with JsonlSink(path) as sink:
        return simulate_ed(center, arrival_profile, DAYS, SEED, sink=sink, profiles=profiles)


def test_huellas_del_log_y_de_la_verdad_del_hito_5(center, arrival_profile, profiles, tmp_path):
    path = tmp_path / "eventos.jsonl"
    result = run_to_file(center, arrival_profile, profiles, path)
    text = truth_lines(result.ground_truth.episodes)

    assert len(result.ground_truth.episodes) == 1101
    assert all(e.outcome is not None for e in result.ground_truth.episodes)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == H5_LOG_FINGERPRINT
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == H5_TRUTH_FINGERPRINT


def test_dos_ejecuciones_con_la_misma_semilla_son_iguales(
    center, arrival_profile, profiles, tmp_path
):
    a = run_to_file(center, arrival_profile, profiles, tmp_path / "a.jsonl")
    b = run_to_file(center, arrival_profile, profiles, tmp_path / "b.jsonl")

    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()
    assert a.ground_truth == b.ground_truth


def test_lo_clinico_es_el_del_hito_4_bit_a_bit(arrival_profile, simulated):
    # Los hijos 0 a 7 son los mismos con 8 y con 10 flujos (decisión 43): las llegadas y
    # la verdad clínica de cada paciente son las del hito 4 con los perfiles de ejemplo
    # sin el bloque. Solo cambia el destino (el flujo 4).
    _, h5 = simulated
    h4 = simulate_ed(
        load_center(DATA / "centro_sala_ejemplo.toml"),
        arrival_profile,
        DAYS,
        SEED,
        sink=MemorySink(),
        profiles=load_profiles(DATA / "perfiles_ejemplo.toml"),
    )
    pairs = list(zip(h4.ground_truth.episodes, h5.ground_truth.episodes, strict=True))

    assert h4.ground_truth.days == h5.ground_truth.days
    for a, b in pairs:
        assert (a.episode_id, a.arrival_time, a.clinical) == (
            b.episode_id,
            b.arrival_time,
            b.clinical,
        )
        assert (a.level, a.triage_time, a.assessment_time, a.reassessment_time, a.needs_tests) == (
            b.level,
            b.triage_time,
            b.assessment_time,
            b.reassessment_time,
            b.needs_tests,
        )
    assert any(a.admitted != b.admitted for a, b in pairs)  # el destino sí cambia


def test_con_otra_plantilla_ningun_sorteo_cambia(center, arrival_profile, profiles, simulated):
    # La plantilla y los boxes cambian el flujo, nunca lo sorteado: la misma verdad entera,
    # también la del desenlace.
    _, base = simulated
    other = dataclasses.replace(center, boxes=40, doctors=(14, 14, 9), triage_nurses=(4, 4, 3))
    result = simulate_ed(other, arrival_profile, DAYS, SEED, sink=MemorySink(), profiles=profiles)

    assert result.ground_truth == base.ground_truth


def test_la_verdad_del_desenlace_solo_tiene_tipos_de_python(simulated):
    # El gemelo del hito 5 de test_la_verdad_solo_tiene_tipos_de_python: type(x), no
    # isinstance, porque un np.float64 en el desenlace pasaría por float.
    _, result = simulated
    outcome_leaves = set()
    for truth in result.ground_truth.episodes:
        for path, value in leaves(asdict(truth)):
            assert type(value) in PLAIN, (truth.episode_id, path, type(value))
            if path[0] == "outcome":
                outcome_leaves.add(path[1:])

    # Guarda: el recorrido llega a las 4 Gumbel y a los dos z del desenlace.
    assert {("destination_draws", i) for i in range(4)} | {("patience_z",), ("bed_z",)} <= (
        outcome_leaves
    )


# --- El CSV del ground truth del hito 5 -------------------------------------------------------

PARAMETERS = RunParameters(
    center="tests/data/centro_h5_ejemplo.toml",
    center_fingerprint="5b86440058ee",
    profile="tests/data/llegadas_ejemplo.toml",
    profile_fingerprint="63d0ae1fb4f0",
    days=DAYS,
    warmup_days=1,
    seed=SEED,
    run_id="r2026",
)
PROFILES = ProfilesParameters(
    profiles="tests/data/perfiles_h5_ejemplo.toml", profiles_fingerprint="0123456789ab"
)
OUTCOME_HEADER = (
    "z_paciencia",
    "paciencia",
    "sorteo_destino_alta",
    "sorteo_destino_ingreso",
    "sorteo_destino_traslado",
    "sorteo_destino_exitus",
    "z_cama",
    "espera_cama_base",
)
"""Las 8 columnas nuevas, escritas a mano en el orden de la especificación."""


def write_h5(episodes, path):
    write_episodes_csv(episodes, path, PARAMETERS, PROFILES, outcome=True)
    return path


def test_las_columnas_del_desenlace_van_al_final(simulated, tmp_path):
    _, result = simulated
    path = write_h5(result.ground_truth.episodes, tmp_path / "episodios.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")

    assert OUTCOME_COLUMNS == OUTCOME_HEADER
    assert len(header) == 57 + 8 == 65
    assert tuple(header) == (*CLINICAL_EPISODE_COLUMNS, *OUTCOME_HEADER) == OUTCOME_EPISODE_COLUMNS


def test_ida_y_vuelta_del_csv_del_hito_5(simulated, tmp_path):
    # Con ==, floats bit a bit, también el destino contrafactual de quien se fue.
    events, result = simulated
    episodes = result.ground_truth.episodes
    path = write_h5(episodes, tmp_path / "episodios.csv")

    assert read_episodes_csv(path) == episodes
    # Guarda: la muestra tiene los cuatro destinos, y quien se fue tiene destino sorteado
    # aunque nunca llegó a la decisión, también uno distinto del alta.
    left = {e.episode_id for e in events if e.event_type == "patient_left_wbs"}
    assert {e.outcome.destination for e in episodes} == {"alta", "ingreso", "traslado", "exitus"}
    assert {e.outcome.destination for e in episodes if e.episode_id in left} > {"alta"}


def test_lo_leido_del_hito_5_solo_tiene_tipos_de_python(simulated, tmp_path):
    # El gemelo de test_lo_leido_solo_tiene_tipos_de_python (test_clinical_csv.py).
    _, result = simulated
    path = write_h5(result.ground_truth.episodes, tmp_path / "episodios.csv")
    outcome_leaves = set()
    for e in read_episodes_csv(path):
        for where, value in leaves(asdict(e)):
            assert type(value) in PLAIN, (e.episode_id, where, type(value))
            if where[0] == "outcome":
                outcome_leaves.add(where[1:])
    assert {("destination_draws", i) for i in range(4)} <= outcome_leaves


def test_un_csv_del_hito_5_sin_episodios(tmp_path):
    # El modelo, no los episodios, decide las columnas: 65 aunque no haya filas.
    path = write_h5((), tmp_path / "episodios.csv")

    assert path.read_text(encoding="utf-8") == ",".join(OUTCOME_EPISODE_COLUMNS) + "\n"
    assert read_episodes_csv(path) == ()


def test_el_csv_del_hito_5_exige_el_desenlace(simulated, tmp_path):
    _, result = simulated
    episodes = result.ground_truth.episodes
    path = tmp_path / "episodios.csv"
    h4 = dataclasses.replace(episodes[0], outcome=None)

    with pytest.raises(ValueError, match="needs the profiles"):
        write_episodes_csv(episodes, path, PARAMETERS, outcome=True)
    with pytest.raises(ValueError, match="needs outcome=True"):
        write_episodes_csv(episodes, path, PARAMETERS, PROFILES)
    with pytest.raises(ValueError, match="has no outcome"):
        write_h5((*episodes[1:], h4), path)
    assert not path.exists()  # se comprueba antes de crear el fichero


def h5_csv_rows(simulated, tmp_path) -> list[list[str]]:
    _, result = simulated
    path = write_h5(result.ground_truth.episodes[:3], tmp_path / "episodios.csv")
    return [line.split(",") for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("column", OUTCOME_HEADER)
@pytest.mark.parametrize("text", ["nan", "inf", "", "1e400"])
def test_un_valor_no_finito_en_el_desenlace_no_se_lee(simulated, tmp_path, column, text):
    rows = h5_csv_rows(simulated, tmp_path)
    rows[1][rows[0].index(column)] = text
    path = tmp_path / "roto.csv"
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"{column} must be"):
        read_episodes_csv(path)


def test_un_destino_desconocido_no_se_lee(simulated, tmp_path):
    rows = h5_csv_rows(simulated, tmp_path)
    rows[1][rows[0].index("destino")] = "uci"
    path = tmp_path / "roto.csv"
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="destino must be one of"):
        read_episodes_csv(path)


@pytest.mark.parametrize("cut", [-1, 1])
def test_una_cabecera_de_64_o_66_columnas_no_se_lee(simulated, tmp_path, cut):
    rows = h5_csv_rows(simulated, tmp_path)
    rows = [r[:cut] if cut < 0 else [*r, "x"] for r in rows]
    path = tmp_path / "roto.csv"
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid episode ground truth header"):
        read_episodes_csv(path)


def test_un_csv_de_57_columnas_es_del_hito_4(arrival_profile, tmp_path):
    # El CSV clínico de siempre se lee como hasta ahora: sin desenlace.
    result = simulate_ed(
        load_center(DATA / "centro_sala_ejemplo.toml"),
        arrival_profile,
        DAYS,
        SEED,
        sink=MemorySink(),
        profiles=load_profiles(DATA / "perfiles_ejemplo.toml"),
    )
    path = tmp_path / "episodios.csv"
    write_episodes_csv(result.ground_truth.episodes, path, PARAMETERS, PROFILES)

    assert len(path.read_text(encoding="utf-8").splitlines()[0].split(",")) == 57
    read = read_episodes_csv(path)
    assert read == result.ground_truth.episodes
    assert all(e.outcome is None for e in read)


# --- Decisión 28: ni la paciencia ni el destino de quien se fue van al log --------------------


def test_quien_se_fue_no_tiene_destino_en_el_log(simulated):
    events, _ = simulated
    left = {e.episode_id for e in events if e.event_type == "patient_left_wbs"}

    assert left
    assert not [e for e in events if e.episode_id in left and "destino" in e.payload]
