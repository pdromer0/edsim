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
    daily_waits,
    manchester_compliance,
)

DAY = 1440.0


def record(n: int, arrival: float, level: int, door: float, *, departed: bool = True, box=0.0):
    """Un episodio que llega en ``arrival`` y ve al médico ``door`` minutos después."""
    return EpisodeRecord(
        episode_id=f"EP-{n:06d}",
        arrival=arrival,
        triage_start=arrival,
        triage_end=arrival + 5,
        level=level,
        first_box=arrival + 5,
        first_assessment=arrival + door,
        decision=arrival + door + 20 if departed else None,
        departure=arrival + door + 20 if departed else None,
        destination="alta" if departed else None,
        displacements=0,
        triage_wait=0.0,
        box_wait=box if departed else None,
        doctor_wait=0.0 if departed else None,
        initial_doctor_wait=0.0,
        door_to_doctor=door,
        triage_start_to_doctor=door,  # triaje desde la llegada
        classified_to_doctor=door - 5,  # clasificado 5 minutos después
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


@pytest.mark.parametrize(
    "kwargs", [{"target": 0}, {"target": 1.1}, {"max_wait": (0, 10)}, {"max_wait": (-1,) * 5}]
)
def test_cumplimiento_argumentos(kwargs):
    with pytest.raises(ValueError):
        manchester_compliance(TABLE, 1, 3, **kwargs)
