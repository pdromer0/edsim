"""`runs/` con la versión 4: estado «esperando cama», pasillo, abandono y filtros (tarea 5.4).

H5-11: el estado dice qué hace el paciente (`waiting_bed`); la marca, dónde está
(`hallway`, como la sala de resultados), y el abandono es un cierre contado aparte. Los
instantes salen de los escenarios M y C del motor (calculados a mano en la 5.1) y del
ejemplo D del plan de la 5.4.
"""

from pathlib import Path

import pytest
from test_outcome_metrics import ten_arrivals
from v4_logs import HandLog, episode

from edsim.engine.analysis import episode_table
from edsim.engine.center import load_center
from edsim.engine.scenarios import abandonment, admission, run_scenario
from edsim.runs import (
    EpisodeFilters,
    RunStore,
    episode_observed_time,
    episode_period,
    episode_segments,
    filter_episodes,
    read_run_results,
    simulate_run,
    window_outcome,
)
from edsim.runs._location import LocationState
from edsim.runs.episodes import EpisodeSegment
from edsim.runs.replay import _empty, _fold

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def log_c(center):
    return run_scenario(admission(center)).events


@pytest.fixture(scope="module")
def log_m(center):
    return run_scenario(abandonment(center)).events


def state_at(events, who: str, t: float) -> LocationState:
    state = LocationState()
    for e in events:
        if e.episode_id == who and e.sim_time <= t:
            state = state.apply(e)
    return state


# --- El reductor de ubicación ----------------------------------------------------------


def test_esperando_cama_en_el_box_y_en_el_pasillo(log_c):
    in_box = state_at(log_c, "EP-000000", 40.0)
    assert (in_box.location(), in_box.box, in_box.hallway) == ("waiting_bed", 1, False)
    in_hallway = state_at(log_c, "EP-000000", 70.0)
    assert (in_hallway.location(), in_hallway.box, in_hallway.hallway) == (
        "waiting_bed",
        None,
        True,
    )
    gone = state_at(log_c, "EP-000000", 185.0)
    assert gone.departed and gone.closed and not gone.hallway and not gone.left


def test_un_desalojo_sin_cama_pedida_no_es_pasillo(log_c):
    # R2 nunca pide cama; el desalojado de antes de la cama vuelve a la cola de box.
    log = HandLog().arrive(1, 0.0).triage(1, 0.0, 5.0, 4).box(1, 5.0, 1).displace(1, 9.0, 1, 2)
    state = state_at(log.events(), episode(1), 9.0)
    assert (state.location(), state.hallway) == ("waiting_box", False)


def test_el_abandono_cierra_aparte(log_m):
    q2 = state_at(log_m, "EP-000001", 26.0)
    assert q2.left and q2.closed and not q2.departed and q2.box is None
    assert state_at(log_m, "EP-000001", 25.0).location() == "waiting_doctor"


# --- Segmentos del episodio ------------------------------------------------------------


def test_segmentos_del_ingresado_del_pasillo(log_c):
    events = [e for e in log_c if e.episode_id == "EP-000000"]
    segments = episode_segments(events, 1440.0).segments
    assert segments == (
        EpisodeSegment("triage", 0.0, 5.0, None),
        EpisodeSegment("assessment", 5.0, 35.0, 1),
        EpisodeSegment("waiting_bed", 35.0, 60.0, 1),
        EpisodeSegment("waiting_bed", 60.0, 185.0, None, hallway=True),
    )


def test_los_segmentos_de_quien_se_va_acaban_al_irse(log_m):
    events = [e for e in log_m if e.episode_id == "EP-000001"]
    assert episode_segments(events, 1440.0).segments == (
        EpisodeSegment("triage", 1.0, 6.0, None),
        EpisodeSegment("waiting_doctor", 6.0, 26.0, 2),
    )


# --- Replay -----------------------------------------------------------------------------


def test_el_replay_cuenta_el_abandono_aparte(log_m):
    state = _fold(_empty(), log_m, 30.0)
    # En 30 siguen Q1 (valoración) y Q3 (box 2); Q2 y Q4 se fueron en la última hora.
    assert {p.episode_id for p in state.patients} == {"EP-000000", "EP-000002"}
    assert [(a.episode_id, a.time, a.wait, a.level) for a in state.abandonments] == [
        ("EP-000003", 4.0, "triaje", None),
        ("EP-000001", 26.0, "medico", 4),
    ]
    assert dict(state.departures_by_destination) == dict.fromkeys(
        ("alta", "ingreso", "traslado", "exitus"), 0
    )
    # Pasada la hora, ya no son recientes.
    assert _fold(_empty(), log_m, 90.0).abandonments == ()


def test_el_replay_marca_el_pasillo(log_c):
    state = _fold(_empty(), log_c, 70.0)
    r1 = next(p for p in state.patients if p.episode_id == "EP-000000")
    assert (r1.state, r1.box, r1.hallway) == ("waiting_bed", None, True)
    # Salidas de la última hora, (t − 60, t]: en 100, las altas de R3 (80) y R2 (100);
    # en 190, solo el ingreso de R1 (185).
    in_100 = _fold(_empty(), log_c, 100.0).departures_by_destination
    assert dict(in_100) == {"alta": 2, "ingreso": 0, "traslado": 0, "exitus": 0}
    in_190 = _fold(_empty(), log_c, 190.0).departures_by_destination
    assert dict(in_190) == {"alta": 0, "ingreso": 1, "traslado": 0, "exitus": 0}


# --- Filtros ------------------------------------------------------------------------------


def ids(table, **filters) -> set[str]:
    chosen = filter_episodes(table, EpisodeFilters(**filters), warmup_end=0.0, horizon=1440.0)
    return {e.episode_id for e in chosen}


def test_filtros_del_desenlace_con_el_ejemplo_d():
    table = ten_arrivals()
    assert ids(table, left=True) == {episode(n) for n in (1, 5, 6, 9)}
    assert ids(table, left_from="box") == {episode(5), episode(9)}
    assert ids(table, bed=True) == {episode(4), episode(7)}
    assert ids(table, destination="traslado") == {episode(8)}
    assert ids(table, left=False, level=4) == {episode(7), episode(8)}


def test_filtro_del_pasillo(log_c):
    assert ids(episode_table(log_c), hallway=True) == {"EP-000000"}


def test_quien_se_va_ha_terminado(log_m):
    q2 = next(e for e in episode_table(log_m) if e.episode_id == "EP-000001")
    assert episode_period(q2, 0.0) == "window"
    assert episode_observed_time(q2, 1440.0) == 25.0
    table = episode_table(log_m)
    # Puerta-médico de Q2 como cota: 26 − 1 = 25, no 1.440 − 1.
    assert "EP-000001" in ids(table, door_to_doctor_gt=24.0)
    assert "EP-000001" not in ids(table, door_to_doctor_gt=25.0)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("left", "si", "left must be"),
        ("bed", 1, "bed must be"),
        ("left_from", "pasillo", "left_from"),
        ("destination", "uci", "destination"),
    ],
)
def test_filtros_no_validos(field, value, match):
    with pytest.raises(ValueError, match=match):
        EpisodeFilters(**{field: value})


def test_los_cuatro_destinos_son_validos():
    for destination in ("alta", "ingreso", "traslado", "exitus"):
        assert EpisodeFilters(destination=destination).destination == destination


# --- RunResults con el desenlace -------------------------------------------------------


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs_v4")
    for run_id, center_file, profiles in (
        ("hito4", "centro_sala_ejemplo.toml", "perfiles_ejemplo.toml"),
        ("hito5", "centro_h5_ejemplo.toml", "perfiles_h5_ejemplo.toml"),
    ):
        simulate_run(
            DATA / center_file,
            DATA / "llegadas_ejemplo.toml",
            2,
            7,
            output_dir=root / run_id,
            run_id=run_id,
            warmup_days=1,
            origin="cli",
            profiles=DATA / profiles,
        )
    return RunStore(root)


def test_los_resultados_del_hito_5_traen_el_desenlace(store):
    result = read_run_results(store, "hito5")
    analysis = result.analysis
    assert result.outcome == window_outcome(
        analysis.table, analysis.curves, analysis.metrics.start, analysis.metrics.end
    )
    assert result.outcome.left.arrivals == analysis.metrics.arrivals
    assert read_run_results(store, "hito4").outcome is None
