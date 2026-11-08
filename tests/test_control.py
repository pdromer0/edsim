"""Órdenes del directo (tarea 6.3): velocidad, pausa, reanudar y parar.

Las órdenes solo cambian el ritmo (H6-6). Aquí se prueban la orden, que solo existe
válida, y la fuente programada de los tests: cada poll da como mucho una orden, la más
antigua de las vencidas.
"""

import math

import numpy as np
import pytest

from edsim.live.clock import FakeClock
from edsim.live.control import (
    MAX_SPEED,
    PAUSE,
    RESUME,
    SPEED,
    STOP,
    Command,
    NoControl,
    ScriptedControl,
    check_speed,
)


@pytest.mark.parametrize(
    ("command", "order", "value"),
    [
        (Command(SPEED, 60), "velocidad", 60.0),
        (Command(SPEED, 0.5), "velocidad", 0.5),
        (Command(SPEED, np.int64(10)), "velocidad", 10.0),
        (Command(SPEED, "max"), "velocidad", "max"),
        (Command(PAUSE), "pausar", None),
        (Command(RESUME), "reanudar", None),
        (Command(STOP), "parar", None),
    ],
)
def test_ordenes_validas(command, order, value):
    assert (command.order, command.value) == (order, value)
    assert type(command.value) is type(value)


@pytest.mark.parametrize(
    "speed", [True, False, math.nan, math.inf, -math.inf, 0, -5, "10", "MAX", None]
)
def test_velocidad_no_valida(speed):
    with pytest.raises(ValueError, match="speed") as error:
        Command(SPEED, speed)
    assert repr(speed) in str(error.value)
    with pytest.raises(ValueError, match="speed"):
        check_speed(speed)


def test_check_speed():
    assert check_speed(60) == 60.0
    assert check_speed(MAX_SPEED) == "max"


@pytest.mark.parametrize(
    ("order", "value", "match"),
    [
        ("acelerar", None, "order"),
        ("PARAR", None, "order"),
        (None, None, "order"),
        (PAUSE, 10, "pausar takes no value"),
        (STOP, "max", "parar takes no value"),
    ],
)
def test_orden_no_valida(order, value, match):
    with pytest.raises(ValueError, match=match):
        Command(order, value)


def test_sin_ordenes():
    assert NoControl().poll() is None


def test_las_ordenes_programadas_llegan_al_vencer():
    clock = FakeClock()
    control = ScriptedControl(clock, [(1.0, Command(PAUSE)), (2.0, Command(RESUME))])
    assert control.poll() is None  # aún no

    clock.sleep(1.5)
    assert control.poll() == Command(PAUSE)
    assert control.poll() is None

    clock.sleep(0.5)  # justo en su instante
    assert control.poll() == Command(RESUME)
    assert control.poll() is None
    assert control.pending == 0
    assert control.delivered == [(1.0, 1.5, Command(PAUSE)), (2.0, 2.0, Command(RESUME))]


def test_dos_ordenes_en_el_mismo_instante_salen_una_por_poll():
    clock = FakeClock()
    control = ScriptedControl(clock, [(1.0, Command(SPEED, "max")), (1.0, Command(SPEED, 60))])
    clock.sleep(1)

    assert control.poll() == Command(SPEED, "max")
    assert control.poll() == Command(SPEED, 60)
    assert control.poll() is None


def test_el_guion_se_ordena_por_instante():
    clock = FakeClock()
    control = ScriptedControl(
        clock, [(2.0, Command(STOP)), (1.0, Command(PAUSE)), (1.0, Command(RESUME))]
    )
    clock.sleep(3)

    assert [control.poll() for _ in range(4)] == [
        Command(PAUSE),
        Command(RESUME),
        Command(STOP),
        None,
    ]


@pytest.mark.parametrize(
    "script", [[(math.nan, Command(STOP))], [(True, Command(STOP))], [(1.0, "parar")]]
)
def test_guion_no_valido(script):
    with pytest.raises(ValueError):
        ScriptedControl(FakeClock(), script)
