"""Sorteos del desenlace del hito 5: paciencia, destino y espera de cama (tarea 5.1).

`OutcomeDraws` se inyecta a mano en los escenarios del motor; el muestreador es de la
tarea 5.2. La espera de cama es base × factor del turno × factor de la estación, con el
turno de los `[turnos]` del centro y la estación de la fecha del instante del pedido.

Los valores esperados están calculados a mano en el plan: las fechas con
`date(2026, 1, 5) + timedelta(days=d)` y los turnos con los inicios 8, 15 y 22.
"""

import dataclasses
import math
from datetime import date, datetime, timedelta

import pytest
from clinical_factory import example_profiles, hand_patient

from edsim.arrivals.thinning import ArrivalRecord
from edsim.engine.clinical import BedWaitFactors, OutcomeDraws, PatientDraws
from edsim.engine.ground_truth import EpisodeTruth
from edsim.profiles.sampler import Outcome

START = date(2026, 1, 5)
SEASONS = (1.0, 1.2, 0.9, 1.1)


def factors(**kwargs) -> BedWaitFactors:
    values = {
        "start_date": START,
        "shift_starts": (8, 15, 22),
        "shift_factors": (0.8, 1.0, 1.5),
        "season_factors": SEASONS,
    } | kwargs
    return BedWaitFactors(**values)


def outcome(**kwargs) -> OutcomeDraws:
    values = {"patience": 60.0, "destination": "alta", "bed_base": 100.0, "beds": factors()}
    return OutcomeDraws(**(values | kwargs))


# --- Factores por turno y estación ---------------------------------------------------


def test_las_fechas_del_calculo_a_mano():
    # Referencia independiente de la función probada: el calendario de datetime.
    assert START + timedelta(days=54) == date(2026, 2, 28)
    assert START + timedelta(days=55) == date(2026, 3, 1)
    assert START + timedelta(days=361) == date(2027, 1, 1)


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (480, 80.0),  # 8:00 del 5 de enero: mañana, invierno; 100 × 0,8 × 1,0
        (479.5, 150.0),  # 7:59:30: aún la noche; 100 × 1,5 × 1,0
        (35, 150.0),  # 0:35: noche (escenario C)
        (54 * 1440 + 600, 80.0),  # 28-02 10:00: mañana, invierno
        (55 * 1440 + 600, 96.0),  # 01-03 10:00: mañana, primavera; 100 × 0,8 × 1,2
        (55 * 1440 + 960, 120.0),  # 01-03 16:00: tarde, primavera; 100 × 1,0 × 1,2
        (361 * 1440 + 1380, 150.0),  # 01-01-2027 23:00: noche, invierno
    ],
)
def test_espera_de_cama_por_turno_y_estacion(t, expected):
    assert math.isclose(outcome().bed_wait(t), expected, rel_tol=1e-12)


def test_la_espera_usa_el_instante_del_pedido():
    # Variante del turno del escenario C: llega a las 7:30 (noche) y pide cama a las 8:10
    # (mañana). La espera es la de las 8:10: 100 × 0,8 = 80, no 150.
    draws = outcome(beds=factors(season_factors=(1.0,) * 4))
    assert draws.bed_wait(490) == 80.0
    assert draws.bed_wait(450) == 150.0


def test_estaciones_por_defecto_valen_1():
    beds = BedWaitFactors(START, (8, 15, 22), (0.8, 1.0, 1.5))
    assert beds.season_factors == (1.0, 1.0, 1.0, 1.0)
    assert beds.factor_at(55 * 1440 + 600) == 0.8


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"start_date": datetime(2026, 1, 5)}, "start_date"),
        ({"start_date": "2026-01-05"}, "start_date"),
        ({"shift_starts": (8, 15)}, "shift_starts"),
        ({"shift_starts": (8, 8, 22)}, "shift_starts"),
        ({"shift_starts": (8, 15, 24)}, "shift_starts"),
        ({"shift_starts": (8.0, 15, 22)}, "shift_starts"),
        ({"shift_starts": (True, 15, 22)}, "shift_starts"),
        ({"shift_factors": (0.8, 1.0)}, "shift_factors"),
        ({"shift_factors": (0.8, 1.0, 0.0)}, "shift_factors"),
        ({"shift_factors": (0.8, 1.0, math.nan)}, "shift_factors"),
        ({"shift_factors": "0.8"}, "shift_factors"),
        ({"season_factors": (1.0, 1.0, 1.0)}, "season_factors"),
        ({"season_factors": (1.0, 1.0, 1.0, math.inf)}, "season_factors"),
        ({"season_factors": (1.0, 1.0, 1.0, 10**400)}, "season_factors"),
    ],
)
def test_factores_no_validos(change, match):
    with pytest.raises(ValueError, match=match):
        factors(**change)


# --- OutcomeDraws ---------------------------------------------------------------------


def test_listas_se_guardan_como_tuplas():
    beds = factors(shift_starts=[8, 15, 22], shift_factors=[0.8, 1, 1.5])
    assert beds.shift_starts == (8, 15, 22)
    assert beds.shift_factors == (0.8, 1.0, 1.5)
    assert all(type(x) is float for x in beds.shift_factors)


@pytest.mark.parametrize("destination", ["alta", "ingreso", "traslado", "exitus"])
def test_cuatro_destinos(destination):
    assert outcome(destination=destination).destination == destination


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"patience": -1.0}, "patience"),
        ({"patience": math.nan}, "patience"),
        ({"patience": math.inf}, "patience"),
        ({"patience": True}, "patience"),
        ({"patience": 10**400}, "patience"),
        ({"patience": "60"}, "patience"),
        ({"bed_base": -0.5}, "bed_base"),
        ({"bed_base": math.nan}, "bed_base"),
        ({"destination": "uci"}, "destination"),
        ({"destination": "Alta"}, "destination"),
        ({"destination": None}, "destination"),
        ({"beds": (0.8, 1.0, 1.5)}, "beds"),
    ],
)
def test_desenlace_no_valido(change, match):
    with pytest.raises(ValueError, match=match):
        outcome(**change)


def test_paciencia_0_y_espera_0_son_validas():
    draws = outcome(patience=0, bed_base=0)
    assert (draws.patience, draws.bed_base) == (0.0, 0.0)
    assert draws.bed_wait(35) == 0.0


# --- PatientDraws.outcome ---------------------------------------------------------------


@pytest.fixture(scope="module")
def clinical_patient() -> PatientDraws:
    return hand_patient(example_profiles())


def test_sin_desenlace_por_defecto(clinical_patient):
    assert clinical_patient.outcome is None
    assert [f.name for f in dataclasses.fields(PatientDraws)][-2:] == ["clinical", "outcome"]


def test_desenlace_con_el_modelo_clinico(clinical_patient):
    draws = dataclasses.replace(clinical_patient, outcome=outcome(), admitted=False)
    assert draws.outcome.destination == "alta"
    admitted = dataclasses.replace(
        clinical_patient, outcome=outcome(destination="ingreso"), admitted=True
    )
    assert admitted.admitted


def test_desenlace_sin_modelo_clinico_falla():
    with pytest.raises(ValueError, match="clinical"):
        PatientDraws(3, 5.0, 20.0, 10.0, False, 60.0, False, outcome=outcome())


@pytest.mark.parametrize(
    ("destination", "admitted"),
    [("ingreso", False), ("alta", True), ("traslado", True), ("exitus", True)],
)
def test_admitted_coherente_con_el_destino(clinical_patient, destination, admitted):
    with pytest.raises(ValueError, match="admitted"):
        dataclasses.replace(
            clinical_patient, outcome=outcome(destination=destination), admitted=admitted
        )


def test_la_verdad_del_episodio_aun_no_guarda_el_desenlace(clinical_patient):
    # La verdad del desenlace es de la tarea 5.3: hasta entonces, EpisodeTruth no cambia.
    draws = dataclasses.replace(clinical_patient, outcome=outcome())
    truth = EpisodeTruth.from_draws(ArrivalRecord(0, 0.0), draws)
    assert truth == EpisodeTruth.from_draws(ArrivalRecord(0, 0.0), clinical_patient)
    assert not hasattr(truth, "outcome")


DRAWN = Outcome(
    destination_draws=(0.1, 1.9, 0.5, 0.2),
    destination="ingreso",
    patience_z=-0.3,
    patience=95.5,
    bed_z=0.4,
    bed_base=301.25,
)
"""Un desenlace sorteado a mano (tarea 5.3): lo que el motor lee sale de aquí."""


def test_from_outcome_lee_lo_sorteado_y_lo_guarda_como_verdad():
    draws = OutcomeDraws.from_outcome(DRAWN, factors())

    assert (draws.patience, draws.destination, draws.bed_base) == (95.5, "ingreso", 301.25)
    assert draws.truth is DRAWN
    assert outcome().truth is None  # los pacientes a mano de los escenarios


@pytest.mark.parametrize(
    "change",
    [{"patience": 95.0}, {"destination": "alta"}, {"bed_base": 301.0}],
)
def test_la_verdad_tiene_que_coincidir_con_lo_que_lee_el_motor(change):
    values = {"patience": 95.5, "destination": "ingreso", "bed_base": 301.25} | change
    with pytest.raises(ValueError, match="must be those of truth"):
        OutcomeDraws(**values, beds=factors(), truth=DRAWN)


def test_la_verdad_es_un_outcome():
    with pytest.raises(ValueError, match="truth must be an Outcome"):
        outcome(truth=dataclasses.asdict(DRAWN))


def test_el_turno_de_la_cama_es_el_de_shift_at():
    # factor_at toma el turno de arrival_context con los inicios del centro: el mismo que
    # shifts.shift_at, minuto a minuto durante un día y con otros inicios.
    from edsim.engine.shifts import shift_at

    for starts in ((8, 15, 22), (0, 7, 19), (6, 14, 23)):
        beds = factors(
            shift_starts=starts, shift_factors=(1.0, 2.0, 4.0), season_factors=(1.0,) * 4
        )
        for minute in range(0, 1440):
            t = minute + 0.5
            assert beds.factor_at(t) == (1.0, 2.0, 4.0)[shift_at(starts, t)], (starts, t)
