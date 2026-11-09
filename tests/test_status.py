"""Línea de estado del directo (tarea 6.5): cada 10 s reales, enganchada a las órdenes.

El directo a mano de la 6.3 (W 120, horizonte 180, ×60 desde 0 s, reloj falso): el censo
de 6 eventos y la salida de EP-000003 en 0 s, la de EP-000002 en 30 s, la llegada de
EP-000004 en 50 s y el fin en 60 s. El pacer pide una orden en cada tramo de 0,2 s, así
que hay una línea exactamente a los 10, 20… s; la del instante de un evento sale antes de
publicarlo (el pacer pide la orden y después libera). Los valores son a mano.
"""

from datetime import date

import pytest
from test_directo import INFO, TimedSink, live_hand_log

from edsim.engine.events import EventLog, MemorySink
from edsim.engine.scenarios import SCENARIO_START
from edsim.live.clock import FakeClock
from edsim.live.control import PAUSE, RESUME, Command, ScriptedControl
from edsim.live.directo import LogSource, MemoryLiveSink, RunEnd, RunStart, run_live
from edsim.live.pacer import Pacer
from edsim.live.report import format_census, format_end, format_status
from edsim.live.status import LiveStatus, ReportingSink, StatusControl

TOL = 1e-9


def approx(x):
    return pytest.approx(x, abs=TOL)


def run_with_status(*, script=(), delay=0.0, pending=None):
    """El directo a mano con los dos envoltorios; devuelve las líneas, con el instante del
    reloj en que salió cada una, el sumidero de dentro y el que cuenta."""
    clock = FakeClock()
    inner = TimedSink(clock, delay)
    ends = []
    sink = ReportingSink(inner, on_end=lambda start, end: ends.append((start, end)))
    pacer = Pacer(clock, 60, (0.0, 0.0))
    lines = []
    control = StatusControl(
        ScriptedControl(clock, script),
        clock=clock,
        pacer=pacer,
        start_date=SCENARIO_START,
        horizon=180,
        published=lambda: sink.published,
        on_status=lambda status: lines.append((clock.monotonic(), status)),
        pending=pending,
    )
    run_live(
        LogSource(live_hand_log(), 180),
        pacer,
        control,
        sink,
        start=120,
        horizon=180,
        run_info=INFO,
    )
    return lines, inner, sink, ends


def summary(lines):
    """(instante, minuto, en pausa, publicados) de cada línea."""
    return [(t, s.sim_time, s.paused, s.published) for t, s in lines]


@pytest.mark.parametrize("pending", [None, 3], ids=["memoria", "pendientes"])
def test_estado_a_mano(pending):
    lines, _, _, _ = run_with_status(pending=None if pending is None else lambda: pending)

    expected = [
        (10, 130, False, 7),
        (20, 140, False, 7),
        (30, 150, False, 7),  # el poll de los 30 s va antes de publicar la salida de EP-000002
        (40, 160, False, 8),
        (50, 170, False, 8),
        (60, 180, False, 9),  # esperando el horizonte
    ]
    assert summary(lines) == [(approx(t), approx(m), paused, n) for t, m, paused, n in expected]
    assert all(s.elapsed == approx(t) for t, s in lines)
    assert all(s.speed == 60 and s.lag == 0 and s.pending == pending for _, s in lines)
    assert lines[0][1].event_time == "2026-01-05T02:10:00.000+01:00"


def test_estado_en_pausa():
    lines, _, _, _ = run_with_status(script=[(15, Command(PAUSE)), (35, Command(RESUME))])

    # Pausa en el minuto 135; al reanudar, ancla (35 s, 135): EP-000002 sale a los 50 s.
    expected = [
        (10, 130, False, 7),
        (20, 135, True, 7),
        (30, 135, True, 7),
        (40, 140, False, 7),
        (50, 150, False, 7),
        (60, 160, False, 8),
        (70, 170, False, 8),
        (80, 180, False, 9),
    ]
    assert summary(lines) == [(approx(t), approx(m), paused, n) for t, m, paused, n in expected]


def test_estado_empieza_en_el_ancla_del_directo():
    # Publicar cada evento tarda 1 s: el censo acaba a los 6 s, y ahí se ancla el directo.
    # La primera línea sale 10 s después del ancla, no del arranque.
    lines, _, _, _ = run_with_status(delay=1.0)

    first_time, first = lines[0]
    assert (first_time, first.sim_time, first.published) == (approx(16), approx(130), 7)
    assert first.elapsed == approx(10)


def off_grid_log() -> list:
    """Dos staffing_changed en 0 y llegadas en 120,37 + 2,13 · i (hasta 177,88): a ×60 desde
    W = 120, ningún evento cae en un segundo entero, y los tramos de 0,2 s del pacer
    empiezan en cada evento, fuera de la rejilla de 10 s."""
    sink = MemorySink()
    log = EventLog("rrejilla", SCENARIO_START, sink, schema_version=3)
    log.emit("staffing_changed", 0.0, recurso="enfermeria_triaje", anterior=0, nueva=2)
    log.emit("staffing_changed", 0.0, recurso="medicos", anterior=0, nueva=3)
    for i in range(28):
        log.emit("patient_arrived", 120.37 + 2.13 * i, arrival_id=i + 1, medio="propios_medios")
    return sink.events


def test_las_lineas_no_se_retrasan_con_eventos_fuera_de_la_rejilla():
    # Cada línea sale en el primer poll desde 10k s, como mucho 0,2 s después: la rejilla
    # va fija desde el ancla, y los retrasos de una línea no se suman a la siguiente.
    clock = FakeClock()
    sink = ReportingSink(MemoryLiveSink())
    pacer = Pacer(clock, 60, (0.0, 0.0))
    lines = []
    control = StatusControl(
        ScriptedControl(clock, []),
        clock=clock,
        pacer=pacer,
        start_date=SCENARIO_START,
        horizon=180,
        published=lambda: sink.published,
        on_status=lambda status: lines.append(clock.monotonic()),
    )
    events = off_grid_log()
    run_live(LogSource(events, 180), pacer, control, sink, start=120, horizon=180, run_info=INFO)

    assert len(lines) == 6
    assert all(10 * k <= t < 10 * k + 0.2 for k, t in enumerate(lines, start=1)), lines
    # Guarda: el caso ocurre, alguna línea no sale justo en su múltiplo de 10 s.
    assert any(t != approx(10 * k) for k, t in enumerate(lines, start=1))
    assert len(sink.sink.events) == len(events)


def test_el_sumidero_que_cuenta_no_cambia_lo_publicado():
    lines, inner, sink, ends = run_with_status()

    assert sink.published == len(inner.events) == 9
    assert sink.run_start is inner.run_start
    assert sink.run_end is inner.run_end
    assert ends == [(inner.run_start, inner.run_end)]
    assert lines  # guarda: el estado salió


def test_el_fin_de_ctrl_c_llega_al_resumen():
    clock = FakeClock(interrupt_at=45)
    ends = []
    sink = ReportingSink(TimedSink(clock), on_end=lambda start, end: ends.append(end))
    with pytest.raises(KeyboardInterrupt):
        run_live(
            LogSource(live_hand_log(), 180),
            Pacer(clock, 60, (0.0, 0.0)),
            ScriptedControl(clock, []),
            sink,
            start=120,
            horizon=180,
            run_info=INFO,
        )
    [end] = ends
    assert (end.reason, end.published) == ("interrupcion", 8)


# --- Textos --------------------------------------------------------------------------


def status(**changes):
    values = dict(
        elapsed=10.0,
        sim_time=130.0,
        event_time="2026-01-05T02:10:00.000+01:00",
        speed=60.0,
        paused=False,
        published=7,
        lag=0.00042,
        pending=None,
    )
    return LiveStatus(**(values | changes))


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({}, "+10 s · 2026-01-05T02:10:00.000+01:00 (minuto 130.0) · ×60 · 7 publicados"
             " · retraso 0.4 ms"),
        ({"pending": 3}, "+10 s · 2026-01-05T02:10:00.000+01:00 (minuto 130.0) · ×60"
                         " · 7 publicados · retraso 0.4 ms · 3 pendientes"),
        ({"speed": "max"}, "+10 s · 2026-01-05T02:10:00.000+01:00 (minuto 130.0) · máxima"
                           " · 7 publicados · retraso 0.4 ms"),
        ({"speed": 2.5, "paused": True}, "+10 s · 2026-01-05T02:10:00.000+01:00"
                                         " (minuto 130.0) · en pausa · 7 publicados"
                                         " · retraso 0.4 ms"),
    ],
    ids=["memoria", "pendientes", "maxima", "pausa"],
)  # fmt: skip
def test_texto_de_la_linea_de_estado(changes, text):
    assert format_status(status(**changes)) == text


START = RunStart(
    info=INFO,
    live_start=120.0,
    horizon=180.0,
    speed=60.0,
    census_episodes=2,
    census_events=6,
)


def test_texto_del_censo():
    assert format_census(START) == (
        "Censo en W = 120 min: 2 episodios abiertos, 6 eventos; empieza el directo"
    )


def test_texto_del_fin():
    end = RunEnd("rcenso", "horizonte", 180.0, "rcenso-000000012", 9)
    assert format_end(START, end) == (
        "Fin · motivo horizonte · 9 publicados (6 de censo y 3 en directo) · minuto 180"
        " · último event_id rcenso-000000012"
    )


def test_texto_del_fin_con_error_en_el_censo_y_sin_eventos():
    # Un fin de error con menos confirmados que el censo, y uno sin inicio ni eventos.
    error = RunEnd("rcenso", "error", 120.0, "rcenso-000000003", 4)
    assert "4 publicados (4 de censo y 0 en directo)" in format_end(START, error)
    empty = RunEnd("rcenso", "interrupcion", 120.0, None, 0)
    assert format_end(None, empty) == (
        "Fin · motivo interrupcion · 0 publicados · minuto 120 · último event_id —"
    )


def test_fecha_del_escenario():
    assert SCENARIO_START == date(2026, 1, 5)  # la que dan las líneas de arriba
