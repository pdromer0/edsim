"""El dado real del registro clínico: el flujo propio de la semilla (tarea 7.2).

Cada test dice qué error pilla. Los literales son los de la tirada calculada a mano con numpy
directo, sin `edsim` (el cálculo, en el plan y en el PR de la 7.2):
`default_rng(SeedSequence(2026).spawn(11)[10])`, 13 uniformes por tirada y los tres `z` por la
inversa de la normal.
"""

import dataclasses
from statistics import NormalDist

import numpy as np
import pytest
from registro_factory import (
    RUN,
    CountingDice,
    clean_record_profile,
    loud_profile,
    patient_log,
)
from runaway import RunawayLoop

from edsim.clinical_record import (
    DUPLICATE,
    LOST,
    ROLL_SIZE,
    Roll,
    StreamDice,
    notebook_csv,
    record,
    record_json,
)
from edsim.engine.events import CATALOGS

SEED = 2026
ROLL_1 = [0.640905, 0.145248, -0.514496, 0.091152, 0.751757, 0.309891, 0.793521, 0.72415,
          0.872385, -0.632064, 0.588579, -0.298706, 0.556176]  # fmt: skip
ROLL_2 = [0.277968, 0.347375, -0.484185, 0.169878, 0.489183, 0.75814, 0.202029, 0.693677,
          0.215922, -0.257767, 0.658356, 0.172989, 0.029479]  # fmt: skip
Z_POSITIONS = (2, 9, 11)  # z_retraso, z_correccion y z_duplicado


def numbers(roll: Roll) -> list[float]:
    return list(dataclasses.astuple(roll))


def test_las_dos_primeras_tiradas_son_las_calculadas_a_mano():
    """Pilla el flujo equivocado (otro hijo, otra semilla) y los `z` en otra posición."""
    dice = StreamDice(SEED)
    assert numbers(dice.roll()) == pytest.approx(ROLL_1, abs=5e-7)
    assert numbers(dice.roll()) == pytest.approx(ROLL_2, abs=5e-7)


def test_cada_tirada_consume_exactamente_trece_numeros_del_flujo():
    """Pilla un consumo variable: la tirada k son los números 13k a 13k + 12 del flujo.

    La referencia es numpy directo, sin `StreamDice`: 50 tiradas seguidas de la misma `random`.
    """
    stream = np.random.default_rng(np.random.SeedSequence(SEED).spawn(11)[10]).random(13 * 50)
    normal = NormalDist()
    dice = StreamDice(SEED)
    for k in range(50):
        u = stream[13 * k : 13 * (k + 1)].tolist()
        expected = [normal.inv_cdf(x) if i in Z_POSITIONS else x for i, x in enumerate(u)]
        assert numbers(dice.roll()) == pytest.approx(expected, abs=1e-12), k


def test_la_misma_semilla_da_las_mismas_tiradas_y_otra_semilla_otras():
    """Pilla un dado que no depende de la semilla (o que depende de algo más)."""
    a, b, c = StreamDice(7), StreamDice(7), StreamDice(8)
    assert [numbers(a.roll()) for _ in range(5)] == [numbers(b.roll()) for _ in range(5)]
    assert numbers(StreamDice(7).roll()) != numbers(c.roll())


class _Constant:
    """Un generador que devuelve siempre el mismo uniforme: lleva el dado a sus bordes."""

    def __init__(self, value: float):
        self.value = value

    def random(self, size: int):
        return np.full(size, self.value)


@pytest.mark.parametrize(
    ("u", "z"),
    [(0.0, -8.2095), (0.5, 0.0), (1 - 2**-53, 8.2095)],
    ids=["cero", "mediana", "el_mayor"],
)
def test_la_normal_es_finita_en_los_bordes_del_uniforme(u, z):
    """Pilla `inv_cdf(0)`, que lanza un error: un uniforme de numpy puede valer 0."""
    dice = StreamDice(SEED)
    dice._rng = _Constant(u)
    roll = dice.roll()
    assert roll.z_delay == pytest.approx(z, abs=1e-4)
    assert roll.z_correction == roll.z_duplicate == roll.z_delay
    assert (roll.u_forget, roll.spare) == (u, u)


@pytest.mark.parametrize("seed", [-1, 1.5, True, "7", None], ids=repr)
def test_semilla_no_valida(seed):
    """Pilla una semilla que `SeedSequence` aceptaría a su manera (`True` como 1)."""
    with pytest.raises(ValueError, match="seed must be an integer >= 0"):
        StreamDice(seed)


def test_una_semilla_enorme_vale():
    """Una semilla de más de 64 bits vale para el dado (el `run_id` derivado es otro asunto)."""
    assert len(numbers(StreamDice(2**100).roll())) == ROLL_SIZE


def test_record_sin_dice_es_record_con_el_dado_de_la_semilla():
    """Pilla un dado por defecto que no es el de la semilla: lo escrito sale distinto."""
    events = patient_log(60)
    kwargs = {"horizon": 2 * 1440.0, "run_id": RUN}
    default = record(events, loud_profile(), 7, **kwargs)
    explicit = record(events, loud_profile(), 7, dice=StreamDice(7), **kwargs)
    kinds = {row.kind for row in default.notebook}
    assert {LOST, DUPLICATE} <= kinds, "el perfil ruidoso tiene que dar despistes de verdad"
    assert [record_json(r) for r in default.records] == [record_json(r) for r in explicit.records]
    assert notebook_csv(default.notebook) == notebook_csv(explicit.notebook)


@pytest.mark.parametrize("profile", [clean_record_profile(), loud_profile()], ids=lambda p: p.name)
def test_una_tirada_por_evento_de_paciente_sea_cual_sea_el_perfil(profile):
    """Pilla un consumo que cambia con el perfil: en el limpio, o con lo olvidado, no se tira."""
    events = patient_log(120)
    patient = sum(CATALOGS[e.schema_version][e.event_type].patient for e in events)
    assert patient < len(events), "el log tiene que traer eventos de recursos"
    dice = CountingDice(StreamDice(3))
    record(events, profile, 3, horizon=2 * 1440.0, run_id=RUN, dice=dice)
    assert dice.calls == patient


def test_si_todo_se_olvida_se_tira_igual():
    """Pilla el atajo «olvidado: no tiro»: el dado del evento siguiente se desplazaría."""
    forgetful = dataclasses.replace(loud_profile(), forget=1.0)
    events = patient_log(20)
    patient = sum(CATALOGS[e.schema_version][e.event_type].patient for e in events)
    dice = CountingDice(StreamDice(3))
    recording = record(events, forgetful, 3, horizon=2 * 1440.0, run_id=RUN, dice=dice)
    assert dice.calls == patient
    assert {row.kind for row in recording.notebook if row.record_id is None} == {LOST}


def test_el_dado_contador_corta_un_bucle_que_no_para():
    """El tope funciona: una versión incorrecta que pida tiradas sin fin falla, no cuelga."""
    dice = CountingDice(StreamDice(1), limit=5)
    with pytest.raises(RunawayLoop):
        for _ in range(10**9):
            dice.roll()
    assert dice.calls == 6
