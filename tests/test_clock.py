"""Relojes del directo (tarea 6.3): el del sistema y el falso de los tests.

El reloj falso avanza solo cuando se le pide esperar, de golpe y sin dormir, y cuenta en
nanosegundos enteros para que las sumas de tramos de 0,2 s den instantes exactos
(docs/specs/hito-6.md, pieza 7).
"""

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest

from edsim.live.clock import FAKE_WALL_START, FakeClock, SystemClock


def test_el_reloj_falso_avanza_sin_dormir_y_anota_las_esperas():
    clock = FakeClock(10.0)
    assert clock.monotonic() == 10.0

    clock.sleep(2.5)
    clock.sleep(0)
    clock.sleep(0.25)

    assert clock.monotonic() == 12.75
    assert clock.sleeps == [2.5, 0.0, 0.25]


def test_el_reloj_falso_cuenta_en_nanosegundos_enteros():
    # En coma flotante, 150 tramos de 0,2 s suman 29,999999999999925.
    total = 0.0
    for _ in range(150):
        total += 0.2
    assert total < 30

    clock = FakeClock()
    for _ in range(150):
        clock.sleep(0.2)
    assert clock.monotonic() == 30.0


def test_una_espera_diminuta_avanza_al_menos_un_nanosegundo():
    clock = FakeClock(1.0)
    clock.sleep(1e-12)
    assert clock.monotonic() == 1.0 + 1e-9


def test_el_exceso_se_suma_a_cada_espera():
    clock = FakeClock(oversleep=0.001)
    clock.sleep(1.0)
    clock.sleep(0.5)

    assert clock.monotonic() == pytest.approx(1.502, abs=1e-12)
    assert clock.sleeps == [1.0, 0.5]  # lo pedido, sin el exceso


def test_la_hora_de_pared_avanza_con_el_reloj_monotono():
    madrid = timezone(timedelta(hours=1))
    start = datetime(2026, 3, 11, 10, 30, tzinfo=madrid)
    clock = FakeClock(100.0, wall_start=start)
    assert clock.wall() == start

    clock.sleep(90.5)

    assert clock.wall() == start + timedelta(seconds=90.5)
    assert FakeClock().wall() == FAKE_WALL_START


@pytest.mark.parametrize("seconds", [-1, -1e-9, math.nan, math.inf, True, "1", None])
def test_una_espera_no_valida_es_un_error(seconds):
    clock = FakeClock()
    with pytest.raises(ValueError, match="sleep"):
        clock.sleep(seconds)
    assert clock.monotonic() == 0.0
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "kwargs",
    [{"start": -1}, {"oversleep": math.nan}, {"interrupt_at": math.inf}, {"start": True}],
)
def test_parametros_no_validos(kwargs):
    with pytest.raises(ValueError):
        FakeClock(**kwargs)


def test_la_pared_sin_zona_es_un_error():
    with pytest.raises(ValueError, match="wall_start"):
        FakeClock(wall_start=datetime(2026, 3, 11, 10, 30))


def test_ctrl_c_en_la_primera_espera_que_llega_al_instante():
    clock = FakeClock(interrupt_at=45.0)
    clock.sleep(44.8)  # no llega

    with pytest.raises(KeyboardInterrupt):
        clock.sleep(10)
    # Como un Ctrl+C a mitad de time.sleep: el reloj se queda en el instante.
    assert clock.monotonic() == 45.0

    clock.sleep(10)  # una sola vez
    assert clock.monotonic() == 55.0


def test_ctrl_c_cuando_la_espera_llega_justo_al_instante():
    clock = FakeClock(interrupt_at=0.6)
    clock.sleep(0.2)
    clock.sleep(0.2)
    with pytest.raises(KeyboardInterrupt):
        clock.sleep(0.2)
    assert clock.monotonic() == 0.6


def test_el_reloj_del_sistema():
    clock = SystemClock()
    before = clock.monotonic()
    clock.sleep(0)
    assert clock.monotonic() >= before

    wall = clock.wall()
    assert wall.utcoffset() == timedelta(0)
    assert abs(wall - datetime.now(UTC)) < timedelta(seconds=5)
    with pytest.raises(ValueError):
        clock.sleep(-1)
