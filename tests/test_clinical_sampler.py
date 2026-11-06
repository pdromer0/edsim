"""El ClinicalSampler sin el motor: flujos, consumo fijo, respuesta por franja y destino.

Une los tres muestreadores de profiles/ y el destino provisional con los flujos 1 a 7
de child_streams(seed, 8) (tarea 4.5a, docs/specs/hito-4.md).
"""

import dataclasses
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
from clinical_factory import PLAIN, leaves

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import ArrivalRecord, iter_arrivals
from edsim.engine.center import load_center
from edsim.engine.clinical import PatientDraws
from edsim.engine.clinical_sampler import (
    ClinicalDraws,
    ClinicalSampler,
    ClinicalTruth,
    TurnaroundShifts,
    admitted_from_draw,
)
from edsim.engine.ground_truth import EpisodeTruth
from edsim.profiles.config import REASON_KEYS, TEST_TYPES, load_profiles
from edsim.profiles.context import ArrivalContext, arrival_context
from edsim.profiles.durations import durations_from_draws
from edsim.profiles.mixing import gumbel_max, reason_weights
from edsim.profiles.population import Person, draw_person_standard, person_from_draws
from edsim.profiles.sampler import SeverityAndTriage, draw_reason_standard
from edsim.profiles.severity import severity_from_draw, triage_from_draws, triage_quality
from edsim.profiles.workup import Workup, older_bands, workup_from_draws
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
SEED = 2026
DAYS = 3
N_HAND = 1000  # pacientes del test de asignación de flujos


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_ejemplo.toml")


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def arrival_profile():
    return load_profile(DATA / "llegadas_ejemplo.toml")


@pytest.fixture(scope="module")
def arrivals(arrival_profile) -> list[ArrivalRecord]:
    return list(iter_arrivals(arrival_profile, DAYS, child_streams(SEED, 8)[0]))


def make_sampler(profiles, center, arrival_profile, seed=SEED) -> ClinicalSampler:
    return ClinicalSampler(profiles, arrival_profile.start_date, center, child_streams(seed, 8)[1:])


# --- Flujos -------------------------------------------------------------------


def test_los_cinco_primeros_hijos_son_los_del_provisional():
    # Cada hijo depende solo de su índice: con 8 flujos, las llegadas (0) y los
    # cuatro del provisional son los mismos objetos que con 5.
    eight, five = child_streams(SEED, 8), child_streams(SEED, 5)
    for a, b in zip(eight[:5], five, strict=True):
        assert (a.entropy, a.spawn_key, a.pool_size) == (b.entropy, b.spawn_key, b.pool_size)
        assert a.generate_state(4).tolist() == b.generate_state(4).tolist()


def test_el_primer_paciente_con_sorteos_a_mano(profiles, center, arrival_profile, arrivals):
    # La z de G del primer paciente es la primera normal estándar del hijo 7, y su
    # error, la del hijo 1: con ellas se recalculan sus dos niveles.
    streams = child_streams(SEED, 8)
    first = make_sampler(profiles, center, arrival_profile)(arrivals[0])
    truth = first.clinical.truth
    z = np.random.default_rng(streams[7]).standard_normal()
    z_e = np.random.default_rng(streams[1]).standard_normal()
    t = profiles.triage

    assert truth.triage.z == z
    g = severity_from_draw(profiles.reason(truth.reason).severity, truth.person.band, z)
    assert truth.triage.severity == g
    assert (first.level, truth.triage.true_level) == triage_from_draws(
        g, z_e, t.thresholds, t.noise, t.bias
    )


def test_asignacion_de_flujos_a_mano(profiles, center, arrival_profile, arrivals):
    # Cada flujo con su generador independiente, y cada paciente transformado con las
    # funciones de profiles/: persona del 5, motivo del 6, G del 7, error del 1,
    # pruebas del 3, duraciones del 2 y destino del 4 con el nivel ASIGNADO.
    streams = child_streams(SEED, 8)
    rng = {i: np.random.default_rng(streams[i]) for i in range(1, 8)}
    sampler = make_sampler(profiles, center, arrival_profile)
    start, t = arrival_profile.start_date, profiles.triage
    older = older_bands(profiles.population)
    probabilities = center.admission_probability
    door = with_round = without_round = destination_differs = 0

    for arrival in arrivals[:N_HAND]:
        ctx = arrival_context(arrival.time, start, profiles.shift_band_starts)
        person = person_from_draws(profiles.population, ctx, draw_person_standard(rng[5]))
        weights = reason_weights(profiles, ctx, person.band)
        reason = REASON_KEYS[gumbel_max(weights, draw_reason_standard(rng[6]))]
        z, z_e = float(rng[7].standard_normal()), float(rng[1].standard_normal())
        test_draws = []
        for _ in TEST_TYPES:
            test_draws += [rng[3].random(), rng[3].random(), rng[3].standard_normal()]
        duration_draws = [rng[2].standard_normal() for _ in range(3)]
        u = rng[4].random()

        profile = profiles.reason(reason)
        g = severity_from_draw(profile.severity, person.band, z)
        level, true_level = triage_from_draws(g, z_e, t.thresholds, t.noise, t.bias)
        quality, jump = triage_quality(level, true_level)
        workup = workup_from_draws(
            profiles.diagnostic_tests, profile.test_pct, g, older[person.band], test_draws
        )
        durations = durations_from_draws(profiles, profile, true_level, duration_draws)
        expected = PatientDraws(
            level=level,
            triage_time=durations.triage_time,
            assessment_time=durations.assessment_time,
            reassessment_time=durations.reassessment_time,
            needs_tests=workup.has_round,
            test_turnaround=None,
            admitted=bool(u < probabilities[level - 1]),
            clinical=ClinicalDraws(
                truth=ClinicalTruth(
                    context=ctx,
                    person=person,
                    reason=reason,
                    triage=SeverityAndTriage(z, g, level, true_level, quality, jump),
                    workup=workup,
                ),
                shifts=sampler.shifts,
            ),
        )

        assert sampler(arrival) == expected
        door += level == 1
        with_round += workup.has_round
        without_round += not workup.has_round
        destination_differs += (u < probabilities[level - 1]) != (u < probabilities[true_level - 1])

    # Guardas: el caso ocurre. Pacientes de puerta (los 377, 701 y 866), con y sin
    # ronda, y pacientes cuyo destino cambiaría con el nivel real.
    assert door >= 3
    assert with_round > 0 and without_round > 0
    assert destination_differs > 0


# --- Consumo fijo ----------------------------------------------------------------


class CountingGenerator:
    """Un Generator que cuenta los valores que entrega."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self.count = 0

    def _take(self, size) -> None:
        self.count += 1 if size is None else int(np.prod(size))

    def random(self, size=None):
        self._take(size)
        return self._rng.random(size)

    def standard_normal(self, size=None):
        self._take(size)
        return self._rng.standard_normal(size)

    def gumbel(self, loc=0.0, scale=1.0, size=None):
        self._take(size)
        return self._rng.gumbel(loc, scale, size)


EXPECTED_DRAWS = {1: 1, 2: 3, 3: 12, 4: 1, 5: 7, 6: 17, 7: 1}
"""Sorteos fijos por paciente de cada flujo (docs/specs/hito-4.md)."""


def test_consumo_fijo_por_flujo(profiles, center, arrival_profile, arrivals, monkeypatch):
    # Generadores instrumentados: cada paciente consume lo mismo de cada flujo, sea
    # de puerta o de enfermería, con ronda o sin ella.
    real = np.random.default_rng
    counters: dict[int, CountingGenerator] = {}

    def counting_rng(seed):
        counter = CountingGenerator(real(seed))
        counters[seed.spawn_key[-1]] = counter
        return counter

    monkeypatch.setattr(np.random, "default_rng", counting_rng)
    sampler = make_sampler(profiles, center, arrival_profile)
    monkeypatch.undo()
    assert sorted(counters) == list(range(1, 8))

    kinds = set()
    for arrival in arrivals:
        before = {i: c.count for i, c in counters.items()}
        draws = sampler(arrival)
        assert {i: c.count - before[i] for i, c in counters.items()} == EXPECTED_DRAWS
        kinds.add((draws.level == 1, draws.needs_tests))

    # Guardas: hay pacientes de puerta y de enfermería, con y sin ronda.
    assert {door for door, _ in kinds} == {True, False}
    assert {tests for _, tests in kinds} == {True, False}


def test_los_flujos_no_se_modifican(profiles, center, arrival_profile, arrivals):
    streams = child_streams(SEED, 8)[1:]
    a = ClinicalSampler(profiles, arrival_profile.start_date, center, streams)
    first = [a(x) for x in arrivals[:200]]
    b = ClinicalSampler(profiles, arrival_profile.start_date, center, streams)

    assert [b(x) for x in arrivals[:200]] == first


def test_otra_semilla_da_otros_pacientes(profiles, center, arrival_profile, arrivals):
    a = make_sampler(profiles, center, arrival_profile)
    b = make_sampler(profiles, center, arrival_profile, seed=SEED + 1)

    assert [a(x) for x in arrivals[:50]] != [b(x) for x in arrivals[:50]]


# --- Respuesta de la ronda por franja del pedido, a mano ---------------------------

# Franjas [8, 15, 22] en hora local; el minuto 0 son las 00:00 del día de inicio.
# Factores de perfiles_ejemplo.toml: analítica 1,0 / 1,1 / 0,9; radiografía 1,0 / 1,0 /
# 1,2; ECG sin factor; imagen 1,0 / 1,1 / 1,3.
BASES = (75.0, 70.0, 12.0, 200.0)  # analítica, radiografía, ECG, imagen
AN_ECG = (True, False, True, False)
AN_RX = (True, True, False, False)
IMAGING = (False, False, False, True)


def hand_truth(ordered, turnarounds=BASES, abnormal=(False,) * 4) -> ClinicalTruth:
    return ClinicalTruth(
        context=ArrivalContext(0, 0, 0),
        person=Person(band=1, age=50, female=True, ambulance=False),
        reason="otros",
        triage=SeverityAndTriage(
            z=0.0, severity=0.0, level=3, true_level=3, quality="correcto", jump=0
        ),
        workup=Workup(
            ordered=tuple(ordered),
            abnormal=tuple(abnormal),
            turnarounds=tuple(turnarounds),
            draws=(0.0,) * 12,
        ),
    )


def hand_draws(profiles, ordered, **kwargs) -> ClinicalDraws:
    shifts = TurnaroundShifts.from_profiles(profiles, load_profile_start())
    return ClinicalDraws(truth=hand_truth(ordered, **kwargs), shifts=shifts)


def load_profile_start():
    return load_profile(DATA / "llegadas_ejemplo.toml").start_date


def hhmm(h: int, m: int) -> float:
    return 60.0 * h + m


@pytest.mark.parametrize(
    ("ordered", "at", "expected"),
    [
        pytest.param(AN_ECG, hhmm(14, 59), 75.0, id="analitica+ecg-14:59-manana"),
        pytest.param(AN_ECG, hhmm(15, 0), 82.5, id="analitica+ecg-15:00-tarde"),
        pytest.param(AN_ECG, hhmm(22, 0), 67.5, id="analitica+ecg-22:00-noche"),
        pytest.param(AN_RX, hhmm(14, 0), 75.0, id="analitica+rx-14:00-manana"),
        # De noche cambia la más lenta: la radiografía (70 × 1,2) pasa a la analítica
        # (75 × 0,9 = 67,5).
        pytest.param(AN_RX, hhmm(22, 0), 84.0, id="analitica+rx-22:00-noche"),
        pytest.param(IMAGING, hhmm(7, 59), 260.0, id="imagen-07:59-noche"),
        pytest.param(IMAGING, hhmm(8, 0), 200.0, id="imagen-08:00-manana"),
    ],
)
def test_respuesta_con_la_franja_del_pedido(profiles, ordered, at, expected):
    assert hand_draws(profiles, ordered).round_turnaround(at) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize(
    ("at", "band"),
    [(hhmm(7, 59), 2), (hhmm(8, 0), 0), (hhmm(14, 59), 0), (hhmm(15, 0), 1), (hhmm(22, 0), 2)],
)
def test_franja_del_instante(profiles, at, band):
    shifts = TurnaroundShifts.from_profiles(profiles, load_profile_start())
    assert shifts.shift_band_at(at) == band
    assert shifts.factors_at(at) == shifts.factors[band]


def test_factores_de_cada_franja(profiles):
    shifts = TurnaroundShifts.from_profiles(profiles, load_profile_start())
    assert shifts.factors == ((1.0, 1.0, 1.0, 1.0), (1.1, 1.0, 1.0, 1.1), (0.9, 1.2, 1.0, 1.3))
    assert shifts.shift_band_starts == (8, 15, 22)


def test_sin_ronda_no_hay_respuesta(profiles):
    with pytest.raises(ValueError, match="no round"):
        hand_draws(profiles, (False,) * 4).round_turnaround(hhmm(10, 0))


def test_payloads_clinicos(profiles):
    draws = hand_draws(profiles, AN_ECG, abnormal=(True, True, False, True))

    assert draws.payload("patient_arrived") == {"medio": "propios_medios"}
    assert draws.payload("patient_registered") == {"edad": 50, "sexo": "mujer"}
    assert draws.payload("triage_completed") == {"motivo": "otros"}
    assert draws.payload("test_ordered") == {"pruebas": ("analitica", "ecg")}
    # Solo las pedidas: la radiografía y la imagen salen alteradas, pero no se pidieron.
    assert draws.payload("test_resulted") == {
        "resultados": {"analitica": "alterado", "ecg": "normal"}
    }
    with pytest.raises(ValueError, match="no clinical payload"):
        draws.payload("box_assigned")


# --- Destino provisional con el nivel asignado ------------------------------------

ADMISSION = (0.80, 0.45, 0.15, 0.04, 0.01)  # probabilidad_ingreso de los centros de ejemplo


def test_destino_con_el_nivel_asignado(center):
    # Asignado 3 (0,15) y real 2 (0,45), con u = 0,30: alta. Con el nivel real sería
    # ingreso.
    assert center.admission_probability == ADMISSION
    assert admitted_from_draw(0.30, 3, ADMISSION) is False
    assert admitted_from_draw(0.30, 2, ADMISSION) is True


def test_destino_en_el_borde():
    assert admitted_from_draw(0.15, 3, ADMISSION) is False
    assert admitted_from_draw(math.nextafter(0.15, 0), 3, ADMISSION) is True


# --- Validación -------------------------------------------------------------------


def test_patient_draws_exige_un_modelo(profiles):
    clinical = hand_draws(profiles, AN_ECG)
    base = dict(level=3, triage_time=5.0, assessment_time=20.0, reassessment_time=10.0)

    with pytest.raises(ValueError, match="test_turnaround"):
        PatientDraws(**base, needs_tests=True, test_turnaround=None, admitted=False)
    with pytest.raises(ValueError, match="test_turnaround"):
        PatientDraws(
            **base, needs_tests=True, test_turnaround=60.0, admitted=False, clinical=clinical
        )
    with pytest.raises(ValueError, match="needs_tests"):
        PatientDraws(
            **base, needs_tests=False, test_turnaround=None, admitted=False, clinical=clinical
        )
    # Los dos modelos válidos.
    PatientDraws(**base, needs_tests=True, test_turnaround=60.0, admitted=False)
    PatientDraws(**base, needs_tests=True, test_turnaround=None, admitted=False, clinical=clinical)


@pytest.mark.parametrize("n", [0, 6, 8])
def test_numero_de_flujos_incorrecto(profiles, center, arrival_profile, n):
    with pytest.raises(ValueError, match="7 SeedSequence"):
        ClinicalSampler(profiles, arrival_profile.start_date, center, child_streams(SEED, 9)[:n])


def test_flujos_que_no_son_seed_sequence(profiles, center, arrival_profile):
    streams = [*child_streams(SEED, 8)[1:7], 7]
    with pytest.raises(ValueError, match=r"streams\[6\]"):
        ClinicalSampler(profiles, arrival_profile.start_date, center, streams)


def test_inmutable(profiles, center, arrival_profile, arrivals):
    draws = make_sampler(profiles, center, arrival_profile)(arrivals[0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        draws.clinical.truth = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        draws.clinical.truth.reason = "otros"


# --- Tipos exactos de la verdad ---------------------------------------------------


def test_la_verdad_solo_tiene_tipos_de_python(profiles, center, arrival_profile, arrivals):
    # type(x), no isinstance: np.float64 es subclase de float y json.dumps lo aceptaría
    # en silencio, así que la huella del ground truth no vería un escalar de NumPy.
    sampler = make_sampler(profiles, center, arrival_profile)
    workup_leaves = set()
    for arrival in arrivals:
        truth = EpisodeTruth.from_draws(arrival, sampler(arrival))
        for path, value in leaves(asdict(truth)):
            assert type(value) in PLAIN, (truth.episode_id, path, type(value))
            if path[:2] == ("clinical", "workup"):
                workup_leaves.add(path[2:])

    # Guarda: el recorrido llega a las hojas anidadas, los 12 sorteos y las 4 respuestas.
    assert {p for p in workup_leaves if p[0] == "draws"} == {("draws", i) for i in range(12)}
    assert {p for p in workup_leaves if p[0] == "turnarounds"} == {
        ("turnarounds", i) for i in range(4)
    }
