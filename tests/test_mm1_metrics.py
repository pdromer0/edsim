import dataclasses

import pytest

from edsim.queueing.mm1 import CustomerRecord, MM1Metrics, mm1_metrics, simulate_mm1

# Traza construida a mano, coherente con un servidor FIFO (el servidor está libre de 6 a 7).
# Ventana de observación [2, 10], T = 8.
#
#   cliente  llegada  inicio  fin   servicio  papel
#   0        0        0       3     3         cruza el inicio de la ventana, en servicio
#   1        2,5      3       5     2         dentro; espera 0,5
#   2        4        5       6     1         dentro; espera 1
#   3        7        7       —     4         sigue dentro al final (saldría en 11)
HAND_RECORDS = (
    CustomerRecord(customer_id=0, arrival=0.0, service_time=3.0, service_start=0.0, departure=3.0),
    CustomerRecord(customer_id=1, arrival=2.5, service_time=2.0, service_start=3.0, departure=5.0),
    CustomerRecord(customer_id=2, arrival=4.0, service_time=1.0, service_start=5.0, departure=6.0),
    CustomerRecord(customer_id=3, arrival=7.0, service_time=4.0, service_start=7.0, departure=None),
)


def test_ejemplo_a_mano():
    m = mm1_metrics(HAND_RECORDS, warmup=2.0, horizon=10.0)

    # Wq y W: solo los clientes 1 y 2 (el 0 llegó antes del warmup; el 3 no terminó).
    #   Wq = (0,5 + 1) / 2 = 0,75;  W = (2,5 + 2) / 2 = 2,25.
    assert m.n_customers == 2
    assert m.wq == pytest.approx(0.75)
    assert m.w == pytest.approx(2.25)

    # L: tiempo en el sistema recortado a [2, 10]:
    #   0: [0, 3] → 1;  1: [2,5; 5] → 2,5;  2: [4, 6] → 2;  3: [7, 10] → 3.
    #   Suma 8,5 → L = 8,5 / 8 = 1,0625.
    assert m.l == pytest.approx(1.0625)

    # Lq: tiempo en cola recortado:
    #   0: 0;  1: [2,5; 3] → 0,5;  2: [4, 5] → 1;  3: 0.   Suma 1,5 → Lq = 0,1875.
    assert m.lq == pytest.approx(0.1875)

    # ρ: tiempo en servicio recortado:
    #   0: [0, 3] → 1;  1: [3, 5] → 2;  2: [5, 6] → 1;  3: [7, 10] → 3.
    #   Suma 7 → ρ = 7 / 8 = 0,875 (el hueco de 6 a 7 es el 12,5 % libre).
    assert m.rho == pytest.approx(0.875)

    # λ_obs: llegan los clientes 1, 2 y 3 dentro de [2, 10) → 3 / 8.
    assert m.lam_obs == pytest.approx(0.375)


# --- Simulación larga ---------------------------------------------------------

LAM, MU, WARMUP, HORIZON, SEED = 0.8, 1.0, 1_000.0, 51_000.0, 2026


@pytest.fixture(scope="module")
def long_run() -> MM1Metrics:
    records = simulate_mm1(lam=LAM, mu=MU, horizon=HORIZON, seed=SEED)
    return mm1_metrics(records, warmup=WARMUP, horizon=HORIZON)


def test_l_es_lq_mas_rho(long_run):
    # Cada estancia es su espera más su servicio, también tras recortar.
    assert long_run.l == pytest.approx(long_run.lq + long_run.rho)


def test_ley_de_little(long_run):
    # Little se cumple en cada trayectoria; solo difieren los bordes de la ventana
    # (clientes que la cruzan cuentan en el área pero no en W). Con T = 50 000 y
    # unos 4 clientes en el sistema, ese efecto es del orden del 0,02 %: rel=0,01
    # deja más de diez veces de margen.
    m = long_run

    assert m.n_customers > 35_000
    assert m.l == pytest.approx(m.lam_obs * m.w, rel=0.01)
    assert m.lq == pytest.approx(m.lam_obs * m.wq, rel=0.01)


def test_rho_entre_0_y_1(long_run):
    assert 0 <= long_run.rho <= 1


# --- Errores ------------------------------------------------------------------


@pytest.mark.parametrize("warmup", [-1.0, 10.0, 12.0])
def test_warmup_invalido(warmup):
    with pytest.raises(ValueError, match="warmup"):
        mm1_metrics(HAND_RECORDS, warmup=warmup, horizon=10.0)


def test_sin_clientes_completos():
    # Solo el cliente 3, que no termina: Wq y W no están definidos.
    with pytest.raises(ValueError, match="no customer"):
        mm1_metrics(HAND_RECORDS[3:], warmup=2.0, horizon=10.0)


def test_inmutable():
    m = mm1_metrics(HAND_RECORDS, warmup=2.0, horizon=10.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        m.rho = 0.5
