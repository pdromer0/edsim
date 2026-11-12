"""Block boundaries retain carried values and integrate step areas exactly."""

from types import MappingProxyType

import numpy as np
import pytest

from edsim.engine.analysis import CURVES, OUTCOME_CURVES, StepCurves
from edsim.runs import curve_blocks, curve_steps


@pytest.fixture
def curves():
    return StepCurves(
        np.array([0.0, 10.0, 20.0, 30.0, 38.0]),
        MappingProxyType({name: np.array([0, 7, 1, 99, 500]) for name in CURVES}),
        38.0,
    )


def test_carried_maximum_exact_area_and_partial_last_block(curves):
    blocks = curve_blocks(curves, "census", 15, 38)
    np.testing.assert_array_equal(blocks.edges, [15, 30, 38])
    np.testing.assert_array_equal(blocks.mean, [3, 99])
    np.testing.assert_array_equal(blocks.maximum, [7, 99])
    assert blocks.maximum.dtype == np.int64
    assert np.dot(np.diff(blocks.edges), blocks.mean) == curves.area("census", 15, 38)


def test_no_event_in_block_and_change_exactly_at_start(curves):
    blocks = curve_blocks(curves, "census", 10, 20, block_minutes=5)
    np.testing.assert_array_equal(blocks.edges, [10, 15, 20])
    np.testing.assert_array_equal(blocks.mean, [7, 7])
    np.testing.assert_array_equal(blocks.maximum, [7, 7])


def test_whole_curve_mean_matches_integrated_blocks(curves):
    blocks = curve_blocks(curves, "census", 0, 38, block_minutes=7)
    assert np.average(blocks.mean, weights=np.diff(blocks.edges)) == pytest.approx(
        curves.mean("census", 0, 38)
    )
    np.testing.assert_array_equal(blocks.maximum, [0, 7, 7, 1, 99, 99])


def test_steps_clip_both_ends_and_copy_the_values(curves):
    steps = curve_steps(curves, "nurses_staff", 15, 35)
    np.testing.assert_array_equal(steps.edges, [15, 20, 30, 35])
    np.testing.assert_array_equal(steps.values, [7, 1, 99])
    steps.values[:] = 0
    np.testing.assert_array_equal(curves["nurses_staff"], [0, 7, 1, 99, 500])


@pytest.mark.parametrize("start,end", [(-1, 10), (10, 10), (11, 10), (0, 40), (0, float("nan"))])
@pytest.mark.parametrize("function", [curve_blocks, curve_steps])
def test_invalid_windows(curves, start, end, function):
    with pytest.raises(ValueError, match="start"):
        function(curves, "census", start, end)


@pytest.mark.parametrize("width", [0, -1, float("inf"), float("nan"), True])
def test_invalid_widths(curves, width):
    with pytest.raises(ValueError, match="block_minutes"):
        curve_blocks(curves, "census", 0, 38, block_minutes=width)


@pytest.mark.parametrize("function", [curve_blocks, curve_steps])
def test_unknown_curve(curves, function):
    with pytest.raises(ValueError, match="curve"):
        function(curves, "missing", 0, 38)


def test_public_exports():
    import edsim.runs as runs

    for name in ("CurveBlocks", "CurveSteps", "curve_blocks", "curve_steps"):
        assert name in runs.__all__


def test_steps_drop_redundant_values_without_moving_changes():
    curves = StepCurves(
        np.array([0.0, 1.0, 2.0, 3.0]),
        MappingProxyType({"nurses_staff": np.array([4, 4, 8, 8])}),
        4.0,
    )
    steps = curve_steps(curves, "nurses_staff", 0.5, 3.5)
    np.testing.assert_array_equal(steps.edges, [0.5, 2, 3.5])
    np.testing.assert_array_equal(steps.values, [4, 8])


@pytest.mark.parametrize("function", [curve_blocks, curve_steps])
def test_las_curvas_de_la_cama_se_leen_como_las_demas(function):
    """Las dos curvas del hito 5 (OUTCOME_CURVES, tarea 5.4) son curvas del análisis."""
    names = CURVES + OUTCOME_CURVES
    curves = StepCurves(
        np.array([0.0, 10.0]),
        MappingProxyType({name: np.array([0, 2]) for name in names}),
        20.0,
    )
    for name in OUTCOME_CURVES:
        result = function(curves, name, 0, 20)
        # De 0 a 10 vale 0 y de 10 a 20 vale 2: media 1 en un bloque de 20, máximo 2.
        if function is curve_blocks:
            assert result.edges[-1] == 20.0
        else:
            np.testing.assert_array_equal(result.values, [0, 2])
    blocks = curve_blocks(curves, "hallway", 0, 20, block_minutes=20)
    np.testing.assert_array_equal(blocks.mean, [1.0])
    np.testing.assert_array_equal(blocks.maximum, [2])
