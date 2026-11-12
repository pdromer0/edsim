"""Format the outcome indicators of milestone 5 without recomputing them."""

from edsim.runs import CensoredValue, OverThreshold
from edsim_app.outcome_frames import format_censored, format_censored_minutes, threshold_frame


def test_a_lower_bound_is_shown_with_its_sign():
    assert format_censored(CensoredValue(250.64, False)) == "≥ 250,6"
    assert format_censored(CensoredValue(818.13, True)) == "818,1"
    assert format_censored(None) == "—"


def test_threshold_share_is_over_the_known_ones():
    row = threshold_frame((OverThreshold(360.0, over=3, known=4, unknown=2),)).iloc[0]
    # 3 / 4 = 75 %: the two unknown are not in the denominator, but they are shown.
    assert row["Umbral (h)"] == "6"
    assert row["Porcentaje (por encima / conocidos)"] == "75,0 %"
    assert (row["Por encima"], row["Conocidos"], row["Sin saber"]) == (3, 4, 2)


def test_minutes_without_a_value_have_no_unit():
    assert format_censored_minutes(None) == "—"
    assert format_censored_minutes(CensoredValue(250.64, False)) == "≥ 250,6 min"
