"""Esperas por día y nivel y cumplimiento de los tiempos máximos de Manchester.

Las tablas de episodios se construyen a mano: aquí importa a qué día y nivel va cada
episodio y cuándo cumple, no cómo se pliega el log (eso lo prueba test_engine_analysis).
"""

import numpy as np
import pytest

from edsim.engine.analysis import EpisodeRecord
from edsim.engine.targets import (
    COMPLIANCE_TARGET,
    MANCHESTER_MAX_WAIT,
    PRETRIAGE_LONG_WAIT,
    PRETRIAGE_MAX_WAIT,
    PRETRIAGE_TARGET,
    clock_quantiles,
    daily_waits,
    manchester_compliance,
    pretriage,
)

DAY = 1440.0


def record(
    n: int,
    arrival: float,
    level: int,
    door: float,
    *,
    departed: bool = True,
    box=0.0,
    triage: float = 0.0,
    pretriage: float = 0.0,
):
    """Un episodio que llega en ``arrival`` y ve al médico ``door`` minutos después.

    Espera ``pretriage`` a la enfermera y su triaje dura ``triage``. Sin ellos los tres
    relojes valen ``door``; con ellos, B = door − pretriaje y C = door − pretriaje − triaje.
    """
    return EpisodeRecord(
        episode_id=f"EP-{n:06d}",
        arrival=arrival,
        triage_start=arrival + pretriage,
        triage_end=arrival + pretriage + triage,
        level=level,
        first_box=arrival + pretriage + triage,
        first_assessment=arrival + door,
        decision=arrival + door + 20 if departed else None,
        departure=arrival + door + 20 if departed else None,
        destination="alta" if departed else None,
        displacements=0,
        triage_wait=pretriage,
        box_wait=box if departed else None,
        doctor_wait=0.0 if departed else None,
        initial_doctor_wait=0.0,
        door_to_doctor=door,
        triage_start_to_doctor=door - pretriage,
        classified_to_doctor=door - pretriage - triage,
        initial_box_wait=box,
        results_box_wait=0.0 if departed else None,
    )


def test_maximos_de_manchester():
    assert MANCHESTER_MAX_WAIT == (0.0, 10.0, 60.0, 120.0, 240.0)
    assert COMPLIANCE_TARGET == 0.90


# Día 1: dos de nivel 4 (box 10 y 30) y uno de nivel 2. Día 2: uno de nivel 4 (box 50),
# otro que sigue dentro (no cuenta) y uno de nivel 4 del día 3 (fuera del tramo).
TABLE = (
    record(0, DAY + 100, 4, 30.0, box=10.0),
    record(1, DAY + 200, 4, 40.0, box=30.0),
    record(2, DAY + 300, 2, 8.0),
    record(3, 2 * DAY + 10, 4, 60.0, box=50.0),
    record(4, 2 * DAY + 20, 4, 60.0, departed=False),
    record(5, 3 * DAY + 10, 4, 60.0, box=99.0),
    record(6, 0.5 * DAY, 4, 60.0, box=99.0),  # día 0: antes del tramo
)


def test_esperas_por_dia_y_nivel():
    d = daily_waits(TABLE, "box_wait", 1, 3)
    assert list(d.days) == [1, 2]
    assert d.n.tolist() == [[0, 1, 0, 2, 0], [0, 0, 0, 1, 0]]
    assert d.mean[0, 3] == 20.0 and d.mean[1, 3] == 50.0
    assert d.mean[0, 1] == 0.0
    assert np.isnan(d.mean[0, 0]) and np.isnan(d.mean[1, 1])


def test_esperas_medida_desconocida():
    with pytest.raises(ValueError, match="measure"):
        daily_waits(TABLE, "espera", 1, 3)


@pytest.mark.parametrize(("first", "end"), [(2, 2), (3, 1), (-1, 2), (1.0, 2), (True, 2)])
def test_dias_invalidos(first, end):
    with pytest.raises(ValueError):
        daily_waits(TABLE, "box_wait", first, end)


def test_justo_en_el_maximo_cumple():
    # Nivel 2, máximo 10: exactamente 10 cumple; 10,001 no.
    table = (record(0, 100, 2, 10.0), record(1, 200, 2, 10.001))
    c = manchester_compliance(table, 0, 1)
    assert c.within[0, 1] == 0.5
    assert c.out[0, 1]  # 50 % < 90 %
    assert manchester_compliance(table[:1], 0, 1).within[0, 1] == 1.0
    assert not manchester_compliance(table[:1], 0, 1).out[0, 1]


def test_cumplimiento_por_dia_y_nivel():
    # Día 0: 10 de nivel 3, uno pasa de 60 (90 % cumple: dentro). Día 1: 10 de nivel 3,
    # dos pasan (80 %: fuera). Nivel 1 en el día 1: espera 3 > 0, fuera. Día 2: nadie.
    table = [record(i, 10 + i, 3, 70.0 if i == 0 else 20.0) for i in range(10)]
    table += [record(10 + i, DAY + 10 + i, 3, 70.0 if i < 2 else 20.0) for i in range(10)]
    table.append(record(30, DAY + 50, 1, 3.0))
    c = manchester_compliance(table, 0, 3)

    assert c.n[:, 2].tolist() == [10, 10, 0]
    assert c.within[0, 2] == pytest.approx(0.9) and c.within[1, 2] == pytest.approx(0.8)
    assert c.out[:, 2].tolist() == [False, True, False]
    assert c.out[:, 0].tolist() == [False, True, False]
    assert np.isnan(c.within[2, 2])
    assert c.days_with_patients.tolist() == [1, 0, 2, 0, 0]
    assert c.share_out[2] == 0.5 and c.share_out[0] == 1.0
    assert np.isnan(c.share_out[1])


def test_otro_objetivo_y_otros_maximos():
    table = [record(i, 10 + i, 3, 70.0 if i < 2 else 20.0) for i in range(10)]
    assert not manchester_compliance(table, 0, 1, target=0.8).out[0, 2]
    assert not manchester_compliance(table, 0, 1, max_wait=(0, 10, 80, 120, 240)).out[0, 2]


def test_cumplimiento_usa_el_reloj_c_por_defecto():
    # Nivel 2 (máximo 10): llega en 100, espera enfermera 2, triaje 5 y médico 5 minutos
    # después de clasificarse. A = 12 (no cumple), B = 10 (cumple justo), C = 5 (cumple).
    table = (record(0, 100, 2, 12.0, pretriage=2.0, triage=5.0),)

    c = manchester_compliance(table, 0, 1)
    assert c.measure == "classified_to_doctor"
    assert c.within[0, 1] == 1.0 and not c.out[0, 1]

    a = manchester_compliance(table, 0, 1, measure="door_to_doctor")
    assert a.measure == "door_to_doctor"
    assert a.within[0, 1] == 0.0 and a.out[0, 1]

    b = manchester_compliance(table, 0, 1, measure="triage_start_to_doctor")
    assert b.within[0, 1] == 1.0
    # Sigue devolviendo los cinco niveles.
    assert c.n.shape == (1, 5) and len(c.max_wait) == 5


@pytest.mark.parametrize("measure", ["stay", "triage_wait", "reloj"])
def test_cumplimiento_solo_con_un_reloj(measure):
    with pytest.raises(ValueError, match="measure"):
        manchester_compliance(TABLE, 1, 3, measure=measure)


@pytest.mark.parametrize(
    "kwargs", [{"target": 0}, {"target": 1.1}, {"max_wait": (0, 10)}, {"max_wait": (-1,) * 5}]
)
def test_cumplimiento_argumentos(kwargs):
    with pytest.raises(ValueError):
        manchester_compliance(TABLE, 1, 3, **kwargs)


# --- Pretriaje ------------------------------------------------------------------------


def test_normas_del_pretriaje():
    assert (PRETRIAGE_MAX_WAIT, PRETRIAGE_TARGET, PRETRIAGE_LONG_WAIT) == (10.0, 0.85, 5.0)


def pretriage_table():
    # Día 0: nivel 3 con pretriajes 2, 5, 10 y 12 (≤ 10: 3 de 4 = 75 %, fuera; > 5: 2,
    # 50 %); nivel 4 con 4 y 6 (≤ 10: 100 %; > 5: 50 %). Un nivel 1 en la puerta (0) no
    # cuenta. Día 1: un nivel 2 con 11 (fuera) y uno de nivel 5 que sigue dentro (no
    # cuenta). Total 2-5 del día 0: 5 de 6 dentro = 83,3 %, fuera; > 5: 3 de 6.
    rows = [
        record(0, 10, 3, 30.0, pretriage=2.0),
        record(1, 20, 3, 30.0, pretriage=5.0),
        record(2, 30, 3, 30.0, pretriage=10.0),
        record(3, 40, 3, 30.0, pretriage=12.0),
        record(4, 50, 4, 30.0, pretriage=4.0),
        record(5, 60, 4, 30.0, pretriage=6.0),
        record(6, 70, 1, 1.0),
        record(7, DAY + 10, 2, 30.0, pretriage=11.0),
        record(8, DAY + 20, 5, 30.0, pretriage=1.0, departed=False),
    ]
    return rows


def test_pretriaje_por_dia_y_nivel():
    p = pretriage(pretriage_table(), 0, 2)

    assert p.groups == (2, 3, 4, 5, None)
    assert p.n.tolist() == [[0, 4, 2, 0, 6], [1, 0, 0, 0, 1]]
    assert p.within[0, 1] == 0.75 and p.within[0, 2] == 1.0
    assert p.within[0, 4] == pytest.approx(5 / 6)
    assert p.over[0, 1] == 0.5 and p.over[0, 2] == 0.5 and p.over[0, 4] == 0.5
    assert p.within[1, 0] == 0.0 and p.over[1, 0] == 1.0
    assert np.isnan(p.within[1, 1]) and np.isnan(p.over[0, 0])
    assert p.out.tolist() == [[False, True, False, False, True], [True, False, False, False, True]]
    assert p.days_with_patients.tolist() == [1, 1, 1, 0, 2]
    assert p.share_out[4] == 1.0 and p.share_out[2] == 0.0 and np.isnan(p.share_out[3])


def test_pretriaje_acumulado_en_el_tramo():
    # Sobre los dos días: 7 pacientes de niveles 2 a 5, 5 dentro de 10 y 4 por encima de 5.
    p = pretriage(pretriage_table(), 0, 2)
    assert p.pooled_n.tolist() == [1, 4, 2, 0, 7]
    assert p.pooled_within[4] == pytest.approx(5 / 7)
    assert p.pooled_over[4] == pytest.approx(4 / 7)
    assert np.isnan(p.pooled_within[3])


def test_pretriaje_con_otras_normas():
    p = pretriage(pretriage_table(), 0, 1, max_wait=12.0, long_wait=10.0, target=0.7)
    assert p.within[0, 1] == 1.0 and p.over[0, 1] == 0.25 and not p.out[0, 4]


@pytest.mark.parametrize(
    "kwargs",
    [{"target": 0}, {"target": 1.5}, {"max_wait": -1}, {"long_wait": -1}],
)
def test_pretriaje_argumentos(kwargs):
    with pytest.raises(ValueError):
        pretriage(pretriage_table(), 0, 2, **kwargs)


# --- Relojes por nivel ------------------------------------------------------------------


def test_mediana_y_p90_de_los_tres_relojes():
    # Nivel 3: A = 10, 20, 30 y 40 con pretriaje 2 y triaje 5 (B = A − 2, C = A − 7).
    # Mediana de A 25 y p90 37 (interpolación lineal: 30 + 0,7 · 10). Un nivel 1 en la
    # puerta (A = B = C = 1). El que sigue dentro no cuenta.
    table = [record(i, 10 * i, 3, 10.0 * (i + 1), pretriage=2.0, triage=5.0) for i in range(4)]
    table += [record(9, 100, 1, 1.0), record(10, 200, 3, 99.0, departed=False)]

    by_level = clock_quantiles(table, 0, 1)

    assert [c.level for c in by_level] == [1, 2, 3, 4, 5]
    three = by_level[2]
    assert three.n == 4
    assert three.median == {
        "door_to_doctor": 25.0,
        "triage_start_to_doctor": 23.0,
        "classified_to_doctor": 18.0,
    }
    assert three.p90["door_to_doctor"] == pytest.approx(37.0)
    assert three.p90["classified_to_doctor"] == pytest.approx(30.0)
    assert by_level[0].n == 1 and by_level[0].median["classified_to_doctor"] == 1.0
    assert by_level[1].n == 0 and by_level[1].median["door_to_doctor"] is None


def test_cumplimiento_acumulado_en_el_tramo():
    # Nivel 3: día 0 con 9 de 10 dentro, día 1 con 8 de 10: 17 de 20.
    table = [record(i, 10 + i, 3, 70.0 if i == 0 else 20.0) for i in range(10)]
    table += [record(10 + i, DAY + 10 + i, 3, 70.0 if i < 2 else 20.0) for i in range(10)]
    c = manchester_compliance(table, 0, 2)
    assert c.pooled_within[2] == pytest.approx(17 / 20)
    assert np.isnan(c.pooled_within[0])
