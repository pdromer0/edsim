"""Los indicadores del desenlace del hito 5 (tarea 5.4, pieza 4).

Abandono, destinos, espera de cama, estancia por destino y boxes bloqueados, con los
ejemplos a mano del plan de la 5.4: B (la cama con un censurado), C (la estancia por
destino) y D (diez llegadas con abandono y destinos). Los logs se escriben con
`v4_logs.HandLog`.

La regla de los censurados: un cuantil crece cuando crece uno de sus valores. Con los
censurados en su cota sale el mínimo posible, y con ellos por encima de todo, el máximo; si
coinciden, es exacto, y si no, una cota inferior.
"""

from pathlib import Path

import numpy as np
import pytest
from v4_logs import HandLog

from edsim.engine.analysis import episode_table, outcome_counts, step_curves
from edsim.engine.center import load_center
from edsim.engine.events import WARD
from edsim.engine.outcome_metrics import (
    BED_WAIT_THRESHOLDS,
    CensoredValue,
    bed_occupancy,
    bed_wait_quantiles,
    censored_mean,
    censored_quantile,
    destination_shares,
    left_without_being_seen_shares,
    over_threshold,
    stay_by_destination,
    window_outcome,
)
from edsim.engine.scenarios import abandonment, admission, run_scenario

DATA = Path(__file__).parent / "data"


# --- B: cuantiles y umbrales con censura -----------------------------------------------


def test_mediana_exacta_con_un_censurado_por_encima():
    # Acabadas 100 y 500; uno sigue esperando con 800. Mínimo: mediana{100, 500, 800} = 500;
    # máximo: mediana{100, 500, H} = 500. Sin el censurado saldría 300 (V27).
    assert censored_quantile([100, 500], [800], 50) == CensoredValue(500.0, True)


def test_p90_es_una_cota_con_un_censurado_por_encima():
    # Rango 0,9 · 2 = 1,8: mínimo 500 + 0,8 · (800 − 500) = 740; el máximo depende de H.
    p90 = censored_quantile([100, 500], [800], 90)
    assert p90.value == pytest.approx(740.0, abs=1e-9) and not p90.exact


def test_mediana_cota_con_un_censurado_en_medio():
    # Con el censurado en 200: mínimo mediana{100, 200, 500} = 200, máximo 500.
    assert censored_quantile([100, 500], [200], 50) == CensoredValue(200.0, False)


@pytest.mark.parametrize(
    ("censored", "minutes", "over", "known", "unknown"),
    [
        (800, 360, 2, 3, 0),  # 500 y el censurado 800 > 360
        (800, 720, 1, 3, 0),  # solo el censurado
        (800, 1440, 0, 2, 1),  # 800 ≤ 1.440: no se sabe
        (200, 360, 1, 2, 1),  # 200 ≤ 360: no se sabe
        (360, 360, 1, 2, 1),  # justo en el umbral: aún puede pasarlo
    ],
)
def test_por_encima_de_un_umbral(censored, minutes, over, known, unknown):
    result = over_threshold([100, 500], [censored], minutes)
    assert (result.over, result.known, result.unknown) == (over, known, unknown)
    assert result.share == over / known


def test_sin_censurados_es_numpy_percentile():
    values = np.random.default_rng(5).exponential(300, 101).tolist()
    for percent in (0, 10, 50, 90, 100):
        assert censored_quantile(values, [], percent) == CensoredValue(
            float(np.percentile(values, percent)), True
        )
    assert censored_mean(values, []) == CensoredValue(float(np.mean(values)), True)


def test_todo_censurado_y_vacio():
    assert censored_quantile([], [5.0], 50) == CensoredValue(5.0, False)
    assert censored_quantile([], [], 50) is None
    assert censored_mean([], []) is None
    assert over_threshold([], [], 360).share is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_valores_no_validos(bad):
    with pytest.raises(ValueError, match="finite"):
        censored_quantile([1.0, bad], [], 50)
    with pytest.raises(ValueError, match="finite"):
        censored_mean([1.0], [bad])
    with pytest.raises(ValueError, match="percent"):
        censored_quantile([1.0], [], 101)


def admitted(log: HandLog, who: int, arrival: float, decision: float) -> HandLog:
    """Un nivel 3 que llega, se clasifica en 5 min, tiene box y se valora hasta `decision`."""
    log.arrive(who, arrival).triage(who, arrival, arrival + 5, 3).box(who, arrival + 5, who)
    return log.assess(who, arrival + 5, decision, who)


def test_espera_de_cama_del_ejemplo_b():
    # Esperas de 100 (10 → 110) y 500 (20 → 520); la tercera pide cama en 40 y sigue en
    # el horizonte, 840: lleva 800.
    log = HandLog()
    admitted(log, 1, 0.0, 10.0).admit(1, 10.0, 110.0)
    admitted(log, 2, 1.0, 20.0).admit(2, 20.0, 520.0)
    admitted(log, 3, 2.0, 40.0)
    log.add(40.0, "disposition_decided", 3, destino="ingreso")
    log.add(40.0, "bed_requested", 3, servicio=WARD)
    bed = bed_wait_quantiles(episode_table(log.events()), 0.0, 840.0, 840.0)
    assert (bed.requests, bed.completed, bed.censored) == (3, 2, 1)
    assert bed.median == CensoredValue(500.0, True)
    assert bed.p90.value == pytest.approx(740.0, abs=1e-9) and not bed.p90.exact
    assert [(o.minutes, o.over, o.known) for o in bed.over] == [
        (360.0, 2, 3),
        (720.0, 1, 3),
        (1440.0, 0, 2),
    ]
    assert tuple(o.minutes for o in bed.over) == BED_WAIT_THRESHOLDS


# --- C: estancia por destino -----------------------------------------------------------


def stays_log(censored_arrival: float) -> list:
    """El ejemplo C con el horizonte en 1.000.

    Altas de 0 a 100 y de 10 a 210; un ingreso de 20 a 420; un ingresado que llega en
    `censored_arrival` y sigue esperando cama en el horizonte; dos que se van, de 30 a 80 y
    de 40 a 110; y uno que llega en 900 y sigue sin destino.
    """
    log = HandLog()
    log.arrive(1, 0.0).triage(1, 0.0, 5.0, 4).box(1, 5.0, 1).assess(1, 5.0, 100.0, 1)
    log.depart(1, 100.0)
    log.arrive(2, 10.0).triage(2, 10.0, 15.0, 4).box(2, 15.0, 2).assess(2, 15.0, 210.0, 2)
    log.depart(2, 210.0)
    admitted(log, 3, 20.0, 60.0).admit(3, 60.0, 420.0)
    log.arrive(4, 30.0).triage(4, 30.0, 35.0, 5).leave(4, 80.0, "box")
    log.arrive(5, 40.0).triage(5, 40.0, 45.0, 5).leave(5, 110.0, "box")
    admitted(log, 6, censored_arrival, censored_arrival + 50)
    log.add(censored_arrival + 50, "disposition_decided", 6, destino="ingreso")
    log.add(censored_arrival + 50, "bed_requested", 6, servicio=WARD)
    log.arrive(7, 900.0).triage(7, 900.0, 905.0, 4)
    return episode_table(log.events())


def test_estancia_por_destino_del_ejemplo_c():
    stay = stay_by_destination(stays_log(700.0), 0.0, 1000.0, 1000.0)
    alta = stay.by_destination["alta"]
    assert (alta.n, alta.censored) == (2, 0)
    assert alta.mean == CensoredValue(150.0, True) and alta.median == CensoredValue(150.0, True)
    ingreso = stay.by_destination["ingreso"]
    # Sale uno con 400 y otro lleva 300 en el horizonte: media y mediana ≥ 350.
    assert (ingreso.n, ingreso.censored) == (1, 1)
    assert ingreso.mean == CensoredValue(350.0, False)
    assert ingreso.median == CensoredValue(350.0, False)
    assert stay.by_destination["traslado"].mean is None
    assert stay.left.mean == CensoredValue(60.0, True) and stay.left.n == 2
    assert stay.inside_without_destination == 1
    # Ingresados por encima de 4 h: 400 y el censurado con 300.
    over = stay.admitted_over
    assert (over.over, over.known, over.unknown) == (2, 2, 0)


def test_ingresado_censurado_por_debajo_de_4_horas():
    over = stay_by_destination(stays_log(800.0), 0.0, 1000.0, 1000.0).admitted_over
    assert (over.over, over.known, over.unknown) == (1, 1, 1)  # el censurado lleva 200


# --- D: diez llegadas con abandono y destinos ---------------------------------------------


def ten_arrivals() -> list:
    """El ejemplo D: uno se va antes del triaje; nivel 3 con alta, alta e ingreso; nivel 4
    con abandono en la espera de box, abandono en el box, ingreso y traslado; nivel 5 con
    abandono en la espera de box y alta."""
    log = HandLog()
    log.arrive(1, 1.0).leave(1, 5.0, "triaje")

    def seen(who: int, level: int) -> HandLog:
        t = float(who)
        log.arrive(who, t).triage(who, t, t + 5, level).box(who, t + 5, who)
        return log.assess(who, t + 5, t + 30, who)

    seen(2, 3).depart(2, 32.0)
    seen(3, 3).depart(3, 33.0)
    seen(4, 3).admit(4, 34.0, 134.0)
    log.arrive(5, 5.0).triage(5, 5.0, 10.0, 4).leave(5, 60.0, "box")
    log.arrive(6, 6.0).triage(6, 6.0, 11.0, 4).box(6, 11.0, 6).leave(6, 61.0, "medico")
    seen(7, 4).admit(7, 37.0, 137.0)
    seen(8, 4).depart(8, 38.0, "traslado")
    log.arrive(9, 9.0).triage(9, 9.0, 14.0, 5).leave(9, 64.0, "box")
    seen(10, 5).depart(10, 40.0)
    return episode_table(log.events())


def test_abandono_del_ejemplo_d():
    left = left_without_being_seen_shares(ten_arrivals(), 0.0, 1440.0)
    assert left.arrivals == 10
    assert dict(left.by_wait) == {"triaje": 1, "box": 2, "medico": 1}
    assert (left.share, left.before_triage_share, left.after_triage_share) == (0.4, 0.1, 0.3)
    assert [(c.level, c.classified, c.count) for c in left.by_level] == [
        (1, 0, 0),
        (2, 0, 0),
        (3, 3, 0),
        (4, 4, 2),
        (5, 2, 1),
    ]
    assert [c.share for c in left.by_level] == [None, None, 0.0, 0.5, 0.5]


def test_destinos_del_ejemplo_d():
    destinations = destination_shares(ten_arrivals(), 0.0, 1440.0)
    assert dict(destinations.counts) == {"alta": 3, "ingreso": 2, "traslado": 1, "exitus": 0}
    assert [destinations.share(d) for d in ("alta", "ingreso", "traslado", "exitus")] == [
        0.3,
        0.2,
        0.1,
        0.0,
    ]
    level_3, level_4, level_5 = destinations.by_level[2:]
    assert (level_3.share("alta"), level_3.share("ingreso")) == (2 / 3, 1 / 3)
    assert (level_4.share("ingreso"), level_4.share("traslado"), level_4.share("alta")) == (
        0.25,
        0.25,
        0.0,
    )
    assert level_5.share("alta") == 0.5
    # En cada nivel, destinos más abandonos = clasificados.
    left = left_without_being_seen_shares(ten_arrivals(), 0.0, 1440.0)
    for level, gone in zip(destinations.by_level, left.by_level, strict=True):
        assert sum(level.counts.values()) + gone.count == level.classified


def test_los_que_llegan_fuera_de_la_ventana_no_cuentan():
    left = left_without_being_seen_shares(ten_arrivals(), 5.0, 1440.0)
    assert left.arrivals == 6 and dict(left.by_wait) == {"triaje": 0, "box": 2, "medico": 1}


# --- Con los escenarios del motor --------------------------------------------------------


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


def test_los_abandonos_son_los_de_outcome_counts(center):
    events = run_scenario(abandonment(center)).events
    left = left_without_being_seen_shares(episode_table(events), 0.0, 1440.0)
    counts = outcome_counts(events, 0.0, 1440.0)
    assert tuple(left.by_wait.values()) == counts.left and left.arrivals == counts.arrivals


def test_boxes_bloqueados_y_pasillo_del_escenario_c(center):
    events = run_scenario(admission(center)).events
    beds = bed_occupancy(step_curves(events, 1440.0), 0.0, 1440.0)
    assert beds.boxes_mean == pytest.approx(25 / 1440, abs=1e-15) and beds.boxes_max == 1
    assert beds.hallway_mean == pytest.approx(125 / 1440, abs=1e-15) and beds.hallway_max == 1
    # Fuera de los tramos con cama pedida, el máximo es 0.
    assert bed_occupancy(step_curves(events, 1440.0), 200.0, 1440.0).hallway_max == 0


def test_window_outcome_junta_todo(center):
    events = run_scenario(admission(center)).events
    table = episode_table(events)
    outcome = window_outcome(table, step_curves(events, 1440.0), 0.0, 1440.0)
    assert outcome.bed_wait.median == CensoredValue(150.0, True)
    assert outcome.destinations.counts["ingreso"] == 1 and outcome.left.left == 0
    with pytest.raises(ValueError, match="window"):
        window_outcome(table, step_curves(events, 1440.0), 0.0, 2000.0)
