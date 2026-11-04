"""Hand-written counterfactuals and short persisted runs for checked comparisons."""

from dataclasses import fields, replace
from pathlib import Path

import pytest

from edsim.runs import (
    RunStore,
    compare_runs,
    read_center_values,
    read_run_episode_truth,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs.compare import DRAW_EFFECTS, PairingCheckError, pairing_blockers


@pytest.fixture(scope="module")
def comparison_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("comparison-runs")
    source = Path("tests/data/centro_ejemplo.toml")
    for name in ("base", "night", "assessment", "probability", "seed"):
        values = read_center_values(source)
        if name == "night":
            values["recursos.medicos"][2] += 1
        elif name == "assessment":
            values["duraciones.valoracion"] = [v * 1.2 for v in values["duraciones.valoracion"]]
        elif name == "probability":
            values["pruebas.probabilidad"][0] += 1e-12
        center = root / f"{name}.toml"
        write_variant(source, values, center)
        simulate_run(
            center,
            "tests/data/llegadas_ejemplo.toml",
            3,
            2027 if name == "seed" else 2026,
            output_dir=root / name,
            run_id=name,
            warmup_days=1,
            origin="app",
        )
    store = RunStore(root)
    return {
        name: (read_run_results(store, name), read_run_episode_truth(store, name))
        for name in ("base", "night", "assessment", "probability", "seed")
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", 9),
        ("profile_fingerprint", "different"),
        ("days", 4),
        ("warmup_days", 0),
    ],
)
def test_each_pairing_blocker(comparison_runs, field, value):
    a, _ = comparison_runs["base"]
    b = replace(a, info=replace(a.info, **{field: value}))
    blockers = pairing_blockers(a, b)
    assert len(blockers) == 1
    assert (blockers[0].field, blockers[0].a, blockers[0].b) == (
        field,
        getattr(a.info, field),
        value,
    )
    assert not pairing_blockers(a, a)


def test_draw_effects_are_exhaustive_and_immutable():
    assert DRAW_EFFECTS.keys() == read_center_values("config/centro.toml").keys()
    assert DRAW_EFFECTS["triaje.reparto_niveles"] == {"level", "needs_tests", "admitted"}
    for key in (
        "turnos.inicio",
        "recursos.medicos",
        "recursos.boxes",
        "recursos.enfermeria_triaje",
    ):
        assert not DRAW_EFFECTS[key]
    for key, field in (
        ("triaje", "triage_time"),
        ("valoracion", "assessment_time"),
        ("reevaluacion", "reassessment_time"),
        ("respuesta_pruebas", "test_turnaround"),
    ):
        assert DRAW_EFFECTS[f"duraciones.{key}"] == {field}
    assert DRAW_EFFECTS["pruebas.probabilidad"] == {"needs_tests"}
    assert DRAW_EFFECTS["destino.probabilidad_ingreso"] == {"admitted"}
    with pytest.raises(TypeError):
        DRAW_EFFECTS["recursos.boxes"] = frozenset({"level"})


@pytest.mark.parametrize(
    "name,kind,changed_field",
    [
        ("base", "same_draws", None),
        ("night", "same_draws", None),
        ("assessment", "different_draws", "assessment_time"),
        ("probability", "different_draws", None),
    ],
)
def test_configuration_and_exact_draws(comparison_runs, name, kind, changed_field):
    a, ta = comparison_runs["base"]
    b, tb = comparison_runs[name]
    check = compare_runs(a, b, ta, tb).pairing
    assert check.kind == kind
    assert len(ta) > 0 and any(t.level == 1 for t in ta.values())
    for change in check.draw_differences:
        assert change.total == len(ta)
        assert change.changed == (len(ta) if change.field == changed_field else 0)
    if name == "night":
        by_id = {e.episode_id: e for e in b.analysis.table}
        assert any(
            e.stay != by_id[e.episode_id].stay
            for e in a.analysis.table
            if e.departure is not None and by_id[e.episode_id].departure is not None
        )


def test_other_seed_is_programming_error(comparison_runs):
    a, ta = comparison_runs["base"]
    b, tb = comparison_runs["seed"]
    with pytest.raises(ValueError, match="pairable") as error:
        compare_runs(a, b, ta, tb)
    assert type(error.value) is ValueError


@pytest.mark.parametrize(
    "field,value",
    [
        ("arrival_time", 1.0),
        ("level", 5),
        ("triage_time", 999.0),
        ("assessment_time", 999.0),
        ("reassessment_time", 999.0),
        ("needs_tests", False),
        ("test_turnaround", 999.0),
        ("admitted", True),
    ],
)
def test_corrupted_truth_has_field_and_count(comparison_runs, field, value):
    a, ta = comparison_runs["base"]
    b, original = comparison_runs["night"]
    tb = dict(original)
    key = next(k for k, t in tb.items() if getattr(t, field) != value)
    tb[key] = replace(tb[key], **{field: value})
    with pytest.raises(PairingCheckError) as error:
        compare_runs(a, b, ta, tb)
    assert error.value.field == field and error.value.affected == 1
    assert "ground_truth_episodios.csv" in str(error.value)
    assert error.value.run_ids == ("base", "night")


def test_missing_and_wrong_identity_truth(comparison_runs):
    a, ta = comparison_runs["base"]
    missing = dict(ta)
    key = next(iter(missing))
    del missing[key]
    with pytest.raises(PairingCheckError, match="episode_id"):
        compare_runs(a, a, ta, missing)
    wrong = dict(ta)
    wrong[key] = replace(wrong[key], episode_id="wrong")
    with pytest.raises(PairingCheckError, match="episode_id"):
        compare_runs(a, a, ta, wrong)


def test_all_draws_include_unused_and_censored_patients(comparison_runs):
    a, truth = comparison_runs["base"]
    assert set(f.name for f in fields(next(iter(truth.values())))) >= {
        "reassessment_time",
        "test_turnaround",
    }
    key = next(e.episode_id for e in a.analysis.table if e.departure is None)
    corrupted = dict(truth)
    corrupted[key] = replace(corrupted[key], reassessment_time=999)
    with pytest.raises(PairingCheckError, match="reassessment_time"):
        compare_runs(a, a, truth, corrupted)
    key = next(k for k, t in truth.items() if not t.needs_tests)
    corrupted = dict(truth)
    corrupted[key] = replace(corrupted[key], test_turnaround=999)
    with pytest.raises(PairingCheckError, match="test_turnaround"):
        compare_runs(a, a, truth, corrupted)


@pytest.fixture
def hand_comparison(comparison_runs):
    from edsim.runs import TRUTH_ABS_TOL_MINUTES, EpisodeTruth

    template, _ = comparison_runs["base"]
    tol = TRUTH_ABS_TOL_MINUTES
    times = [
        (2 * tol, 0),
        (tol, 0),
        (0, 0),
        (0, tol),
        (0, 2 * tol),
        (20, 10),
        (10, 30),
        (10, None),
        (10, None),
        (None, 10),
        (None, None),
    ]
    record = next(e for e in template.analysis.table if e.departure is not None)
    tables = [[], []]
    truth = {}
    for i, pair in enumerate(times):
        key = f"EP-{i:06}"
        truth[key] = EpisodeTruth(key, i, 0, 3, 5, 20, 10, False, 60, False)
        for table, value in zip(tables, pair, strict=True):
            table.append(
                replace(
                    record,
                    episode_id=key,
                    arrival=0,
                    level=3,
                    departure=value,
                    door_to_doctor=value,
                    displacements=0,
                )
            )
    result = []
    for table in tables:
        metrics = replace(template.analysis.metrics, start=0, end=4320)
        result.append(
            replace(
                template,
                analysis=replace(template.analysis, table=tuple(table), metrics=metrics),
                kpis=replace(template.kpis, n=sum(e.departure is not None for e in table)),
            )
        )
    return *result, truth


def test_hand_counts_signs_exact_tolerance_and_exclusions(hand_comparison):
    from edsim.runs import compare_runs

    a, b, truth = hand_comparison
    result = compare_runs(a, b, truth, truth)
    assert len(result.episodes) == 7
    assert (result.excluded.only_a, result.excluded.only_b, result.excluded.neither) == (2, 1, 1)
    assert (result.summary.unfinished_a, result.summary.unfinished_b) == (2, 3)
    assert (result.summary.completed_a, result.summary.completed_b) == (9, 8)
    assert result.episodes[5].stay_difference == -10
    assert result.episodes[6].stay_difference == 20
    for summary in result.differences:
        assert (summary.improved, summary.worsened, summary.unchanged) == (2, 2, 3)
        assert summary.n == 7
        assert summary.improved_share == summary.worsened_share == 2 / 7
        assert summary.unchanged_share == 3 / 7
        assert sum(bin.n for bin in summary.histogram) == 4
    assert [row.stay_change for row in result.episodes] == [
        "improved",
        "unchanged",
        "unchanged",
        "unchanged",
        "worsened",
        "improved",
        "worsened",
    ]
    assert [e.episode_id for e in result.most_affected[:2]] == ["EP-000006", "EP-000005"]


def test_summary_values_none_zero_and_types(hand_comparison):
    from edsim.runs import compare_run_summary

    a, b, _ = hand_comparison
    a = replace(
        a,
        kpis=replace(
            a.kpis, arrivals_per_day=10, census_mean=0, stay_mean=None, admission_share=0.2
        ),
    )
    b = replace(
        b,
        kpis=replace(
            b.kpis,
            arrivals_per_day=15,
            census_mean=10,
            stay_mean=20,
            stay_p90=None,
            admission_share=0.3,
        ),
    )
    summary = compare_run_summary(a, b)
    kpis = {row.field: row for row in summary.kpis}
    assert len(kpis) == 9 and "n" not in kpis
    assert kpis["arrivals_per_day"].difference == 5
    assert kpis["arrivals_per_day"].relative_change == 0.5
    assert kpis["census_mean"].difference == 10
    assert kpis["census_mean"].relative_change is None
    assert kpis["stay_mean"].difference is None
    assert kpis["stay_mean"].relative_change is None
    assert kpis["stay_p90"].difference is None
    assert kpis["admission_share"].difference == pytest.approx(0.1)
    for name in ("pairing", "episodes", "differences", "most_affected", "excluded"):
        assert not hasattr(summary, name)
    for level, source in zip(summary.levels, a.analysis.metrics.by_level, strict=True):
        assert level.level == source.level and level.a.n == source.n
        for wait in level.a.waits:
            assert wait.mean == source.mean[wait.measure]
            assert wait.p90 == source.p90[wait.measure]


def test_same_real_run_zero_everywhere(comparison_runs):
    from edsim.runs import compare_run_summary, compare_runs

    a, truth = comparison_runs["base"]
    result = compare_runs(a, a, truth, truth)
    assert result.summary == compare_run_summary(a, a)
    assert not result.summary.metadata_differences and not result.summary.center_differences
    assert result.pairing.kind == "same_draws"
    assert len(result.episodes) == a.kpis.n > 0
    for kpi in result.summary.kpis:
        assert kpi.difference == 0
        assert kpi.relative_change == (0 if kpi.a else None)
    assert all(e.stay_difference == e.door_to_doctor_difference == 0 for e in result.episodes)
    for difference in result.differences:
        assert difference.unchanged_share == 1
        assert difference.improved == difference.worsened == 0
        assert difference.histogram == ()


@pytest.mark.parametrize("name", ["night", "assessment"])
def test_real_pair_symmetry_sign_oracle_and_histogram(comparison_runs, name):
    from edsim.runs import compare_runs

    a, ta = comparison_runs["base"]
    b, tb = comparison_runs[name]
    ab, ba = compare_runs(a, b, ta, tb), compare_runs(b, a, tb, ta)
    assert ab.episodes and any(e.stay_difference for e in ab.episodes)
    reverse = {e.episode_id: e for e in ba.episodes}
    for e in ab.episodes:
        other = reverse[e.episode_id]
        assert e.stay_difference == e.stay_b - e.stay_a
        assert other.stay_difference == -e.stay_difference
        assert e.door_to_doctor_difference == e.door_to_doctor_b - e.door_to_doctor_a
        assert other.door_to_doctor_difference == -e.door_to_doctor_difference
    assert ab.excluded.only_a == ba.excluded.only_b
    assert ab.excluded.only_b == ba.excluded.only_a
    assert ab.excluded.neither == ba.excluded.neither
    for first, second in zip(ab.differences, ba.differences, strict=True):
        assert first.improved == second.worsened
        assert first.worsened == second.improved
        assert first.unchanged == second.unchanged
        assert sum(bin.n for bin in first.histogram) == first.improved + first.worsened
    assert [e.episode_id for e in ab.most_affected] == [e.episode_id for e in ba.most_affected]
    for first, second in zip(ab.summary.kpis, ba.summary.kpis, strict=True):
        assert first.difference == -second.difference


def test_pair_by_identity_not_position(hand_comparison):
    from edsim.runs import compare_runs

    a, b, truth = hand_comparison
    expected = compare_runs(a, b, truth, truth)
    b = replace(b, analysis=replace(b.analysis, table=tuple(reversed(b.analysis.table))))
    assert compare_runs(a, b, truth, dict(reversed(list(truth.items())))) == expected


def test_no_pairs_and_empty_level(hand_comparison):
    from edsim.runs import compare_runs

    a, b, truth = hand_comparison
    a = replace(
        a,
        analysis=replace(
            a.analysis, table=tuple(replace(e, departure=None) for e in a.analysis.table)
        ),
    )
    result = compare_runs(a, b, truth, truth)
    assert not result.episodes and not result.most_affected
    assert result.excluded.only_b == b.kpis.n
    for summary in result.differences:
        assert summary.n == 0 and summary.unchanged_share is None
        assert summary.histogram == ()
    source = b.analysis.metrics.by_level[0]
    empty = replace(
        source, n=0, mean={key: None for key in source.mean}, p90={key: None for key in source.p90}
    )
    b = replace(
        b,
        analysis=replace(
            b.analysis,
            metrics=replace(b.analysis.metrics, by_level=(empty, *b.analysis.metrics.by_level[1:])),
        ),
    )
    result = compare_runs(a, b, truth, truth)
    assert result.summary.levels[0].b.n == 0
    assert all(wait.mean is None and wait.p90 is None for wait in result.summary.levels[0].b.waits)


def test_arrival_mismatch_even_inside_log_tolerance(comparison_runs):
    from edsim.runs import TRUTH_ABS_TOL_MINUTES, compare_runs

    a, ta = comparison_runs["base"]
    b, original = comparison_runs["night"]
    tb = dict(original)
    key = next(iter(tb))
    tb[key] = replace(tb[key], arrival_time=tb[key].arrival_time + TRUTH_ABS_TOL_MINUTES / 2)
    with pytest.raises(PairingCheckError, match="minutos de llegada"):
        compare_runs(a, b, ta, tb)


def test_window_boundaries_and_warmup_are_excluded(hand_comparison):
    from edsim.runs import compare_runs

    a, b, truth = hand_comparison
    updated_truth = dict(truth)
    sides = []
    for result in (a, b):
        table = []
        for index, record in enumerate(result.analysis.table):
            arrival = 0 if index == 0 else 20 if index == 1 else 10
            stay = record.stay
            table.append(
                replace(record, arrival=arrival, departure=None if stay is None else arrival + stay)
            )
            updated_truth[record.episode_id] = replace(
                truth[record.episode_id], arrival_time=arrival
            )
        sides.append(
            replace(
                result,
                analysis=replace(
                    result.analysis,
                    table=tuple(table),
                    metrics=replace(result.analysis.metrics, start=10, end=20),
                ),
            )
        )
    comparison = compare_runs(*sides, updated_truth, updated_truth)
    assert len(comparison.episodes) == 5
    assert all(e.episode_id not in {"EP-000000", "EP-000001"} for e in comparison.episodes)
    assert comparison.excluded.only_a == 2 and comparison.excluded.neither == 1


def test_ranking_ties_stable_and_limited_to_ten(hand_comparison):
    from edsim.runs import compare_runs

    a, b, truth = hand_comparison
    ta, tb, draws = [], [], {}
    for index in reversed(range(12)):
        key = f"EP-{index:06}"
        ta.append(replace(a.analysis.table[0], episode_id=key, departure=10))
        tb.append(replace(b.analysis.table[0], episode_id=key, departure=20))
        draws[key] = replace(next(iter(truth.values())), episode_id=key, arrival_id=index)
    a = replace(a, analysis=replace(a.analysis, table=tuple(ta)))
    b = replace(b, analysis=replace(b.analysis, table=tuple(tb)))
    comparison = compare_runs(a, b, draws, draws)
    assert [row.episode_id for row in comparison.most_affected] == [f"EP-{i:06}" for i in range(10)]


@pytest.mark.parametrize(
    "deltas",
    [
        (-2.0, -0.05, 0.0, 0.02, 7.0),
        (0.02, 0.04, 7.0),
        (-2.0, -0.04, -0.02),
        (2.0, 2.0, 2.0),
    ],
)
def test_histogram_zero_is_exact_edge_and_no_bin_mixes_signs(hand_comparison, deltas):
    a, b, truth = hand_comparison
    tables = [[], []]
    draws = {}
    for index, delta in enumerate(deltas):
        key = f"EP-{index:06}"
        for table, stay in zip(tables, (max(0, -delta), max(0, delta)), strict=True):
            table.append(
                replace(a.analysis.table[0], episode_id=key, departure=stay, door_to_doctor=stay)
            )
        draws[key] = replace(next(iter(truth.values())), episode_id=key, arrival_id=index)
    a = replace(a, analysis=replace(a.analysis, table=tuple(tables[0])))
    b = replace(b, analysis=replace(b.analysis, table=tuple(tables[1])))
    comparison = compare_runs(a, b, draws, draws)
    for difference in comparison.differences:
        histogram = difference.histogram
        assert 1 <= len(histogram) <= 30
        assert any(bin.left == 0.0 or bin.right == 0.0 for bin in histogram)
        assert all(bin.left < bin.right for bin in histogram)
        assert all(bin.right <= 0.0 or bin.left >= 0.0 for bin in histogram)
        assert sum(bin.n for bin in histogram) == difference.improved + difference.worsened
        assert sum(bin.n for bin in histogram if bin.right <= 0.0) == sum(d < 0 for d in deltas)
        assert sum(bin.n for bin in histogram if bin.left >= 0.0) == sum(d > 0 for d in deltas)
        assert difference.unchanged == deltas.count(0.0)
        widths = [bin.right - bin.left for bin in histogram]
        assert widths == pytest.approx([widths[0]] * len(widths))
