"""Offered work against occupation identities and independent convolution sums."""

import math
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pytest

import edsim.runs as runs
import edsim.runs.offered as offered
from edsim.arrivals.rate import rate
from edsim.engine.clinical import PatientDraws
from edsim.engine.validation import draws_sample, flat_profile
from edsim.runs import OfferedWork, load_center, load_profile, offered_work

CONFIG = Path(__file__).parents[1] / "config"
POOLS = ("medicos", "boxes", "enfermeria_triaje")
SEED = 73001
DISCRETIZATION_MINUTES = {"enfermeria_triaje": 0.5, "medicos": 2.0, "boxes": 1.0}


@pytest.fixture(scope="module")
def center():
    return load_center(CONFIG / "centro.toml")


@pytest.fixture(scope="module")
def profile():
    return load_profile(CONFIG / "llegadas.toml")


@pytest.fixture(scope="module")
def default_draws(center):
    return draws_sample(center, 50_000, seed=SEED)


@pytest.fixture(scope="module")
def default_work(center, profile):
    return offered_work(center, profile)


def occupations(draws):
    """Derive continuous and one-minute occupation from the clinical timeline."""
    # A level 1 is classified at the door: no nurse time (task 4.1).
    triage = np.array([0.0 if d.level == 1 else d.triage_time for d in draws])
    assessment = np.array([d.assessment_time for d in draws])
    reassessment = np.array([d.reassessment_time for d in draws])
    turnaround = np.array([d.test_turnaround for d in draws])
    tests = np.array([d.needs_tests for d in draws])
    assessed = triage + assessment
    results = assessed + turnaround
    departure = assessed + tests * (turnaround + reassessment)
    continuous = {
        "enfermeria_triaje": triage,
        "medicos": assessment + tests * reassessment,
        "boxes": assessment + tests * (turnaround + reassessment),
    }
    # The midpoint grid counts ceil(b - 1/2) - ceil(a - 1/2) in [a, b).
    # This is an oracle for the integral's mass, not another convolution.
    rounded = {
        "enfermeria_triaje": np.ceil(triage - 0.5),
        "medicos": np.ceil(assessed - 0.5)
        - np.ceil(triage - 0.5)
        + tests * (np.ceil(results + reassessment - 0.5) - np.ceil(results - 0.5)),
        "boxes": np.ceil(departure - 0.5) - np.ceil(triage - 0.5),
    }
    return continuous, rounded, float(departure.max())


def assert_little(work, profile, draws):
    continuous, rounded, _ = occupations(draws)
    lam = profile.daily_base / 1440
    for pool in POOLS:
        mean_load = float(np.trapezoid(work.load[pool]) / (work.days * 1440))
        assert mean_load == pytest.approx(lam * rounded[pool].mean(), rel=1e-12, abs=1e-12)
        # At most 1/2 minute per rounded endpoint; triage starts at exact 0,
        # doctors have up to two intervals, and boxes have one interval.
        bound = lam * DISCRETIZATION_MINUTES[pool]
        assert abs(mean_load - lam * continuous[pool].mean()) <= bound + 1e-12


def test_base_prehistory_uses_sample_maximum(default_work, default_draws, profile):
    _, _, maximum_age = occupations(default_draws)
    assert maximum_age > 1440  # A real tail observation, not a vacuous warmup test.
    assert default_work.prior_days == max(1, math.ceil(maximum_age / 1440))
    assert default_work.prior_days == 2
    assert default_work.start_date == profile.start_date
    assert default_work.window_kind == "offered_in_regime"
    assert default_work.days == 7
    np.testing.assert_array_equal(default_work.minutes, np.arange(7 * 1440 + 1))
    assert (
        set(default_work.load)
        == set(default_work.capacity)
        == set(default_work.utilization)
        == set(POOLS)
    )
    for pool in POOLS:
        assert default_work.load[pool].shape == default_work.capacity[pool].shape == (10081,)
        assert default_work.load[pool][0] > 0
        assert len(default_work.utilization[pool]) == 3


@pytest.mark.parametrize("periodic", [False, True])
def test_little_and_lognormal_means(center, profile, default_draws, periodic):
    hypothesis = replace(profile, weekday_factors=(1,) * 7, month_factors=(1,) * 12)
    if not periodic:
        hypothesis = replace(hypothesis, hour_factors=(1,) * 24)
    work = offered_work(center, hypothesis)
    assert_little(work, hypothesis, default_draws)

    # No lognormal_params or analytical helpers from the implementation.
    def mean_lognormal(parameters):
        median, p90 = parameters
        sigma = math.log(p90 / median) / NormalDist().inv_cdf(0.9)
        return median * math.exp(sigma**2 / 2)

    probability = sum(
        s * p for s, p in zip(center.level_shares, center.test_probability, strict=True)
    )
    triage = mean_lognormal(center.triage_time)
    assessment = mean_lognormal(center.assessment_time)
    reassessment = mean_lognormal(center.reassessment_time)
    turnaround = mean_lognormal(center.test_turnaround)
    expected = {
        "enfermeria_triaje": triage,
        "medicos": assessment + probability * reassessment,
        "boxes": assessment + probability * (turnaround + reassessment),
    }
    continuous, _, _ = occupations(default_draws)
    lam = hypothesis.daily_base / 1440
    for pool in POOLS:
        standard_error = float(continuous[pool].std(ddof=1) / math.sqrt(len(default_draws)))
        tolerance = lam * (4 * standard_error + DISCRETIZATION_MINUTES[pool])
        observed = float(np.trapezoid(work.load[pool]) / (work.days * 1440))
        assert abs(observed - lam * expected[pool]) <= tolerance


def test_long_durations_need_multiple_prior_days_and_keep_little(center, profile):
    long_center = replace(
        center, test_turnaround=(3 * 1440, 3 * 1440 + 1), test_probability=(1,) * 5
    )
    periodic = replace(profile, weekday_factors=(1,) * 7, month_factors=(1,) * 12)
    draws = draws_sample(long_center, 32, seed=SEED)
    _, _, maximum_age = occupations(draws)
    work = offered_work(long_center, periodic, sample_size=32)
    assert_little(work, periodic, draws)
    assert work.prior_days == max(1, math.ceil(maximum_age / 1440))
    assert work.prior_days > 1


@pytest.fixture
def controlled_draws(monkeypatch):
    draws = [
        PatientDraws(3, 5.0, 20.0, 10.0, False, 30.0, False),
        PatientDraws(3, 7.0, 10.0, 10.0, True, 30.0, False),
    ]
    calls = []

    def sample(center, n, seed):
        calls.append((n, seed))
        return draws

    monkeypatch.setattr(offered, "draws_sample", sample)
    return draws, calls


def test_short_prehistory_and_constant_staff_utilization(center, controlled_draws):
    _, calls = controlled_draws
    constant = replace(center, doctors=(4,) * 3, triage_nurses=(2,) * 3, boxes=10)
    work = offered_work(constant, flat_profile(daily_base=144), days=2, sample_size=2)
    assert calls == [(2, SEED)]
    assert work.prior_days == 1
    expected_load = {"medicos": 2.0, "boxes": 3.5, "enfermeria_triaje": 0.6}
    expected_capacity = {"medicos": 4, "boxes": 10, "enfermeria_triaje": 2}
    for pool in POOLS:
        np.testing.assert_allclose(work.load[pool], expected_load[pool], rtol=1e-12)
        np.testing.assert_array_equal(work.capacity[pool], expected_capacity[pool])
        assert work.utilization[pool] == pytest.approx(
            (expected_load[pool] / expected_capacity[pool],) * 3, rel=1e-12
        )


@pytest.mark.parametrize("starts", [(8, 15, 22), (0, 7, 19)])
def test_capacities_at_boundaries_and_night_utilization(center, profile, controlled_draws, starts):
    changed = replace(
        center, shift_starts=starts, doctors=(3, 5, 7), triage_nurses=(2, 4, 6), boxes=9
    )
    work = offered_work(changed, profile, days=2, sample_size=2)
    minute = work.minutes % 1440
    morning = (minute >= starts[0] * 60) & (minute < starts[1] * 60)
    afternoon = (minute >= starts[1] * 60) & (minute < starts[2] * 60)
    night = ~(morning | afternoon)
    for pool, staff in (("medicos", changed.doctors), ("enfermeria_triaje", changed.triage_nurses)):
        for index, mask in enumerate((morning, afternoon, night)):
            np.testing.assert_array_equal(work.capacity[pool][mask], staff[index])
            area = (work.load[pool][:-1] + work.load[pool][1:]) / 2
            expected = area[mask[:-1]].sum() / (mask[:-1].sum() * staff[index])
            assert work.utilization[pool][index] == pytest.approx(expected, rel=1e-12)
    np.testing.assert_array_equal(work.capacity["boxes"], 9)


def manual_load(draws, pool, minute, calendar_profile):
    """Sum lambda at prior midpoints times empirical occupation at those ages."""
    age = np.arange(minute) + 0.5
    probability = np.zeros(age.size)
    for draw in draws:
        assessed = draw.triage_time + draw.assessment_time
        results = assessed + draw.test_turnaround
        if pool == "enfermeria_triaje":
            held = age < draw.triage_time
        elif pool == "medicos":
            held = (age >= draw.triage_time) & (age < assessed)
            if draw.needs_tests:
                held |= (age >= results) & (age < results + draw.reassessment_time)
        else:
            departure = assessed + (
                draw.test_turnaround + draw.reassessment_time if draw.needs_tests else 0
            )
            held = (age >= draw.triage_time) & (age < departure)
        probability += held / len(draws)
    return float(np.sum(rate(minute - age, calendar_profile) * probability))


@pytest.mark.parametrize("start", [date(2026, 2, 1), date(2026, 2, 2)])
def test_real_calendar_prehistory_and_general_convolution(
    center, profile, controlled_draws, monkeypatch, start
):
    draws, _ = controlled_draws
    hypothesis = replace(profile, start_date=start)
    original = offered.offered_load_by_pool
    seen_profiles = []

    def inspect(previous, sample, horizon):
        seen_profiles.append(previous)
        assert previous is not hypothesis
        assert previous.start_date == start - timedelta(days=1)
        assert horizon == 3 * 1440
        for day in range(3):
            actual_day = replace(hypothesis, start_date=previous.start_date + timedelta(days=day))
            within_day = np.array([0.5, 29.5, 100.5, 900.5, 1439.5])
            np.testing.assert_allclose(
                rate(day * 1440 + within_day, previous), rate(within_day, actual_day), rtol=1e-14
            )
        return original(previous, sample, horizon)

    monkeypatch.setattr(offered, "offered_load_by_pool", inspect)
    work = offered_work(center, hypothesis, days=2, sample_size=2)
    assert len(seen_profiles) == 1
    assert hypothesis.start_date == work.start_date == start
    assert seen_profiles[0].start_date < start
    if start.day == 1:
        assert seen_profiles[0].start_date.month != start.month
    else:
        assert seen_profiles[0].start_date.weekday() == 6 and start.weekday() == 0
    for minute in (0, 1, 30, 480, 1439, 1440, 2000, 2880):
        for pool in POOLS:
            expected = manual_load(draws, pool, 1440 + minute, seen_profiles[0])
            assert work.load[pool][minute] == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_repeatability_and_separate_sample_seed(center, profile):
    a = offered_work(center, profile, days=1, sample_size=100)
    b = offered_work(center, profile, days=1, sample_size=100)
    c = offered_work(center, profile, days=1, sample_size=100, sample_seed=73002)
    for pool in POOLS:
        np.testing.assert_array_equal(a.load[pool], b.load[pool])
        assert a.utilization[pool] == b.utilization[pool]
        assert not np.array_equal(a.load[pool], c.load[pool])
    # Unit factors remain bit-identical after replace(), isolating the CV:
    # replacing a general profile re-normalizes its factors up to roundoff.
    flat = flat_profile()
    no_daily_effect = offered_work(center, flat, days=1, sample_size=100)
    positive_cv = offered_work(center, replace(flat, daily_cv=0.5), days=1, sample_size=100)
    for pool in POOLS:
        np.testing.assert_array_equal(positive_cv.load[pool], no_daily_effect.load[pool])


@pytest.mark.parametrize("argument", ["days", "sample_size", "sample_seed"])
@pytest.mark.parametrize("value", [True, 1.0, -1, "1", None])
def test_invalid_arguments_do_not_sample(center, profile, monkeypatch, argument, value):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid arguments reached sampling")

    monkeypatch.setattr(offered, "draws_sample", unexpected)
    with pytest.raises(ValueError, match=argument):
        offered_work(center, profile, **{argument: value})


@pytest.mark.parametrize("argument", ["days", "sample_size"])
def test_positive_counts_reject_zero(center, profile, argument):
    with pytest.raises(ValueError, match=argument):
        offered_work(center, profile, **{argument: 0})


def test_zero_sample_seed_and_one_patient_are_valid(center, profile):
    result = offered_work(center, profile, days=1, sample_size=1, sample_seed=0)
    assert isinstance(result, OfferedWork)
    assert result.minutes.size == 1441
    assert np.all(np.isfinite(result.load["medicos"]))


def test_offered_api_is_public():
    assert "OfferedWork" in runs.__all__ and runs.OfferedWork is OfferedWork
    assert "offered_work" in runs.__all__ and runs.offered_work is offered_work
