"""Hand-written counterfactuals and short persisted runs for checked comparisons."""

from dataclasses import fields, replace
from pathlib import Path

import pytest

from edsim.runs import (
    RunStore,
    read_center_values,
    read_run_episode_truth,
    read_run_results,
    simulate_run,
    write_variant,
)
from edsim.runs.compare import DRAW_EFFECTS, PairingCheckError, _checked_pairing, pairing_blockers


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
    check = _checked_pairing(a, b, ta, tb)
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
        _checked_pairing(a, b, ta, tb)
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
        _checked_pairing(a, b, ta, tb)
    assert error.value.field == field and error.value.affected == 1
    assert "ground_truth_episodios.csv" in str(error.value)
    assert error.value.run_ids == ("base", "night")


def test_missing_and_wrong_identity_truth(comparison_runs):
    a, ta = comparison_runs["base"]
    missing = dict(ta)
    key = next(iter(missing))
    del missing[key]
    with pytest.raises(PairingCheckError, match="episode_id"):
        _checked_pairing(a, a, ta, missing)
    wrong = dict(ta)
    wrong[key] = replace(wrong[key], episode_id="wrong")
    with pytest.raises(PairingCheckError, match="episode_id"):
        _checked_pairing(a, a, ta, wrong)


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
        _checked_pairing(a, a, truth, corrupted)
    key = next(k for k, t in truth.items() if not t.needs_tests)
    corrupted = dict(truth)
    corrupted[key] = replace(corrupted[key], test_turnaround=999)
    with pytest.raises(PairingCheckError, match="test_turnaround"):
        _checked_pairing(a, a, truth, corrupted)
