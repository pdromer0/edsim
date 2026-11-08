"""Pacer (tarea 6.3): objetivos absolutos, reanclaje, pausa, tramos y retraso.

Todo con el reloj falso y valores calculados a mano (docs/specs/hito-6.md, pieza 1 y
«Tests y validación»). El reloj falso cuenta en nanosegundos enteros: los instantes salen
exactos salvo el redondeo al nanosegundo del último tramo, de ahí la tolerancia de 1e-9.
"""

import math

import numpy as np
import pytest

from edsim.live.clock import FakeClock
from edsim.live.control import PAUSE, RESUME, SPEED, STOP, Command, NoControl, ScriptedControl
from edsim.live.pacer import MAX_SLICE, Pacer

TOL = 1e-9


def approx(x):
    return pytest.approx(x, abs=TOL)


@pytest.mark.parametrize(("speed", "expected"), [(60, 3.0), (1, 180.0)])
def test_ancla_a_60_y_a_1(speed, expected):
    # Ancla (0 s, 0 min): un evento en el minuto 3 toca a los 3 s a ×60 y a los 180 s a ×1.
    clock = FakeClock()
    pacer = Pacer(clock, speed, (0.0, 0.0))

    assert pacer.wait_until(3, NoControl()) is False
    assert clock.monotonic() == approx(expected)
    assert pacer.lag() == approx(0)
    assert max(clock.sleeps) <= MAX_SLICE


def test_reanclaje_al_cambiar_de_velocidad():
    # ×1 durante 60 s reales (minuto 1) y ×60 durante 10 s: minuto 11.
    clock = FakeClock()
    pacer = Pacer(clock, 1, (0.0, 0.0))
    control = ScriptedControl(clock, [(60, Command(SPEED, 60))])

    assert pacer.wait_until(11, control) is False
    assert clock.monotonic() == approx(70)
    assert pacer.sim_now() == approx(11)
    assert pacer.anchor == (approx(60), approx(1))


def test_pausa_y_reanudacion():
    # ×60 desde (0 s, 0 min); pausa a los 30 s (minuto 30), reanudación a los 50 s.
    clock = FakeClock()
    pacer = Pacer(clock, 60, (0.0, 0.0))
    control = ScriptedControl(clock, [(30, Command(PAUSE)), (50, Command(RESUME))])

    assert pacer.wait_until(31, control) is False
    assert clock.monotonic() == approx(51)
    # Guarda: las dos órdenes se vieron en su instante exacto, no un tramo después.
    assert [(planned, seen) for planned, seen, _ in control.delivered] == [(30, 30.0), (50, 50.0)]
    assert pacer.anchor == (approx(50), approx(30))


def test_cambiar_la_velocidad_en_pausa_no_reanuda():
    clock = FakeClock()
    pacer = Pacer(clock, 60, (0.0, 0.0))
    control = ScriptedControl(
        clock, [(10, Command(PAUSE)), (20, Command(SPEED, 10)), (30, Command(RESUME))]
    )

    # Pausa en el minuto 10; a ×10 desde (30 s, minuto 10), el minuto 31 toca a los 156 s.
    assert pacer.wait_until(31, control) is False
    assert clock.monotonic() == approx(156)

    pacer.pause()
    before = pacer.sim_now()
    clock.sleep(5)
    pacer.set_speed(2)
    assert pacer.paused
    assert pacer.speed == 2.0
    assert pacer.sim_now() == before


def test_tramos_de_0_2_s():
    # A ×1, el siguiente evento está a 10 min reales; una orden parar a los 0,5 s se
    # atiende en el primer tramo siguiente, a los 0,6 s.
    clock = FakeClock()
    pacer = Pacer(clock, 1, (0.0, 0.0))
    control = ScriptedControl(clock, [(0.5, Command(STOP))])

    assert pacer.wait_until(10, control) is True
    assert clock.monotonic() == approx(0.6)
    assert clock.sleeps == [0.2, 0.2, 0.2]


DRIFT_INSTANTS = sorted(
    round(float(x), 2) for x in np.random.default_rng(63).uniform(0, 1440, 3800)
)
"""3.800 instantes de un día, uniformes y redondeados a la centésima de minuto (hay repetidos)."""


def test_deriva_con_exceso_en_cada_espera():
    # Cada sleep se pasa 1 ms. Con objetivos absolutos, ningún evento sale con más de 1 ms
    # de retraso. El retraso se mide aquí, contra el ancla inicial, no con lag().
    assert len(set(DRIFT_INSTANTS)) < len(DRIFT_INSTANTS)  # guarda: hay instantes repetidos
    clock = FakeClock(oversleep=0.001)
    pacer = Pacer(clock, 60, (0.0, 0.0))

    delays = []
    for t in DRIFT_INSTANTS:
        assert pacer.wait_until(t, NoControl()) is False
        delays.append(clock.monotonic() - t)  # a ×60 desde (0, 0), el objetivo es t segundos

    assert min(delays) >= -TOL  # nunca antes de su instante
    assert max(delays) <= 0.001 + TOL
    assert max(delays) > 0.0009  # guarda: el exceso se nota


def test_retraso_si_publicar_tarda():
    # Eventos en los minutos 1, 2, 3… a ×60 (1 s cada uno) y publicar cuesta 2 s.
    clock = FakeClock()
    pacer = Pacer(clock, 60, (0.0, 0.0))

    released, lags = [], []
    for k in range(1, 11):
        assert pacer.wait_until(k, NoControl()) is False
        released.append(clock.monotonic())
        lags.append(pacer.lag())
        clock.sleep(2)  # el sumidero

    # Todos salen, en orden: el k-ésimo a los 2k − 1 s, con k − 1 s de retraso.
    assert released == [approx(2 * k - 1) for k in range(1, 11)]
    assert lags == [approx(k - 1) for k in range(1, 11)]


def test_maxima_y_vuelta():
    clock = FakeClock()
    pacer = Pacer(clock, 60, (0.0, 0.0))
    control = ScriptedControl(clock, [(10, Command(SPEED, "max"))])

    # A los 10 s (minuto 10), velocidad máxima: los minutos 10,5 y 11 salen a los 10 s.
    assert pacer.wait_until(10.5, control) is False
    assert clock.monotonic() == 10.0
    assert pacer.wait_until(11, control) is False
    assert clock.monotonic() == 10.0
    assert pacer.lag() == 0.0
    assert pacer.sim_now() == 11.0

    # Vuelta a ×60 a los 10 s: ancla (10 s, minuto 11); el minuto 12 toca a los 11 s.
    pacer.set_speed(60)
    assert pacer.anchor == (10.0, 11.0)
    assert pacer.wait_until(12, control) is False
    assert clock.monotonic() == approx(11)


def test_ordenes_sin_espera_a_velocidad_maxima():
    # A velocidad máxima no hay que esperar, pero las órdenes se miran en cada evento.
    clock = FakeClock()
    pacer = Pacer(clock, "max", (0.0, 0.0))
    control = ScriptedControl(clock, [(0, Command(STOP))])

    assert pacer.wait_until(5, control) is True
    assert clock.sleeps == []


def test_ordenes_sin_espera_con_el_objetivo_pasado():
    # Con retraso, el objetivo ya ha pasado y no hay que esperar: la orden llega igual.
    clock = FakeClock()
    pacer = Pacer(clock, 60, (0.0, 0.0))
    control = ScriptedControl(clock, [(4, Command(STOP))])

    assert pacer.wait_until(1, control) is False
    clock.sleep(2)  # sumidero lento: 3 s
    assert pacer.wait_until(2, control) is False  # objetivo 2 s pasado; la orden aún no
    clock.sleep(2)  # 5 s
    sleeps = len(clock.sleeps)
    assert pacer.wait_until(3, control) is True  # objetivo 3 s pasado; la orden de los 4 s
    assert len(clock.sleeps) == sleeps  # sin dormir


def test_reanclar_y_ahora_simulado():
    clock = FakeClock(100.0)
    pacer = Pacer(clock, 60, (0.0, 0.0))
    pacer.reanchor(2880)
    assert pacer.anchor == (100.0, 2880.0)
    clock.sleep(30)
    assert pacer.sim_now() == 2910.0

    pacer.set_speed("max")
    assert pacer.sim_now() == 2880.0  # el último liberado: el ancla del directo
    with pytest.raises(ValueError, match="maximum"):
        pacer.target(3000)


@pytest.mark.parametrize(
    ("speed", "anchor"),
    [(0, (0.0, 0.0)), ("rapido", (0.0, 0.0)), (60, (math.nan, 0.0)), (60, [0.0, 0.0]), (60, (0,))],
)
def test_pacer_no_valido(speed, anchor):
    with pytest.raises(ValueError):
        Pacer(FakeClock(), speed, anchor)


@pytest.mark.parametrize("sim_time", [math.nan, math.inf, "3", None, True])
def test_esperar_a_un_instante_no_valido(sim_time):
    with pytest.raises(ValueError, match="sim_time"):
        Pacer(FakeClock(), 60, (0.0, 0.0)).wait_until(sim_time, NoControl())
