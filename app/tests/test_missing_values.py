"""Keep absent configuration values and episode waits explicit in the UI."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import CenterDifference, RunStore, RunSummaryComparison, read_run_results
from edsim_app import results
from edsim_app.comparison_frames import comparison_configuration_frames
from edsim_app.frames import format_change_value


def test_missing_change_value_is_a_dash():
    assert format_change_value(None) == "—"
    assert format_change_value((1, 0.5)) == "[1; 0,5]"


@pytest.mark.parametrize("missing_side", ["A", "B"])
def test_center_changes_show_a_dash_on_the_missing_side(missing_side):
    keys = (
        "triaje.reparto_niveles",
        "duraciones.triaje",
        "duraciones.valoracion",
        "duraciones.reevaluacion",
        "duraciones.respuesta_pruebas",
        "pruebas.probabilidad",
    )
    changes = tuple(
        CenterDifference(key, None, (5, 10))
        if missing_side == "A"
        else CenterDifference(key, (5, 10), None)
        for key in keys
    )
    summary = RunSummaryComparison((), changes, (), (), 0, 0, 0, 0)
    _, frame = comparison_configuration_frames(summary)
    assert frame["Clave del centro"].tolist() == list(keys)
    assert frame[missing_side].tolist() == ["—"] * len(keys)
    assert frame["B" if missing_side == "A" else "A"].tolist() == ["[5; 10]"] * len(keys)


@pytest.mark.slow
@pytest.mark.parametrize(
    "waits,expected", [((None, None), ("—", "—")), ((0.0, 2.5), ("0,0 min", "2,5 min"))]
)
def test_episode_card_waits_only_include_units_when_present(catalog, monkeypatch, waits, expected):
    result = read_run_results(RunStore(catalog), "older")
    record = replace(result.analysis.table[0], initial_box_wait=waits[0], results_box_wait=waits[1])
    result = replace(
        result, analysis=replace(result.analysis, table=(record, *result.analysis.table[1:]))
    )
    monkeypatch.setattr(results, "cached_run_results", Mock(return_value=result))
    app = AppTest.from_file(Path(edsim_app.__file__).with_name("main.py"))
    app.query_params.update(run="older", episodio=record.episode_id)
    app.run().switch_page("views/episodes.py").run()
    assert not app.exception and not app.error
    assert any(item.value == f"Ficha del episodio {record.episode_id}" for item in app.subheader)
    metrics = {item.label: item.value for item in app.metric}
    assert (metrics["Espera inicial de box"], metrics["Espera de box al volver"]) == expected
