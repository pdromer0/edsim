"""El modelo del hito 5 en el motor (tarea 5.3), con los ficheros de ejemplo del hito 5.

``perfiles_h5_ejemplo.toml`` y ``centro_h5_ejemplo.toml`` eligen el modelo del hito 5
(decisión 68): ``child_streams(seed, 10)``, con los hijos 0 a 7 del hito 4 bit a bit y el
desenlace de los flujos 4 (destino), 8 (paciencia) y 9 (espera de cama). Los valores
esperados salen de generadores propios del test, no del muestreador.
"""

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import iter_arrivals
from edsim.engine.center import load_center
from edsim.engine.clinical_sampler import ClinicalSampler, PatientModel
from edsim.engine.engine import simulate_ed
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, MemorySink
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
