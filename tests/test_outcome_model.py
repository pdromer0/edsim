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
