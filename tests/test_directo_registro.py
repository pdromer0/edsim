"""El directo con lo registrado: `run_live(..., recording=…)` (tarea 7.4).

Con `--registro`, por el sumidero solo pasa lo registrado: la verdad va paso a paso a la sala
de espera, y el censo y el directo son sus registros, con el `run_id` derivado. Aquí, con el
escenario L de la 7.1 como «motor falso» (`LogSource`), el reloj falso y un sumidero en
memoria que anota el instante de cada publicación, con valores calculados a mano.

Cada test dice qué error pilla:

- solo viaja lo registrado, y cada registro sale a la hora de su `sim_time` registrado (V12;
  y el pacer, si esperase a la hora verdadera);
- el censo con `W` = 1.140: los abiertos son los de la verdad (V32) y los números son los de
  la grabación entera, con huecos (V33); una corrección de un episodio cerrado va al directo;
- la reemisión (`RecordedLog`) publica lo mismo que la sala;
- `parar` con registros en la sala: el `fin` cuenta solo lo publicado;
- los errores de uso: sala sin `registro` en el `inicio`, o al revés.
"""

import pytest
from registro_factory import (
    DERIVED,
    HORIZON,
    RUN,
    SEED,
    START,
    make_profile,
    run_l,
    scenario_l,
    scenario_l_dice,
)
from runaway import check_calls

from edsim.clinical_record import Record, RecordStream, record_json
from edsim.live.clock import FakeClock
from edsim.live.control import STOP, Command, NoControl, ScriptedControl
from edsim.live.directo import (
    LogSource,
    MemoryLiveSink,
    RecordedLog,
    RecordInfo,
    RunEnd,
    RunInfo,
    RunStart,
    run_live,
)
from edsim.live.pacer import Pacer

RECORD_INFO = RecordInfo(RUN, "prueba", SEED)
INFO = RunInfo(DERIVED, "replay", 4, 2026, START, False, RECORD_INFO)
TRUE_INFO = RunInfo(RUN, "replay", 4, 2026, START, False)


class TimedSink(MemoryLiveSink):
    """Un MemoryLiveSink que anota el instante del reloj de cada publicación, con tope."""

    LIMIT = 10_000

    def __init__(self, clock: FakeClock) -> None:
        super().__init__()
        self.clock = clock
        self.times: list[float] = []

    def _note(self) -> None:
        check_calls(len(self.times) + 1, self.LIMIT, "TimedSink")
        self.times.append(round(self.clock.monotonic(), 6))

    def start(self, message):
        self._note()
        super().start(message)

    def write(self, event):
        self._note()
        super().write(event)

    def end(self, message):
        self._note()
        super().end(message)


def l_recording():
    return RecordStream(make_profile(), SEED, horizon=HORIZON, run_id=RUN, dice=scenario_l_dice())


def run_l_live(start: float, *, recording=None, script=(), info=INFO):
    """El escenario L en directo, ×60 (un minuto simulado por segundo real) desde 0 s."""
    clock = FakeClock()
    sink = TimedSink(clock)
    end = run_live(
        LogSource(scenario_l(), HORIZON),
        Pacer(clock, 60, (0.0, 0.0)),
        ScriptedControl(clock, script),
        sink,
        start=start,
        horizon=HORIZON,
        run_info=info,
        recording=l_recording() if recording is None else recording,
    )
    return end, sink


def numbers(items) -> list[str]:
    return [item.event_id.removeprefix(f"{DERIVED}-").lstrip("0") for item in items]


def test_solo_viaja_lo_registrado_y_cada_registro_sale_a_su_hora():
    """Con `W` = 1.000, todo es directo: los siete registros, ninguno de la verdad (V12), y el
    triaje de L3 sale a 1.031,2 (31,2 s), su hora registrada, detrás de la llegada de 1.028,0."""
    end, sink = run_l_live(1000.0)

    assert all(isinstance(item, Record) for item in sink.events)
    assert {item.run_id for item in sink.events} == {DERIVED}
    assert [record_json(r) for r in sink.events] == [record_json(r) for r in run_l().records]
    assert numbers(sink.events) == ["1", "2", "3", "4", "5", "6", "7"]
    assert sink.times == [0.0, 20.0, 22.5, 28.0, 31.2, 60.0, 60.5, 166.2, 440.0]
    assert sink.run_start.info == INFO
    assert (sink.run_start.census_episodes, sink.run_start.census_events) == (0, 0)
    assert end == RunEnd(DERIVED, "horizonte", HORIZON, f"{DERIVED}-000000007", 7)


def test_el_censo_de_lo_registrado_sale_de_los_abiertos_de_la_verdad():
    """`W` = 1.140: EP-000001 salió en 1.135 (cerrado en la verdad, aunque su salida se olvidó);
    EP-000002 sigue dentro. Censo = el registro 3 (la llegada de EP-000002), con su número de
    la grabación entera; directo = la corrección 7, de un episodio ya cerrado (V32, V33)."""
    end, sink = run_l_live(1140.0)

    items = sink.items
    assert isinstance(items[0], RunStart) and isinstance(items[-1], RunEnd)
    assert numbers(sink.events) == ["3", "7"]
    assert [(r.event_type, r.episode_id) for r in sink.events] == [
        ("patient_arrived", "EP-000002"),
        ("record_corrected", "EP-000001"),
    ]
    assert (sink.run_start.census_episodes, sink.run_start.census_events) == (1, 1)
    assert sink.times == [0.0, 0.0, 26.2, 300.0]
    assert end == RunEnd(DERIVED, "horizonte", HORIZON, f"{DERIVED}-000000007", 2)


@pytest.mark.parametrize("start", [1000.0, 1140.0])
def test_la_reemision_publica_lo_mismo_que_la_sala(start):
    """`RecordedLog` (los registros de `record`, ya ordenados) frente a `RecordStream`."""
    _, from_room = run_l_live(start)
    _, from_log = run_l_live(start, recording=RecordedLog(run_l().records))

    assert from_log.items == from_room.items
    assert from_log.times == from_room.times


def test_parar_con_registros_en_la_sala_solo_cuenta_lo_publicado():
    """Parar a los 25 s (minuto 1.025): han salido el 1 y el 2; los demás no se publican."""
    end, sink = run_l_live(1000.0, script=[(25.0, Command(STOP))])

    assert numbers(sink.events) == ["1", "2"]
    assert end.reason == "parar"
    assert end.published == 2
    assert end.last_event_id == f"{DERIVED}-000000002"
    assert end.sim_time == pytest.approx(1025.0, abs=0.25)  # la orden se ve en un tramo de 0,2 s


def test_lo_registrado_y_el_bloque_registro_van_juntos():
    with pytest.raises(ValueError, match="needs both"):
        run_l_live(1000.0, info=TRUE_INFO)
    with pytest.raises(ValueError, match="needs both"):
        run_live(
            LogSource(scenario_l(), HORIZON),
            Pacer(FakeClock(), 60, (0.0, 0.0)),
            NoControl(),
            MemoryLiveSink(),
            start=1000.0,
            horizon=HORIZON,
            run_info=INFO,
        )


def test_un_registro_que_retrocede_no_vale_en_la_reemision():
    records = run_l().records
    with pytest.raises(ValueError, match="goes back"):
        RecordedLog([records[3], records[2]])
