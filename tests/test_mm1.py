import statistics

import pytest

from edsim.queueing.mm1 import CustomerRecord, simulate_mm1

# Carga alta (ρ = 0,9) para que se formen colas y los invariantes se pongan a prueba.
LAM, MU, HORIZON, SEED = 0.9, 1.0, 2000.0, 2026


@pytest.fixture(scope="module")
def records() -> tuple[CustomerRecord, ...]:
    return simulate_mm1(lam=LAM, mu=MU, horizon=HORIZON, seed=SEED)


def started(records):
    return [r for r in records if r.service_start is not None]


# --- Reproducibilidad -------------------------------------------------------


def test_misma_semilla_mismos_registros(records):
    again = simulate_mm1(lam=LAM, mu=MU, horizon=HORIZON, seed=SEED)

    assert again == records


def test_semillas_distintas_registros_distintos():
    a = simulate_mm1(lam=LAM, mu=MU, horizon=HORIZON, seed=1)
    b = simulate_mm1(lam=LAM, mu=MU, horizon=HORIZON, seed=2)

    assert a != b


def test_servicio_independiente_de_llegadas():
    # Misma semilla, distinta λ: cambian las llegadas, pero cada cliente
    # recibe el mismo tiempo de servicio (base de los números aleatorios comunes).
    slow = simulate_mm1(lam=0.5, mu=MU, horizon=HORIZON, seed=SEED)
    fast = simulate_mm1(lam=0.9, mu=MU, horizon=HORIZON, seed=SEED)
    n = min(len(slow), len(fast))

    assert [r.arrival for r in slow[:n]] != [r.arrival for r in fast[:n]]
    assert [r.service_time for r in slow[:n]] == [r.service_time for r in fast[:n]]


# --- Invariantes ------------------------------------------------------------


def test_hay_colas(records):
    # Sin esperas, los invariantes de abajo pasarían sin probar nada.
    assert any(r.service_start > r.arrival for r in started(records))


def test_ids_y_llegadas(records):
    assert [r.customer_id for r in records] == list(range(len(records)))
    arrivals = [r.arrival for r in records]
    assert all(a < b for a, b in zip(arrivals, arrivals[1:], strict=False))


def test_inicio_no_anterior_a_llegada(records):
    assert all(r.service_start >= r.arrival for r in started(records))


def test_fin_no_anterior_a_inicio(records):
    done = [r for r in records if r.is_complete]

    assert done
    assert all(r.departure >= r.service_start for r in done)


def test_orden_fifo(records):
    s = started(records)
    starts = [r.service_start for r in s]

    # Se empieza a atender en orden de llegada...
    assert all(a <= b for a, b in zip(starts, starts[1:], strict=False))
    # ...y nadie que espera ha llegado antes que alguien ya atendido.
    last_started_id = max(r.customer_id for r in s)
    assert all(r.service_start is not None for r in records[: last_started_id + 1])


def test_nunca_dos_en_servicio(records):
    s = sorted(started(records), key=lambda r: r.service_start)

    for previous, current in zip(s, s[1:], strict=False):
        assert previous.departure is not None, "alguien empezó con el servidor ocupado"
        assert current.service_start >= previous.departure
    assert sum(1 for r in s if not r.is_complete) <= 1


def test_servicio_registrado(records):
    assert all(r.service_time > 0 for r in records)
    for r in records:
        if r.is_complete:
            assert r.departure - r.service_start == pytest.approx(r.service_time)


def test_incompletos_sin_valores_inventados(records):
    pending = [r for r in records if not r.is_complete]

    assert pending, "con ρ = 0,9 debería quedar alguien sin terminar"
    for r in pending:
        assert r.departure is None
    waiting = [r for r in pending if r.service_start is None]
    in_service = [r for r in pending if r.service_start is not None]
    assert len(in_service) <= 1
    assert all(r.departure is None for r in waiting)
    # Ningún instante registrado cae fuera del horizonte simulado.
    for r in records:
        for t in (r.arrival, r.service_start, r.departure):
            assert t is None or t < HORIZON


# --- Escala de las exponenciales ---------------------------------------------


def test_medias_de_llegadas_y_servicio():
    # λ = 2, μ = 5: con μ ≠ 1, pasar la tasa en vez de la escala daría medias
    # de 2 y 5 en lugar de 0,5 y 0,2. Con ~40 000 clientes, el error estándar
    # relativo de la media es 1/√n ≈ 0,5 %; rel=0,03 son unos 6 errores estándar.
    lam, mu = 2.0, 5.0
    recs = simulate_mm1(lam=lam, mu=mu, horizon=20_000.0, seed=SEED)
    arrivals = [0.0] + [r.arrival for r in recs]
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:], strict=False)]

    assert len(recs) > 35_000
    assert statistics.fmean(gaps) == pytest.approx(1 / lam, rel=0.03)
    # Todos los clientes, no solo los completos, para no sesgar la muestra.
    assert statistics.fmean(r.service_time for r in recs) == pytest.approx(1 / mu, rel=0.03)


# --- Validación de parámetros -----------------------------------------------


@pytest.mark.parametrize(
    ("lam", "mu", "horizon"),
    [
        (0.0, 1.0, 100.0),
        (-1.0, 1.0, 100.0),
        (0.5, 0.0, 100.0),
        (1.0, 1.0, 100.0),
        (1.5, 1.0, 100.0),
        (0.5, 1.0, 0.0),
        (0.5, 1.0, -5.0),
    ],
)
def test_parametros_invalidos(lam, mu, horizon):
    with pytest.raises(ValueError):
        simulate_mm1(lam=lam, mu=mu, horizon=horizon, seed=SEED)
