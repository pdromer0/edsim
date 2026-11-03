"""Check editor numbers against independently calculated examples."""

import copy
import math
from itertools import pairwise
from statistics import NormalDist

import pytest

import edsim.runs as runs
from edsim.runs import read_center_values, summarize_center


@pytest.fixture
def values():
    return read_center_values("tests/data/centro_ejemplo.toml")


def test_base_summary_and_input_preserved(values):
    before = copy.deepcopy(values)
    summary = summarize_center(values)
    assert values == before
    assert summary.raw_share_total == pytest.approx(100)
    assert summary.normalized_level_shares == pytest.approx((0.003, 0.121, 0.336, 0.526, 0.014))
    assert summary.tests_percentage == pytest.approx(55.41)
    assert summary.admission_percentage == pytest.approx(12.843)
    assert [d.key for d in summary.durations] == [
        "duraciones.triaje",
        "duraciones.valoracion",
        "duraciones.reevaluacion",
        "duraciones.respuesta_pruebas",
    ]


def test_known_lognormal_density_mean_and_grid(values):
    values["duraciones.triaje"] = [1, math.exp(NormalDist().inv_cdf(0.9))]
    duration = summarize_center(values).durations[0]
    assert duration.mean_minutes == pytest.approx(math.exp(0.5))
    assert len(duration.curve_minutes) == len(duration.curve_density) == 122
    assert (duration.curve_minutes[0], duration.curve_density[0]) == (0, 0)
    assert duration.curve_minutes[61] == pytest.approx(1)
    assert duration.curve_density[61] == pytest.approx(1 / math.sqrt(2 * math.pi))
    assert duration.curve_minutes[1] == pytest.approx(math.exp(-3))
    assert duration.curve_minutes[-1] == pytest.approx(math.exp(3))
    assert all(a < b for a, b in pairwise(duration.curve_minutes))
    assert all(p >= 0 for p in duration.curve_density)


def test_weighted_percentages_and_unnormalized_sum(values):
    values["triaje.reparto_niveles"] = [1, 3, 0, 0, 0]
    values["pruebas.probabilidad"] = [1, 0, 0, 0, 0]
    values["destino.probabilidad_ingreso"] = [0, 1, 0, 0, 0]
    summary = summarize_center(values)
    assert summary.raw_share_total == 4
    assert summary.normalized_level_shares == (0.25, 0.75, 0, 0, 0)
    assert summary.tests_percentage == 25
    assert summary.admission_percentage == 75


def test_invalid_values_raise_and_summary_is_public(values):
    values["recursos.boxes"] = 0
    with pytest.raises(ValueError, match="recursos.boxes"):
        summarize_center(values)
    for name in ("summarize_center", "CenterSummary", "DurationSummary"):
        assert name in runs.__all__
        assert getattr(runs, name) is not None
