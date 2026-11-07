"""Los tres relojes, el pretriaje, el nivel 1 y la medida del cumplimiento (tarea 4.8a).

Un log a mano en el día 1: tres niveles 2 de enfermería y dos niveles 1 en la puerta.
Para cada paciente, A = pretriaje + triaje + espera, B = triaje + espera y C = espera.
"""

import pytest
from test_invariants import build

from edsim.engine.analysis import episode_table
from edsim.runs import (
    level_one_clocks,
    window_clocks,
    window_compliance,
    window_pretriage,
)


def patient(number, arrival, pretriage, triage, wait, *, level=2):
    """Llegada, triaje (puerta si es nivel 1), box y médico; sale 30 min después."""
    start = arrival + pretriage
    classified = start + triage
    doctor = classified + wait
    circuit = "puerta" if level == 1 else "enfermeria"
    return [
        (arrival, number, "patient_arrived", {}),
        (start, number, "triage_started", {"circuito": circuit}),
        (classified, number, "triage_completed", {"nivel": level}),
        (classified, number, "box_assigned", {"box": number + 1}),
        (doctor, number, "assessment_started", {"tipo": "inicial", "pool": "medicos", "box": 1}),
        (doctor + 30, number, "patient_departed", {"destino": "alta"}),
    ]


@pytest.fixture
def table():
    events = build(
        patient(0, 1500, 2, 5, 3),  # A 10, B 8, C 3
        patient(1, 1600, 8, 6, 10),  # A 24, B 16, C 10
        patient(2, 1700, 12, 4, 20),  # A 36, B 24, C 20
        patient(3, 1800, 0, 0, 1, level=1),  # puerta: A = B = C = 1
        patient(4, 1900, 0, 0, 3, level=1),  # puerta: A = B = C = 3
        patient(5, 100, 50, 5, 5),  # calentamiento: no cuenta
    )
    return episode_table(events)


def test_tres_relojes_del_nivel_2_a_mano(table):
    level_2 = window_clocks(table, 1, 2)[1]
    by_name = {c.measure: c for c in level_2.clocks}

    assert level_2.level == 2 and level_2.n == 3
    assert [c.measure for c in level_2.clocks] == [
        "door_to_doctor",
        "triage_start_to_doctor",
        "classified_to_doctor",
    ]
    # Medias, medianas y p90 con interpolación lineal (índice 0,9 · 2 = 1,8).
    assert by_name["door_to_doctor"].mean == pytest.approx(70 / 3)
    assert by_name["door_to_doctor"].median == 24
    assert by_name["door_to_doctor"].p90 == pytest.approx(24 + 0.8 * 12)
    assert by_name["triage_start_to_doctor"].mean == pytest.approx(16)
    assert by_name["triage_start_to_doctor"].p90 == pytest.approx(16 + 0.8 * 8)
    assert by_name["classified_to_doctor"].mean == pytest.approx(11)
    assert by_name["classified_to_doctor"].median == 10
    assert by_name["classified_to_doctor"].p90 == pytest.approx(10 + 0.8 * 10)


def test_un_nivel_sin_pacientes_no_tiene_estadisticos(table):
    level_3 = window_clocks(table, 1, 2)[2]

    assert level_3.n == 0
    assert all(c.mean is c.median is c.p90 is None for c in level_3.clocks)


def test_el_nivel_1_solo_con_mediana_y_p90(table):
    level_1 = level_one_clocks(table, 1, 2)

    assert level_1.level == 1 and level_1.n == 2
    for name in ("door_to_doctor", "triage_start_to_doctor", "classified_to_doctor"):
        assert level_1.median[name] == 2
        assert level_1.p90[name] == pytest.approx(1 + 0.9 * 2)
    assert not hasattr(level_1, "mean")


def test_pretriaje_sin_el_nivel_1(table):
    result = window_pretriage(table, 1, 2)
    level_2, everyone = result.by_group[0], result.by_group[-1]

    # Pretriajes 2, 8 y 12: dos dentro de 10 min, dos por encima de 5 y el día fuera
    # (2/3 < 85 %). Los niveles 1 de la puerta no cuentan en ningún grupo.
    assert (level_2.group, level_2.n) == (2, 3)
    assert level_2.within_share == pytest.approx(2 / 3)
    assert level_2.over_share == pytest.approx(2 / 3)
    assert (level_2.days_out, level_2.days_with_patients) == (1, 1)
    assert (everyone.group, everyone.n) == (None, 3)
    assert result.by_group[1].n == 0 and result.by_group[1].within_share is None


def test_cumplimiento_con_el_reloj_c_a_mano(table):
    result = window_compliance(table, 1, 2, measure="classified_to_doctor")
    level_2 = result.by_level[1]

    # Máximo del nivel 2: 10 min. Con C (3, 10 y 20) solo excede uno; justo en 10 cumple.
    assert result.daily.measure == "classified_to_doctor"
    assert (level_2.n, level_2.exceeded) == (3, 1)
    assert level_2.exceeded_share == pytest.approx(1 / 3)
    assert level_2.share_out == 1.0


def test_sin_medida_el_cumplimiento_sigue_con_el_reloj_a(table):
    default = window_compliance(table, 1, 2)
    explicit = window_compliance(table, 1, 2, measure="door_to_doctor")

    assert default.daily.measure == "door_to_doctor"
    # Con A (10, 24 y 36) exceden dos: la medida de verdad cambia el resultado.
    assert default.by_level[1].exceeded == 2
    assert default.by_level == explicit.by_level


def test_una_medida_desconocida_es_un_error(table):
    with pytest.raises(ValueError, match="measure"):
        window_compliance(table, 1, 2, measure="stay")
