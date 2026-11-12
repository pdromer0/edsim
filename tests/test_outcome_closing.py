"""Las medidas del cierre del flujo (tarea 5.7, issue #74): hora de llegada, ley de Little de
la cama, contrafactual, destinos por tramo de G y media de un reloj.

Cada valor esperado está calculado a mano en el plan, con su aritmética a la vista, y no sale
de la función probada. Al final, una ejecución real del ejemplo del hito 5 comprueba que las
funciones aguantan un log verdadero y que se cuadran entre sí.
"""

from pathlib import Path

import pytest
from episode_factory import episode, truth_of
from v4_logs import HandLog

from edsim.arrivals.profile import load_profile
from edsim.engine.analysis import episode_table, step_curves
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.engine.scenarios import admission, run_scenario
from edsim.profiles.config import DESTINATIONS, load_profiles
from edsim.profiles.outcome import outcome_model
from edsim.runs import (
    abandonment_by_arrival_hour,
    abandonment_counterfactual,
    bed_little,
    clock_mean,
    destinations_by_severity,
    true_level_abandonment,
)

DATA = Path(__file__).parent / "data"
INF = float("inf")


# --- Abandono por hora de llegada ----------------------------------------------------------


def hour_table():
    """Hora 0 de dos días y hora 1; uno llega fuera de la ventana."""
    return [
        episode(1, 5.0, assessment=15.0, departure=60.0),  # reloj A 10
        episode(2, 15.0, assessment=35.0, departure=60.0),  # reloj A 20
        episode(3, 1470.0, assessment=1500.0, departure=1600.0),  # día 2, 0:30; reloj A 30
        episode(4, 40.0, left=80.0),  # se va a los 40
        episode(5, 60.0, assessment=160.0, departure=200.0),  # justo en la hora 1; reloj A 100
        episode(6, 119.9),  # hora 1, sigue esperando
        episode(7, 3000.0, assessment=3010.0, departure=3100.0),  # fuera de la ventana
    ]


def test_la_hora_cero_de_dos_dias():
    # Hora 0: llegadas en 5, 15, 40 y 1470 → 4; se va 1 (25 %); 3 atendidos con 10, 20 y 30 →
    # media 20. Tiempo hasta ser visto o irse: (10 + 20 + 30 + 40) / 4 = 25.
    row = abandonment_by_arrival_hour(hour_table(), 0.0, 2880.0)[0]
    assert (row.hour, row.arrivals, row.left, row.attended) == (0, 4, 1, 3)
    assert row.left_share == pytest.approx(0.25, abs=1e-12)
    assert row.mean_wait_attended == pytest.approx(20.0, abs=1e-12)
    assert row.mean_queue_time == pytest.approx(25.0, abs=1e-12)


def test_un_borde_de_hora_cuenta_en_la_hora_siguiente_y_quien_espera_no_entra_en_la_media():
    # El minuto 60 es la hora 1; el de 119,9 sigue esperando: llega pero no tiene tiempo hasta
    # ser visto. Hora 1: 2 llegadas, 0 se van, 1 atendido con 100 → ambas medias 100.
    row = abandonment_by_arrival_hour(hour_table(), 0.0, 2880.0)[1]
    assert (row.arrivals, row.left, row.attended) == (2, 0, 1)
    assert row.mean_wait_attended == pytest.approx(100.0, abs=1e-12)
    assert row.mean_queue_time == pytest.approx(100.0, abs=1e-12)
    assert row.left_share == 0.0


def test_el_minuto_1470_no_es_la_hora_24():
    rows = abandonment_by_arrival_hour(hour_table(), 0.0, 2880.0)
    assert len(rows) == 24 and [r.hour for r in rows] == list(range(24))
    # Con una arrival // 60 sin módulo, el 1470 caería en la hora 24 (que no existe).
    assert sum(r.arrivals for r in rows) == 6  # los 6 de la ventana; el de 3000 queda fuera


def test_horas_sin_llegadas_son_none():
    row = abandonment_by_arrival_hour(hour_table(), 0.0, 2880.0)[5]
    assert (row.arrivals, row.left, row.attended) == (0, 0, 0)
    assert row.left_share is None and row.mean_wait_attended is None
    assert row.mean_queue_time is None


def test_la_ventana_incluye_el_inicio_y_excluye_el_final_en_la_hora():
    # Ventana [5, 40): entran el de 5 y el de 15, no el de 40.
    row = abandonment_by_arrival_hour(hour_table(), 5.0, 40.0)[0]
    assert row.arrivals == 2


def test_ventana_no_valida_por_hora():
    with pytest.raises(ValueError, match="start"):
        abandonment_by_arrival_hour([], 10.0, 10.0)


# --- Ley de Little de la espera de cama ----------------------------------------------------


def admitted(log, who, arrival, decision):
    """Un nivel 3 que llega, se clasifica en 5 min, tiene box y se valora hasta `decision`."""
    log.arrive(who, arrival).triage(who, arrival, arrival + 5, 3).box(who, arrival + 5, who)
    return log.assess(who, arrival + 5, decision, who)


def test_little_con_un_ingresado_que_sigue_esperando_al_final():
    # Ventana [0, 1000), horizonte 1000. Esperas terminadas de 100 (10 → 110) y 200 (20 → 220), y
    # una petición en 900 que sigue esperando (100 cortada). λ = 3/1000 = 0,003;
    # W = (100 + 200 + 100) / 3 = 133,33; λ·W = 0,003 · 133,33 = 0,4 = 400/1000. Todos esperan en
    # su box, así que la curva da lo mismo: área 100 + 200 + 100 = 400 → 0,4.
    log = HandLog()
    admitted(log, 1, 0.0, 10.0).admit(1, 10.0, 110.0)
    admitted(log, 2, 1.0, 20.0).admit(2, 20.0, 220.0)
    admitted(log, 3, 800.0, 900.0)
    log.add(900.0, "disposition_decided", 3, destino="ingreso")
    log.add(900.0, "bed_requested", 3, servicio="planta")
    events = log.events()
    little = bed_little(episode_table(events), step_curves(events, 1000.0), 0.0, 1000.0)
    assert little.requests == 3
    assert little.rate == pytest.approx(0.003, abs=1e-15)
    assert little.mean_wait == pytest.approx(400 / 3, abs=1e-12)
    assert little.by_little == pytest.approx(0.4, abs=1e-12)
    assert little.boxes_mean == pytest.approx(0.4, abs=1e-12) and little.hallway_mean == 0.0
    assert little.by_curves == pytest.approx(little.by_little, abs=1e-12)


def test_little_con_un_ingresado_en_el_pasillo():
    # El escenario C del motor (calculado a mano en la 5.1): R1 pide cama en 35 y la recibe en
    # 185, esperando 25 min en su box y 125 en el pasillo (lo desaloja R3 en 60). λ = 1/1440,
    # W = 150, λ·W = 150/1440; curvas: boxes 25/1440 + pasillo 125/1440 = 150/1440.
    events = run_scenario(admission(load_center(DATA / "centro_ejemplo.toml"))).events
    little = bed_little(episode_table(events), step_curves(events, 1440.0), 0.0, 1440.0)
    assert (little.requests, little.mean_wait) == (1, 150.0)
    assert little.by_little == pytest.approx(150 / 1440, abs=1e-15)
    assert little.boxes_mean == pytest.approx(25 / 1440, abs=1e-15)
    assert little.hallway_mean == pytest.approx(125 / 1440, abs=1e-15)
    assert little.by_curves == pytest.approx(little.by_little, abs=1e-15)


def test_little_sin_ingresados():
    log = HandLog()
    admitted(log, 1, 0.0, 10.0).depart(1, 10.0)
    events = log.events()
    little = bed_little(episode_table(events), step_curves(events, 100.0), 0.0, 100.0)
    assert (little.requests, little.rate, little.mean_wait, little.by_little) == (0, 0.0, None, 0.0)
    assert little.by_curves == 0.0


def test_little_cuenta_los_pedidos_de_la_ventana_no_los_de_antes():
    # Ventana [500, 1000): el ingresado 1 pide cama en 10, antes de la ventana: no es de ella.
    log = HandLog()
    admitted(log, 1, 0.0, 10.0).admit(1, 10.0, 110.0)
    admitted(log, 2, 600.0, 650.0).admit(2, 650.0, 750.0)
    events = log.events()
    little = bed_little(episode_table(events), step_curves(events, 1000.0), 500.0, 1000.0)
    assert (little.requests, little.mean_wait) == (1, 100.0)
    assert little.by_little == pytest.approx(100 / 500, abs=1e-12)


def test_little_ventana_no_valida():
    log = HandLog()
    admitted(log, 1, 0.0, 10.0).depart(1, 10.0)
    events = log.events()
    with pytest.raises(ValueError, match="window"):
        bed_little(episode_table(events), step_curves(events, 100.0), 0.0, 200.0)


# --- Contrafactual del abandono --------------------------------------------------------------


def counterfactual_world():
    """Nivel asignado 4: tres se quedan y salen (uno ingresa), uno sigue dentro y dos se van
    (uno habría ingresado). Dos se fueron antes del triaje, sin nivel (uno habría ingresado)."""
    table = [
        episode(1, 0.0, assessment=10.0, departure=100.0, destination="ingreso"),
        episode(2, 0.0, assessment=10.0, departure=100.0, destination="alta"),
        episode(3, 0.0, assessment=10.0, departure=100.0, destination="alta"),
        episode(4, 0.0),  # sigue dentro
        episode(5, 0.0, left=50.0),
        episode(6, 0.0, left=60.0),
        episode(7, 0.0, left=5.0, level=None),
        episode(8, 0.0, left=6.0, level=None),
    ]
    destinations = {1: "ingreso", 2: "alta", 3: "alta", 4: "alta", 5: "ingreso", 6: "alta"}
    destinations |= {7: "ingreso", 8: "alta"}
    truth = {f"EP-{i:06d}": truth_of(destination=d) for i, d in destinations.items()}
    return table, truth


def test_el_ingreso_de_los_que_se_quedaron_y_de_los_que_se_fueron():
    table, truth = counterfactual_world()
    rows = abandonment_counterfactual(table, truth, 0.0, 100.0)
    assert [r.level for r in rows] == [1, 2, 3, 4, 5, None]
    level_4 = rows[3]
    # Se quedan 3 y 1 ingresa: 1/3; se van 2 y 1 habría ingresado: 1/2; 1 sigue dentro.
    assert (level_4.stayed, level_4.stayed_admitted, level_4.inside) == (3, 1, 1)
    assert (level_4.left, level_4.left_would_admit) == (2, 1)
    assert level_4.stayed_share == pytest.approx(1 / 3, abs=1e-12)
    assert level_4.left_share == pytest.approx(0.5, abs=1e-12)
    # Antes del triaje: 2 que se fueron, 1 habría ingresado.
    before = rows[5]
    assert (before.left, before.left_would_admit, before.stayed) == (2, 1, 0)
    assert before.stayed_share is None
    assert rows[0].left_share is None  # un nivel sin nadie


def test_la_suma_de_los_que_habrian_ingresado_es_la_del_ground_truth():
    # 1 + 1 = 2 = would_be_admitted, calculado aparte por true_level_abandonment.
    table, truth = counterfactual_world()
    rows = abandonment_counterfactual(table, truth, 0.0, 100.0)
    assert sum(r.left_would_admit for r in rows) == 2
    assert true_level_abandonment(table, truth, 0.0, 100.0).would_be_admitted == 2
    assert sum(r.left for r in rows) == true_level_abandonment(table, truth, 0.0, 100.0).left


def test_el_contrafactual_usa_el_destino_sorteado_y_no_el_del_log():
    # El log de quien se va no tiene destino; el contrafactual sale del ground truth.
    table, truth = counterfactual_world()
    assert all(e.destination is None for e in table if e.left is not None)
    assert abandonment_counterfactual(table, truth, 0.0, 100.0)[3].left_would_admit == 1


def test_el_contrafactual_pide_la_verdad_de_quien_se_fue():
    table, truth = counterfactual_world()
    del truth["EP-000005"]
    with pytest.raises(ValueError, match="not in the ground truth"):
        abandonment_counterfactual(table, truth, 0.0, 100.0)


# --- Destinos por tramo de G -----------------------------------------------------------------


def severity_world():
    """Seis pacientes con G = 1,5 / 0,5 / 0,5 / −0,5 / 1,0 / 0,0 y sus destinos sorteados."""
    spec = [  # (G, destino sorteado, se va, destino en el log)
        (1.5, "ingreso", False, "ingreso"),
        (0.5, "alta", False, "alta"),
        (0.5, "ingreso", True, None),
        (-0.5, "alta", False, "alta"),
        (1.0, "traslado", False, "traslado"),
        (0.0, "alta", False, "alta"),
    ]
    table, truth = [], {}
    for i, (g, drawn, gone, logged) in enumerate(spec):
        if gone:
            table.append(episode(i, 0.0, left=30.0))
        else:
            table.append(episode(i, 0.0, assessment=10.0, departure=60.0, destination=logged))
        truth[f"EP-{i:06d}"] = truth_of(destination=drawn, severity=g)
    return table, truth


def test_destinos_por_tramo_de_g_a_mano():
    # edges [∞, 1, 0, −∞]: tramos G > 1, 0 < G ≤ 1 y G ≤ 0. Tramo 0: el de 1,5. Tramo 1: los dos de
    # 0,5 y el de G = 1 exacto. Tramo 2: el de −0,5 y el de G = 0 exacto.
    rows = destinations_by_severity(*severity_world(), [INF, 1.0, 0.0, -INF], 0.0, 100.0)
    assert [r.arrivals for r in rows] == [1, 3, 2]
    assert [r.left for r in rows] == [0, 1, 0]
    assert dict(rows[0].drawn) == {"alta": 0, "ingreso": 1, "traslado": 0, "exitus": 0}
    assert dict(rows[1].drawn) == {"alta": 1, "ingreso": 1, "traslado": 1, "exitus": 0}
    assert dict(rows[2].drawn) == {"alta": 2, "ingreso": 0, "traslado": 0, "exitus": 0}
    # Lo observado no incluye al que se fue: el del tramo 1 que habría ingresado.
    assert dict(rows[1].observed) == {"alta": 1, "ingreso": 0, "traslado": 1, "exitus": 0}
    assert dict(rows[0].observed) == {"alta": 0, "ingreso": 1, "traslado": 0, "exitus": 0}


def test_g_en_un_borde_cae_en_el_tramo_de_abajo():
    # La convención de interval_nodes es (edges[i + 1], edges[i]]: el borde cuenta en el tramo de
    # arriba de su valor numérico, es decir, el de G ≤ borde. G = 1 → tramo 1; G = 0 → tramo 2.
    rows = destinations_by_severity(*severity_world(), [INF, 1.0, 0.0, -INF], 0.0, 100.0)
    assert rows[1].drawn["traslado"] == 1  # el de G = 1
    assert rows[0].arrivals == 1  # solo el de 1,5, no el de 1,0


def test_los_destinos_sorteados_son_los_cuatro_en_el_orden_del_modelo():
    rows = destinations_by_severity(*severity_world(), [INF, 0.0, -INF], 0.0, 100.0)
    assert tuple(rows[0].drawn) == DESTINATIONS == tuple(rows[0].observed)


@pytest.mark.parametrize(
    "edges",
    [[1.0, 0.0, -INF], [INF, 0.0, 1.0, -INF], [INF], [INF, 0.0, 0.0, -INF], [INF, 0.0, 1.0]],
)
def test_bordes_no_validos(edges):
    with pytest.raises(ValueError, match="edges"):
        destinations_by_severity(*severity_world(), edges, 0.0, 100.0)


def test_un_borde_nan_se_rechaza():
    with pytest.raises(ValueError, match="edges"):
        destinations_by_severity(*severity_world(), [INF, float("nan"), -INF], 0.0, 100.0)


# --- Media de un reloj -----------------------------------------------------------------------


def clock_table():
    return [
        episode(1, 0.0, assessment=30.0, departure=100.0),  # nivel 4, reloj A 30
        episode(2, 10.0, assessment=70.0, departure=100.0),  # nivel 4, 60
        episode(3, 20.0, assessment=110.0, departure=200.0),  # nivel 4, 90
        episode(4, 30.0, assessment=230.0, departure=300.0, level=5),  # nivel 5, 200
        episode(5, 40.0, assessment=45.0, departure=300.0, level=1),  # nivel 1, 5
        episode(6, 50.0, left=500.0, level=5),  # se va: sin reloj
        episode(7, 60.0, level=3),  # sigue dentro
    ]


def test_la_media_del_reloj_a_de_los_niveles_2_a_5():
    # (30 + 60 + 90 + 200) / 4 = 95, sin el nivel 1 (5), ni el que se va ni el que sigue dentro.
    result = clock_mean(clock_table(), 0, 1, (2, 3, 4, 5))
    assert (result.n, result.mean) == (4, pytest.approx(95.0, abs=1e-12))


def test_la_media_del_reloj_a_del_nivel_5():
    result = clock_mean(clock_table(), 0, 1, (5,))
    assert (result.n, result.mean) == (1, 200.0)


def test_la_media_sin_pacientes_es_none_no_nan():
    result = clock_mean(clock_table(), 3, 4, (2, 3, 4, 5))
    assert (result.n, result.mean) == (0, None)


def test_la_media_cuenta_por_dia_de_llegada():
    # Día 0 = minutos 0 a 1439; uno que llega en el 1440 es del día 1.
    table = [*clock_table(), episode(8, 1440.0, assessment=1500.0, departure=1600.0)]
    assert clock_mean(table, 0, 1, (4,)).n == 3
    assert clock_mean(table, 1, 2, (4,)).mean == 60.0


@pytest.mark.parametrize("levels", [(), (0,), (6,)])
def test_niveles_no_validos(levels):
    with pytest.raises(ValueError, match="levels"):
        clock_mean(clock_table(), 0, 1, levels)


def test_medida_y_dias_no_validos():
    with pytest.raises(ValueError, match="measure"):
        clock_mean(clock_table(), 0, 1, (4,), "sopa")
    with pytest.raises(ValueError, match="first_day"):
        clock_mean(clock_table(), 2, 1, (4,))


# --- Con una ejecución real del ejemplo del hito 5 --------------------------------------------

DAYS = 6


@pytest.fixture(scope="module")
def real_run():
    center = load_center(DATA / "centro_h5_ejemplo.toml")
    profiles = load_profiles(DATA / "perfiles_h5_ejemplo.toml")
    arrivals = load_profile(DATA / "llegadas_ejemplo.toml")
    sink = MemorySink()
    result = simulate_ed(center, arrivals, DAYS, 7, sink=sink, warmup_days=1, profiles=profiles)
    truth = {t.episode_id: t for t in result.ground_truth.episodes}
    table = episode_table(sink.events)
    curves = step_curves(sink.events, DAYS * 1440.0)
    return table, truth, curves, outcome_model(profiles, arrivals)


def test_los_destinos_por_tramo_cuadran_con_las_llegadas_y_con_el_modelo(real_run):
    table, truth, _, model = real_run
    start, end = 1440.0, DAYS * 1440.0
    edges = model.workup.severity_edges(5)
    rows = destinations_by_severity(table, truth, edges, start, end)
    arrived = [e for e in table if start <= e.arrival < end]
    assert len(rows) == 5 and sum(r.arrivals for r in rows) == len(arrived) > 100
    assert sum(r.left for r in rows) == sum(e.left is not None for e in arrived)
    for r in rows:
        assert sum(r.drawn.values()) == r.arrivals
        assert sum(r.observed.values()) + r.left <= r.arrivals
    # Tramos de igual masa: cada quintil trae algo menos de un quinto y algo más de un
    # décimo. El primero es el más grave, y el ingreso baja con G.
    assert all(0.10 < r.arrivals / len(arrived) < 0.30 for r in rows)
    exact = model.by_severity(5)
    assert exact[0][DESTINATIONS.index("ingreso")] > exact[4][DESTINATIONS.index("ingreso")]
    share = [r.drawn["ingreso"] / r.arrivals for r in rows]
    assert share[0] > share[4]


def test_el_contrafactual_de_la_ejecucion_real_suma_lo_que_dice_el_ground_truth(real_run):
    table, truth, _, _ = real_run
    start, end = 1440.0, DAYS * 1440.0
    rows = abandonment_counterfactual(table, truth, start, end)
    ground = true_level_abandonment(table, truth, start, end)
    assert ground.left > 0 and ground.would_be_admitted > 0  # la situación ocurre de verdad
    assert sum(r.left for r in rows) == ground.left
    assert sum(r.left_would_admit for r in rows) == ground.would_be_admitted
    arrived = sum(e.arrival >= start and e.arrival < end for e in table)
    assert sum(r.stayed + r.left + r.inside for r in rows) == arrived


def test_little_de_la_ejecucion_real_cuadra_con_las_curvas(real_run):
    table, _, curves, _ = real_run
    little = bed_little(table, curves, 1440.0, DAYS * 1440.0)
    assert little.requests > 0
    # Hay efectos de borde de la ventana, pero ninguno de orden de magnitud.
    assert little.by_curves == pytest.approx(little.by_little, rel=0.5)


def test_la_hora_de_la_ejecucion_real_suma_las_llegadas(real_run):
    table, _, _, _ = real_run
    start, end = 1440.0, DAYS * 1440.0
    rows = abandonment_by_arrival_hour(table, start, end)
    arrived = [e for e in table if start <= e.arrival < end]
    assert sum(r.arrivals for r in rows) == len(arrived)
    assert sum(r.left for r in rows) == sum(e.left is not None for e in arrived)
