"""Integer-grid navigation and elapsed-time playback without sleeping."""

import pytest

from edsim_app import replay
from edsim_app.replay import ReplayPosition, advance_playback, start_playback, step_position


@pytest.mark.parametrize(
    "t,amount,expected",
    [
        (623.3, 1, 624),
        (623.3, 10, 633),
        (623.3, -1, 623),
        (623.3, -10, 614),
        (623, 1, 624),
        (623, 10, 633),
        (623, -1, 622),
        (623, -10, 613),
        (0, -10, 0),
        (1439, 10, 1440),
        (1440, -1, 1439),
        (1440, -10, 1430),
    ],
)
def test_step_rule_and_clipping(t, amount, expected):
    position = ReplayPosition(time=t, playing=True)
    step_position(position, amount, 1440)
    assert position.time == expected and not position.playing


@pytest.mark.parametrize("speed", [1, 5, 15, 60])
def test_fractional_start_elapsed_seconds_and_horizon(speed, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(replay, "clock", lambda: now[0])
    position = ReplayPosition(time=623.3, speed=speed)
    start_playback(position, 1440)
    assert position.time == 624 and position.playing
    now[0] += 2.125
    assert not advance_playback(position, 1440)
    assert position.time == 624 + int(2.125 * speed) and position.time.is_integer()
    now[0] += 1000
    assert advance_playback(position, 1440)
    assert position.time == 1440 and not position.playing
    assert not advance_playback(position, 1440)


def test_daily_census_chart_keeps_wall_times_and_marker_without_timezone():
    import pandas as pd

    from edsim_app.charts import replay_census_chart

    frame = pd.DataFrame(
        {
            "Fecha y hora": pd.to_datetime(["2026-01-05T00:00:00", "2026-01-06T00:00:00"]),
            "Censo": [2, 3],
        }
    )
    spec = replay_census_chart(frame, pd.Timestamp("2026-01-05T10:23:18")).to_dict()
    assert spec["layer"][0]["mark"]["interpolate"] == "step-after"
    marker = spec["datasets"][spec["layer"][1]["data"]["name"]]
    assert marker == [{"Instante": "2026-01-05T10:23:18"}]
