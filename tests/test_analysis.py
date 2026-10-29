import numpy as np
import pytest

# El mismo ejemplo a mano de la tarea 1.3 (ventana [2, 10]); ver test_mm1_metrics.py.
from test_mm1_metrics import HAND_RECORDS

from edsim.queueing.analysis import (
    interarrival_times,
    occupancy,
    residual_times,
    sample_step,
    service_times,
    step_time_average,
)
from edsim.queueing.mm1 import mm1_metrics, simulate_mm1

# Escalera del ejemplo a mano, evento a evento:
#   t = 0    llega 0 y empieza servicio  → cola 0, sistema 1
#   t = 2,5  llega 1, espera             → cola 1, sistema 2
#   t = 3    sale 0, empieza 1           → cola 0, sistema 1
#   t = 4    llega 2, espera             → cola 1, sistema 2
#   t = 5    sale 1, empieza 2           → cola 0, sistema 1
#   t = 6    sale 2                      → cola 0, sistema 0
#   t = 7    llega 3 y empieza servicio  → cola 0, sistema 1
HAND_TIMES = [0.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0]
HAND_IN_SYSTEM = [1, 2, 1, 2, 1, 0, 1]
HAND_IN_QUEUE = [0, 1, 0, 1, 0, 0, 0]


# --- occupancy -------------------------------------------------------------------


def test_occupancy_ejemplo_a_mano():
    occ = occupancy(HAND_RECORDS, horizon=10.0)

    np.testing.assert_array_equal(occ.times, HAND_TIMES)
    np.testing.assert_array_equal(occ.in_system, HAND_IN_SYSTEM)
    np.testing.assert_array_equal(occ.in_queue, HAND_IN_QUEUE)
    np.testing.assert_array_equal(occ.busy, [1, 1, 1, 1, 1, 0, 1])
    # Bordes para ax.stairs: los instantes de cambio más el horizonte.
    np.testing.assert_array_equal(occ.edges, [*HAND_TIMES, 10.0])


def test_occupancy_sin_registros():
    occ = occupancy((), horizon=5.0)

    np.testing.assert_array_equal(occ.times, [0.0])
    np.testing.assert_array_equal(occ.in_system, [0])
    np.testing.assert_array_equal(occ.in_queue, [0])


def test_occupancy_horizonte_invalido():
    with pytest.raises(ValueError, match="horizon"):
        occupancy(HAND_RECORDS, horizon=6.0)  # hay un evento en t = 7


def test_occupancy_invariantes_en_simulacion():
    records = simulate_mm1(lam=0.8, mu=1.0, horizon=2_000.0, seed=11)
    occ = occupancy(records, horizon=2_000.0)

    assert occ.times[0] == 0.0
    assert np.all(np.diff(occ.times) > 0)  # eventos simultáneos fundidos
    assert np.all(occ.in_queue >= 0)
    assert set(np.unique(occ.busy)) <= {0, 1}  # nunca dos en servicio


# --- step_time_average -------------------------------------------------------------


def test_media_en_el_tiempo_ejemplo_a_mano():
    occ = occupancy(HAND_RECORDS, horizon=10.0)

    # Los mismos valores que mm1_metrics en la tarea 1.3: L = 8,5/8, Lq = 1,5/8, ρ = 7/8.
    assert step_time_average(occ.times, occ.in_system, 2.0, 10.0) == pytest.approx(1.0625)
    assert step_time_average(occ.times, occ.in_queue, 2.0, 10.0) == pytest.approx(0.1875)
    assert step_time_average(occ.times, occ.busy, 2.0, 10.0) == pytest.approx(0.875)


def test_media_en_el_tiempo_coincide_con_mm1_metrics():
    # Dos caminos independientes: sumar la escalera y recortar la estancia de cada cliente.
    warmup, horizon = 200.0, 3_000.0
    records = simulate_mm1(lam=0.8, mu=1.0, horizon=horizon, seed=12)
    occ = occupancy(records, horizon=horizon)
    m = mm1_metrics(records, warmup=warmup, horizon=horizon)

    assert step_time_average(occ.times, occ.in_system, warmup, horizon) == pytest.approx(
        m.l, rel=1e-9
    )
    assert step_time_average(occ.times, occ.in_queue, warmup, horizon) == pytest.approx(
        m.lq, rel=1e-9
    )
    assert step_time_average(occ.times, occ.busy, warmup, horizon) == pytest.approx(m.rho, rel=1e-9)


@pytest.mark.parametrize(("start", "end"), [(5.0, 5.0), (6.0, 2.0)])
def test_media_en_el_tiempo_ventana_invalida(start, end):
    with pytest.raises(ValueError, match="start"):
        step_time_average(HAND_TIMES, HAND_IN_SYSTEM, start, end)


# --- sample_step -------------------------------------------------------------------


def test_sample_step_ejemplo_a_mano():
    grid = [0.0, 1.0, 2.5, 2.9, 6.5, 9.0]

    # En un instante de cambio vale lo de después del cambio (t = 2,5 → 2).
    np.testing.assert_array_equal(sample_step(HAND_TIMES, HAND_IN_SYSTEM, grid), [1, 1, 2, 2, 0, 1])


def test_sample_step_antes_del_primer_cambio():
    np.testing.assert_array_equal(sample_step([1.0, 2.0], [3, 4], [0.5, 1.5]), [0, 3])


# --- tiempos entre llegadas, de servicio y residuales -----------------------------


def test_interarrival_y_service_times_ejemplo_a_mano():
    np.testing.assert_array_equal(interarrival_times(HAND_RECORDS), [0.0, 2.5, 1.5, 3.0])
    np.testing.assert_array_equal(service_times(HAND_RECORDS), [3.0, 2.0, 1.0, 4.0])


def test_residual_times():
    np.testing.assert_allclose(residual_times([0.5, 1.5, 3.0], 1.0), [0.5, 2.0])


def test_residual_times_elapsed_negativo():
    with pytest.raises(ValueError, match="elapsed"):
        residual_times([1.0], -1.0)
