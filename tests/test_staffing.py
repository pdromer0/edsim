"""Regla de la plantilla equivalente: ⌈carga del turno / u⌉ (tarea 4.6b)."""

from datetime import date
from pathlib import Path

import pytest

from edsim.arrivals.profile import ArrivalProfile, load_profile
from edsim.calibration.staffing import (
    DOCTORS,
    NURSES,
    RuleStaffing,
    doctor_loads,
    door_share,
    equivalent_staff,
    knob_loads,
    mean_triage_time,
    nurse_loads,
    rule_staffings,
    shift_arrival_rates,
    shift_hours,
    u_grid,
)
from edsim.profiles.config import load_profiles
from edsim.profiles.durations import physician_load

CONFIG = Path(__file__).resolve().parents[1] / "config"
STARTS = (8, 15, 22)


@pytest.fixture(scope="module")
def arrivals() -> ArrivalProfile:
    return load_profile(CONFIG / "llegadas.toml")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(CONFIG / "perfiles.toml")


@pytest.fixture(scope="module")
def loads(profiles, arrivals):
    return nurse_loads(profiles, arrivals, STARTS), doctor_loads(profiles, arrivals, STARTS)


# --- Llegadas por turno ------------------------------------------------------------------


def test_horas_de_cada_turno_con_la_noche_que_cruza_la_medianoche():
    morning, afternoon, night = shift_hours(STARTS)
    assert morning == (8, 9, 10, 11, 12, 13, 14)
    assert afternoon == (15, 16, 17, 18, 19, 20, 21)
    assert night == (22, 23, 0, 1, 2, 3, 4, 5, 6, 7)


def test_llegadas_por_hora_a_mano():
    # Reparto 1 en cada hora y 10 a las 9 h y a las 23 h: suma 42. Con 240 llegadas al
    # día, la mañana (7 h, con la de las 9) recibe 240 · 16/42 en 7 horas; la tarde,
    # 240 · 7/42 en 7; la noche (10 h, con la de las 23), 240 · 19/42 en 10.
    shares = [1.0] * 24
    shares[9], shares[23] = 10.0, 10.0
    profile = ArrivalProfile(
        daily_base=240,
        daily_cv=0.0,
        start_date=date(2026, 1, 5),
        hour_factors=shares,
        weekday_factors=[1] * 7,
        month_factors=[1] * 12,
    )
    assert shift_arrival_rates(profile, STARTS) == pytest.approx(
        (240 * 16 / 42 / 7, 240 * 7 / 42 / 7, 240 * 19 / 42 / 10), rel=1e-12
    )


def test_llegadas_por_hora_con_config(arrivals):
    # 300 al día; reparto_horario de las horas de cada turno: 40,5 %, 38,5 % y 21 %.
    assert shift_arrival_rates(arrivals, STARTS) == pytest.approx(
        (300 * 0.405 / 7, 300 * 0.385 / 7, 300 * 0.21 / 10), rel=1e-9
    )
    assert shift_arrival_rates(arrivals, STARTS) == pytest.approx((17.3571, 16.5, 6.3), abs=1e-4)


# --- Cargas ------------------------------------------------------------------------------


def test_ingredientes_de_las_cargas(profiles, arrivals):
    # p₁ = 0,4 % (el reparto asignado objetivo), media del triaje 5 · exp(σ²/2) con
    # σ = ln 2 / 1,2816, y la carga del médico de «Pruebas y duraciones».
    assert door_share(profiles, arrivals) == pytest.approx(0.004, abs=1e-4)
    assert mean_triage_time(profiles) == pytest.approx(5.7875, abs=1e-4)
    assert physician_load(profiles, arrivals).load == pytest.approx(32.37, abs=0.01)


def test_cargas_de_enfermeria_con_config(loads):
    assert loads[0] == pytest.approx((1.6676, 1.5852, 0.6053), abs=1e-3)


def test_cargas_de_medicos_con_config(loads):
    assert loads[1] == pytest.approx((9.3642, 8.9017, 3.3989), abs=1e-3)


def test_cargas_por_mando(profiles, arrivals, loads):
    assert knob_loads(NURSES, profiles, arrivals, STARTS) == loads[0]
    assert knob_loads(DOCTORS, profiles, arrivals, STARTS) == loads[1]
    with pytest.raises(ValueError, match="knob must be one of"):
        knob_loads("boxes", profiles, arrivals, STARTS)


# --- La regla ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("u", "staff"),
    [(0.60, (3, 3, 2)), (0.70, (3, 3, 1)), (0.80, (3, 2, 1)), (0.85, (2, 2, 1))],
)
def test_regla_a_mano_enfermeria(loads, u, staff):
    assert equivalent_staff(loads[0], u) == staff


@pytest.mark.parametrize(
    ("u", "staff"), [(0.80, (12, 12, 5)), (0.90, (11, 10, 4)), (0.95, (10, 10, 4))]
)
def test_regla_a_mano_medicos(loads, u, staff):
    assert equivalent_staff(loads[1], u) == staff


def test_regla_redondea_hacia_arriba_y_nunca_da_cero():
    # 2 / 0,5 = 4 exacto; 2,2 / 0,5 = 4,4 → 5; una carga casi nula, o nula, da 1.
    assert equivalent_staff((2.0, 2.2, 0.01), 0.5) == (4, 5, 1)
    assert equivalent_staff((1.0, 1.5, 0.0), 1.0) == (1, 2, 1)


@pytest.mark.parametrize("u", [0, -0.5, 1.2, True, "0.8"])
def test_regla_con_u_invalido(u):
    with pytest.raises(ValueError, match="u must be a number in"):
        equivalent_staff((1.0, 1.0, 1.0), u)


def test_regla_necesita_tres_cargas():
    with pytest.raises(ValueError, match="need 3 loads"):
        equivalent_staff((1.0, 1.0), 0.8)


def test_rejilla_de_u_sin_error_acumulado():
    grid = u_grid()
    assert len(grid) == 177
    assert grid[0] == 0.55 and grid[-1] == 0.99 and grid[1] == 0.5525
    assert 0.6075 in grid and 0.8325 in grid


def test_plantillas_distintas_de_enfermeria(loads):
    # Con u de 0,55 a 0,99 en pasos de 0,0025: cinco plantillas, con los bordes del grid.
    assert rule_staffings(loads[0]) == (
        RuleStaffing((4, 3, 2), 0.55, 0.555),
        RuleStaffing((3, 3, 2), 0.5575, 0.605),
        RuleStaffing((3, 3, 1), 0.6075, 0.7925),
        RuleStaffing((3, 2, 1), 0.795, 0.8325),
        RuleStaffing((2, 2, 1), 0.835, 0.99),
    )


def test_plantillas_distintas_de_medicos(loads):
    staffings = rule_staffings(loads[1])
    assert [(s.staff, s.u_low, s.u_high) for s in staffings] == [
        ((18, 17, 7), 0.55, 0.55),
        ((17, 17, 7), 0.5525, 0.555),
        ((17, 16, 7), 0.5575, 0.565),
        ((17, 16, 6), 0.5675, 0.585),
        ((16, 16, 6), 0.5875, 0.5925),
        ((16, 15, 6), 0.595, 0.6225),
        ((15, 15, 6), 0.625, 0.635),
        ((15, 14, 6), 0.6375, 0.6675),
        ((14, 14, 6), 0.67, 0.6775),
        ((14, 14, 5), 0.68, 0.6825),
        ((14, 13, 5), 0.685, 0.72),
        ((13, 13, 5), 0.7225, 0.74),
        ((13, 12, 5), 0.7425, 0.78),
        ((12, 12, 5), 0.7825, 0.8075),
        ((12, 11, 5), 0.81, 0.8475),
        ((12, 11, 4), 0.85, 0.85),
        ((11, 11, 4), 0.8525, 0.89),
        ((11, 10, 4), 0.8925, 0.935),
        ((10, 10, 4), 0.9375, 0.9875),
        ((10, 9, 4), 0.99, 0.99),
    ]


def test_cada_plantilla_sale_de_todo_su_intervalo(loads):
    # Comprobación cruzada: los bordes dan la plantilla y el paso siguiente, otra.
    for s in rule_staffings(loads[0]) + rule_staffings(loads[1]):
        knob = loads[0] if s.staff[0] <= 4 else loads[1]
        assert equivalent_staff(knob, s.u_low) == s.staff
        assert equivalent_staff(knob, s.u_high) == s.staff
        if s.u_high < 0.99:
            assert equivalent_staff(knob, round(s.u_high + 0.0025, 10)) != s.staff
