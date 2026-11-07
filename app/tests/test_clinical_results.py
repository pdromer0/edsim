"""Compare observable page values with the public three-clock services."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    level_one_clocks,
    read_run_results,
    window_clocks,
    window_compliance,
    window_pretriage,
)
from edsim_app.frames import CLOCK_LABELS

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_results(run_id):
    app = AppTest.from_file(MAIN)
    app.query_params["run"] = run_id
    app.run().switch_page("views/results.py").run()
    assert app.title[0].value == "Resultados" and not app.exception and not app.error
    return app


def table(app, column):
    return next(item.value for item in app.dataframe if column in item.value)


def test_three_clocks_match_core(clinical_catalog):
    result = read_run_results(RunStore(clinical_catalog), "clinical")
    app = open_results("clinical")
    frame = table(app, "Nivel asignado")
    frame = next(item.value for item in app.dataframe if "Media (min)" in item.value)
    expected = window_clocks(result.analysis.table, 1, 3)
    assert frame["Reloj"].unique().tolist() == list(CLOCK_LABELS.values())
    for level in expected[1:]:
        for clock in level.clocks:
            row = frame[
                (frame["Nivel asignado"] == level.level)
                & (frame["Reloj"] == CLOCK_LABELS[clock.measure])
            ].iloc[0]
            for column, value in (
                ("Media (min)", clock.mean),
                ("Mediana (min)", clock.median),
                ("p90 (min)", clock.p90),
            ):
                assert (
                    row[column] == pytest.approx(value)
                    if value is not None
                    else pd.isna(row[column])
                )


def test_manchester_uses_classification_clock(clinical_catalog):
    result = read_run_results(RunStore(clinical_catalog), "clinical")
    c = window_compliance(result.analysis.table, 1, 3, measure="classified_to_doctor")
    a = window_compliance(result.analysis.table, 1, 3, measure="door_to_doctor")
    assert any(
        x.exceeded != y.exceeded for x, y in zip(c.by_level[1:], a.by_level[1:], strict=True)
    )
    app = open_results("clinical")
    frame = table(app, "Pacientes que superan el máximo")
    assert frame["Nivel"].tolist() == [2, 3, 4, 5]
    assert frame["Pacientes que superan el máximo"].tolist() == [v.exceeded for v in c.by_level[1:]]
    pd.testing.assert_series_equal(
        frame["Superan el máximo"],
        pd.Series([v.exceeded_share for v in c.by_level[1:]], name="Superan el máximo"),
    )
    assert any("desde la clasificación (C)" in item.value for item in app.subheader)


def test_pretriage_and_level_one_without_percentage(clinical_catalog):
    result = read_run_results(RunStore(clinical_catalog), "clinical")
    app = open_results("clinical")
    pre = window_pretriage(result.analysis.table, 1, 3)
    frame = table(app, "10 min o menos")
    assert frame["n"].tolist() == [g.n for g in pre.by_group]
    pd.testing.assert_series_equal(
        frame["10 min o menos"],
        pd.Series([g.within_share for g in pre.by_group], name="10 min o menos"),
    )
    pd.testing.assert_series_equal(
        frame["Más de 5 min"], pd.Series([g.over_share for g in pre.by_group], name="Más de 5 min")
    )
    one = level_one_clocks(result.analysis.table, 1, 3)
    assert one.n > 0
    frame = next(
        item.value
        for item in app.dataframe
        if list(item.value) == ["Reloj", "n", "Mediana (min)", "p90 (min)"]
    )
    assert frame["Mediana (min)"].tolist() == list(one.median.values())
    assert frame["p90 (min)"].tolist() == list(one.p90.values())


@pytest.mark.parametrize("run_id", ["clinical", "provisional", "legacy", "absurd"])
def test_catalog_and_results_open_both_models_and_legacy(clinical_catalog, run_id):
    app = open_results(run_id)
    assert app.header[0].value == run_id and app.metric
    app.switch_page("views/runs.py").run()
    frame = app.dataframe[0].value.set_index("Ejecución")
    assert frame.loc[run_id, "Modelo"] == (
        "Clínico" if run_id in ("clinical", "absurd") else "Provisional"
    )
    if run_id in ("clinical", "absurd"):
        assert frame.loc[run_id, "Huella de perfiles clínicos"] != "—"


def test_distribution_uses_window_arrivals_and_never_true_levels(clinical_catalog):
    result = read_run_results(RunStore(clinical_catalog), "clinical")
    records = [e for e in result.analysis.table if 1440 <= e.arrival < 4320]
    assert any(e.departure is None for e in records)
    app = open_results("clinical")
    frame = table(app, "Motivo")
    expected = (
        pd.Series(
            [
                result.profiles.reason(result.observed[e.episode_id].reason).name
                if result.observed[e.episode_id].reason
                else "Sin observar"
                for e in records
            ]
        )
        .value_counts()
        .to_dict()
    )
    assert frame.set_index("Motivo")["Pacientes"].to_dict() == expected
    assert frame["Pacientes"].sum() == len(records)
    assert not any("real" in column.lower() for item in app.dataframe for column in item.value)


def test_absurd_center_clinical_fields_do_not_change_observable_results(clinical_catalog):
    app = open_results("clinical")
    expected = [item.value.copy() for item in app.dataframe]
    absurd = open_results("absurd")
    for actual, reference in zip(absurd.dataframe, expected, strict=True):
        pd.testing.assert_frame_equal(actual.value, reference)
