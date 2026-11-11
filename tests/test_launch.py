"""Preparar y lanzar un directo o un replay (tarea 6.5): lo que hace la CLI, sin la CLI.

El run_id por defecto, la preparación del directo (con la fecha del perfil o anclado al
calendario) y la del replay de una ejecución guardada, y el directo entero con la línea de
estado: «directo = batch» sigue valiendo con los envoltorios.

Las ejecuciones guardadas usan una copia de tests/data/llegadas_ejemplo.toml con
fecha_inicio = 2026-03-09: la del perfil de tests/data y la de config/llegadas.toml son la
misma (2026-01-05), y un replay que tomara la fecha del perfil actual en vez de la del
primer evento pasaría sin que nadie lo viera.
"""

import math
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from test_directo import SCRIPT, filtered_batch

from edsim.arrivals.profile import load_profile
from edsim.engine.center import load_center
from edsim.engine.clinical_sampler import ModelChoiceError
from edsim.engine.engine import simulate_ed
from edsim.engine.events import EventLog, MemorySink, read_events, to_json
from edsim.live.clock import FakeClock
from edsim.live.control import ScriptedControl
from edsim.live.directo import EngineSource, LogSource, MemoryLiveSink, RunInfo
from edsim.live.launch import (
    live_run_id,
    log_start_date,
    prepare_live,
    prepare_replay,
    run_prepared,
)
from edsim.live.pacer import MAX_SLICE
from edsim.profiles.config import load_profiles
from edsim.runs.service import simulate_run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
REPLAY_DATE = date(2026, 3, 9)
REPLAY_RUN = "rreemitir"


# --- run_id por defecto --------------------------------------------------------------


@pytest.mark.parametrize(
    ("wall", "expected"),
    [
        # 16:23 UTC son las 17:23 en +01:00.
        (datetime(2026, 11, 6, 16, 23, tzinfo=UTC), "r2026_20261106T172300"),
        # 23:30 UTC del 31 de diciembre ya es el 1 de enero en +01:00: cambian día y año.
        (datetime(2026, 12, 31, 23, 30, tzinfo=UTC), "r2026_20270101T003000"),
    ],
)
def test_run_id_por_defecto(wall, expected):
    assert live_run_id(2026, wall) == expected


@pytest.mark.parametrize(
    ("seed", "wall", "match"),
    [
        (10**60, datetime(2026, 11, 6, tzinfo=UTC), "run_id"),  # no cabe en 64 caracteres
        (-1, datetime(2026, 11, 6, tzinfo=UTC), "seed"),
        (2026, datetime(2026, 11, 6), "wall"),
    ],
    ids=["demasiado-largo", "semilla-negativa", "sin-zona"],
)
def test_run_id_por_defecto_no_valido(seed, wall, match):
    with pytest.raises(ValueError, match=match):
        live_run_id(seed, wall)


# --- Preparar el directo -------------------------------------------------------------


@pytest.fixture(scope="module")
def models():
    return {
        "centro": load_center(DATA / "centro_sala_ejemplo.toml"),
        "provisional": load_center(DATA / "centro_ejemplo.toml"),
        "llegadas": load_profile(DATA / "llegadas_ejemplo.toml"),
        "perfiles": load_profiles(DATA / "perfiles_ejemplo.toml"),
    }


def test_preparar_directo_con_la_fecha_del_perfil(models):
    prepared = prepare_live(
        models["centro"],
        models["llegadas"],
        3,
        2026,
        warmup_days=2,
        run_id="rdirecto",
        profiles=models["perfiles"],
    )

    assert prepared.info == RunInfo("rdirecto", "directo", 3, 2026, date(2026, 1, 5), False)
    assert (prepared.start, prepared.horizon) == (2880.0, 4320.0)
    assert isinstance(prepared.source, EngineSource)
    assert prepared.source.horizon == 4320


def test_preparar_directo_provisional_es_la_version_1(models):
    prepared = prepare_live(
        models["provisional"], models["llegadas"], 2, 2026, warmup_days=1, run_id="rprov"
    )

    assert prepared.info.schema_version == 1
    first = prepared.source.step()[0]
    assert first.schema_version == 1


def test_preparar_directo_anclado(models):
    # 10:30 en +01:00 con 2 días: empieza el 9 a las 0:00 y W = 2 × 1.440 + 630.
    prepared = prepare_live(
        models["centro"],
        models["llegadas"],
        3,
        2026,
        warmup_days=2,
        run_id="ranclado",
        profiles=models["perfiles"],
        anchor_wall=datetime(2026, 3, 11, 9, 30, tzinfo=UTC),
    )

    assert prepared.info.start_date == date(2026, 3, 9)
    assert prepared.info.anchored is True
    assert prepared.start == 3510.0
    first = prepared.source.step()[0]
    assert (first.sim_time, first.event_time) == (0, "2026-03-09T00:00:00.000+01:00")


@pytest.mark.parametrize(("days", "warmup"), [(2, 2), (2, 3), (0, 0)])
def test_preparar_directo_dias_no_validos(models, days, warmup):
    with pytest.raises(ValueError):
        prepare_live(
            models["centro"], models["llegadas"], days, 2026, warmup_days=warmup, run_id="r"
        )


# --- Fecha de inicio de un log -------------------------------------------------------


def hand_events(start_date: date) -> list:
    sink = MemorySink()
    log = EventLog("rfecha", start_date, sink, schema_version=3)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    log.emit("patient_arrived", 739.02, arrival_id=1, medio="propios_medios")
    return sink.events


def test_fecha_de_inicio_del_log():
    events = hand_events(REPLAY_DATE)

    # 739,02 minutos son las 12:19:01,2: event_time menos sim_time da las 0:00 del día 9.
    assert events[1].event_time == "2026-03-09T12:19:01.200+01:00"
    assert [log_start_date(e) for e in events] == [REPLAY_DATE, REPLAY_DATE]


def test_fecha_de_inicio_de_un_log_que_no_empieza_a_las_0():
    # El mismo event_time con sim_time 60: el log empezaría a las 23:00 del día anterior.
    [event, _] = hand_events(REPLAY_DATE)
    with pytest.raises(ValueError, match="00:00"):
        log_start_date(replace(event, sim_time=60.0))


# --- Preparar el replay --------------------------------------------------------------


def save_run(root: Path, run_id: str, *, days: int = 2, warmup_days: int = 1) -> Path:
    """Guarda en ``root`` una ejecución de tests/data (sala, perfiles) con fecha_inicio
    2026-03-09, como `edsim motor simular`; devuelve su eventos.jsonl."""
    arrivals = root / "llegadas_marzo.toml"
    text = (DATA / "llegadas_ejemplo.toml").read_text(encoding="utf-8")
    assert "fecha_inicio = 2026-01-05" in text
    arrivals.write_text(text.replace("fecha_inicio = 2026-01-05", "fecha_inicio = 2026-03-09"))
    simulate_run(
        DATA / "centro_sala_ejemplo.toml",
        arrivals,
        days,
        2026,
        output_dir=root / run_id,
        warmup_days=warmup_days,
        run_id=run_id,
        origin="cli",
        profiles=DATA / "perfiles_ejemplo.toml",
    )
    return root / run_id / "eventos.jsonl"


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    root = tmp_path_factory.mktemp("ejecuciones")
    save_run(root, REPLAY_RUN)
    return root


def test_preparar_replay(saved):
    prepared = prepare_replay(saved, REPLAY_RUN)

    assert prepared.info == RunInfo(REPLAY_RUN, "replay", 3, 2026, REPLAY_DATE, False)
    assert (prepared.start, prepared.horizon) == (1440.0, 2880.0)
    assert isinstance(prepared.source, LogSource)
    first = prepared.source.step()[0]
    assert first.event_id == f"{REPLAY_RUN}-000000000"


def test_preparar_replay_con_otro_calentamiento(saved):
    assert prepare_replay(saved, REPLAY_RUN, warmup_days=0).start == 0.0


def test_preparar_replay_que_no_existe(saved):
    with pytest.raises(OSError):
        prepare_replay(saved, "rnoexiste")


def test_preparar_replay_con_calentamiento_no_menor_que_los_dias(saved):
    with pytest.raises(ValueError, match="warmup"):
        prepare_replay(saved, REPLAY_RUN, warmup_days=2)


def test_preparar_replay_con_el_log_vacio(tmp_path):
    save_run(tmp_path, "rvacio").write_text("")
    with pytest.raises(ValueError, match="empty"):
        prepare_replay(tmp_path, "rvacio")


# --- El directo entero con la línea de estado ----------------------------------------


def test_directo_igual_a_batch_con_la_linea_de_estado(models):
    # El caso v3 de test_directo.py (3 días, W 2, las cuatro órdenes), por run_prepared.
    center, profile, profiles = models["centro"], models["llegadas"], models["perfiles"]
    batch = MemorySink()
    simulate_ed(center, profile, 3, 2026, sink=batch, run_id="r2026", profiles=profiles)
    expected = filtered_batch(batch.events, 2880)

    clock = FakeClock()
    control = ScriptedControl(clock, SCRIPT)
    live = MemoryLiveSink()
    lines, starts, ends = [], [], []
    end = run_prepared(
        prepare_live(center, profile, 3, 2026, warmup_days=2, run_id="r2026", profiles=profiles),
        clock=clock,
        speed=60,
        control=control,
        sink=live,
        on_start=starts.append,
        on_end=lambda start, end: ends.append(end),
        on_status=lines.append,
    )

    assert [to_json(e) for e in live.events] == [to_json(e) for e in expected]
    assert (end.reason, end.sim_time, end.published) == ("horizonte", 4320, len(expected))
    assert starts == [live.run_start]
    assert ends == [end]
    # Guardas: el estado salió y las órdenes se aplicaron, cada una a tiempo.
    assert len(lines) > 10
    assert lines[-1].published <= len(expected)
    assert [c for _, _, c in control.delivered] == [c for _, c in SCRIPT]
    assert all(0 <= seen - at <= MAX_SLICE + 1e-9 for at, seen, _ in control.delivered)


def test_el_replay_publica_las_lineas_filtradas(saved):
    path = saved / REPLAY_RUN / "eventos.jsonl"
    live = MemoryLiveSink()

    end = run_prepared(
        prepare_replay(saved, REPLAY_RUN),
        clock=FakeClock(),
        speed="max",
        control=ScriptedControl(FakeClock(), []),
        sink=live,
    )

    expected = filtered_batch(list(read_events(path)), 1440)
    assert [to_json(e) for e in live.events] == [to_json(e) for e in expected]
    assert end.published == len(expected)
    assert live.run_start.info.start_date == REPLAY_DATE
    assert math.isclose(end.sim_time, 2880)


# --- El hito 5 (tarea 5.3): el directo de la versión 4 es de la 5.4 -------------------------


def test_el_directo_rechaza_los_ficheros_del_hito_5(models):
    # Nunca los etiqueta como versión 3: hasta la 5.4, un error claro.
    with pytest.raises(ValueError, match="live mode of the milestone 5 model .* task 5.4"):
        prepare_live(
            load_center(DATA / "centro_h5_ejemplo.toml"),
            models["llegadas"],
            2,
            2026,
            warmup_days=1,
            run_id="rh5",
            profiles=load_profiles(DATA / "perfiles_h5_ejemplo.toml"),
        )


def test_el_directo_rechaza_un_bloque_a_medias(models):
    with pytest.raises(ModelChoiceError, match=r"missing \[abandono\]"):
        prepare_live(
            load_center(DATA / "centro_h5_ejemplo.toml"),
            models["llegadas"],
            2,
            2026,
            warmup_days=1,
            run_id="rmedias",
            profiles=models["perfiles"],
        )
