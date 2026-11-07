"""Raw center values and the editor's field diagnostics."""

import copy
import dataclasses
import tomllib
from pathlib import Path

import pytest

import edsim.runs as runs
from edsim.runs import (
    center_from_values,
    load_center,
    read_center_values,
    validate_center_values,
)

BASE = Path(__file__).parents[1] / "config" / "centro.toml"


@pytest.fixture
def values():
    return read_center_values(BASE)


def test_raw_values_keep_percentages_lists_and_numeric_types(values):
    assert values["triaje.reparto_niveles"] == [0.3, 12.1, 33.6, 52.6, 1.4]
    assert type(values["duraciones.triaje"][0]) is int
    assert type(values["pruebas.probabilidad"][2]) is float
    assert len(values) == 12  # 11 + recursos.espera_resultados_fuera (tarea 4.6a)
    before = copy.deepcopy(values)
    assert validate_center_values(values) == {}
    assert center_from_values(values) == load_center(BASE)
    assert values == before


def test_all_errors_include_missing_unknown_and_invalid_values(values):
    del values["recursos.boxes"]
    values.update({"recursos.medicos": [0, 2, 3], "duraciones.triaje": [5, 4]})
    values["recursos.boxs"] = 30
    assert validate_center_values(values) == {
        "recursos.medicos": "recursos.medicos[0] must be at least 1, got 0",
        "recursos.boxes": "missing keys: recursos.boxes",
        "duraciones.triaje": "duraciones.triaje: p90 must be greater than the median, got [5, 4]",
        "recursos.boxs": "unknown keys: recursos.boxs",
    }
    with pytest.raises(ValueError) as caught:
        center_from_values(values)
    assert all(message in str(caught.value) for message in validate_center_values(values).values())


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        ("turnos.inicio", "shift_starts", [8, 8, 22]),
        ("recursos.enfermeria_triaje", "triage_nurses", [1, True, 2]),
        ("recursos.medicos", "doctors", [3, 0, 2]),
        ("recursos.boxes", "boxes", 3.0),
        ("triaje.reparto_niveles", "level_shares", [0] * 5),
        ("duraciones.triaje", "triage_time", [0, 5]),
        ("duraciones.valoracion", "assessment_time", [5, 5]),
        ("duraciones.reevaluacion", "reassessment_time", [5, float("nan")]),
        ("duraciones.respuesta_pruebas", "test_turnaround", [1]),
        ("pruebas.probabilidad", "test_probability", [0, 0, 2, 0, 0]),
        ("destino.probabilidad_ingreso", "admission_probability", [False] * 5),
    ],
)
def test_each_field_uses_the_constructor_message(values, key, field, value):
    center = center_from_values(values)
    values[key] = value
    with pytest.raises(ValueError) as caught:
        dataclasses.replace(center, **{field: value})
    assert validate_center_values(values) == {key: str(caught.value)}
    with pytest.raises(ValueError) as built:
        center_from_values(values)
    assert str(built.value) == str(caught.value)


def test_reader_retains_malformed_and_unknown_sections(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(
        "turnos = [8, 15, 22]\n[personal]\nceladores = 2\n[recursos]\n", encoding="utf-8"
    )
    values = read_center_values(path)
    assert values == {"turnos": [8, 15, 22], "personal": {"celadores": 2}}
    errors = validate_center_values(values)
    # Sin ninguna tabla del bloque provisional, sus seis claves no se exigen (tarea 4.9):
    # turnos mal formada, recursos.{enfermeria_triaje, medicos, boxes} y destino ausentes
    # y personal desconocida.
    assert len(errors) == 6
    assert (
        not {"triaje.reparto_niveles", "duraciones.triaje", "pruebas.probabilidad"} & errors.keys()
    )
    assert errors["turnos.inicio"] == "turnos must be a table, got [8, 15, 22]"
    assert errors["recursos.boxes"] == "missing keys: recursos.boxes"
    assert errors["personal"] == "unknown keys: personal"


def test_loader_keeps_grouped_structure_messages(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[recursos]\nboxs = 30\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == (
        f"{path}: missing keys: destino, recursos.boxes, "
        "recursos.enfermeria_triaje, recursos.medicos, turnos; "
        "unknown keys: recursos.boxs"
    )


def test_loader_keeps_first_value_error(values, tmp_path):
    path = tmp_path / "bad.toml"
    # La plantilla se lee del fichero: la calibración (tarea 4.6b) la cambia.
    doctors = ", ".join(str(n) for n in values["recursos.medicos"])
    line = f"medicos = [{doctors}]".encode()
    assert line in BASE.read_bytes()
    path.write_bytes(BASE.read_bytes().replace(line, b"medicos = [0, 0, 0]"))
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == "recursos.medicos[0] must be at least 1, got 0"


def test_reader_propagates_read_and_syntax_errors(tmp_path):
    path = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError):
        read_center_values(path)
    path.write_text("[invalid", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        read_center_values(path)


def test_simular_configuration_types_and_loaders_are_public():
    for name in (
        "ArrivalProfile",
        "CenterConfig",
        "load_center",
        "load_profile",
        "read_center_values",
        "validate_center_values",
        "center_from_values",
    ):
        assert name in runs.__all__
        assert getattr(runs, name) is not None


@pytest.mark.parametrize("key", ["recursos.medicos", "destino.probabilidad_ingreso"])
def test_literal_dotted_root_key_cannot_shadow_a_table_field(tmp_path, key):
    path = tmp_path / "literal.toml"
    path.write_bytes(f'"{key}" = [99, 99, 99]\n'.encode() + BASE.read_bytes())
    values = read_center_values(path)
    assert values[key] == read_center_values(BASE)[key]
    assert values[f'"{key}"'] == [99, 99, 99]
    assert validate_center_values(values) == {f'"{key}"': f'unknown keys: "{key}"'}
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == f"{path}: unknown keys: {key}"


def test_literal_root_key_does_not_supply_a_missing_table(tmp_path):
    path = tmp_path / "literal.toml"
    content = BASE.read_bytes().split(b"[destino]")[0]
    path.write_bytes(b'"destino.probabilidad_ingreso" = [0, 0, 0, 0, 0]\n' + content)
    errors = validate_center_values(read_center_values(path))
    assert set(errors) == {"destino.probabilidad_ingreso", '"destino.probabilidad_ingreso"'}
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == (
        f"{path}: missing keys: destino; unknown keys: destino.probabilidad_ingreso"
    )


# --- Clave opcional espera_resultados_fuera (tarea 4.6a) ------------------------------

EJEMPLO = Path(__file__).parent / "data" / "centro_ejemplo.toml"


def test_sin_la_clave_opcional_no_hay_errores_y_vale_vacia():
    values = read_center_values(EJEMPLO)
    assert "recursos.espera_resultados_fuera" not in values
    assert validate_center_values(values) == {}
    assert center_from_values(values).results_wait_outside == ()


def test_la_clave_opcional_invalida_da_su_error_por_clave(values):
    values["recursos.espera_resultados_fuera"] = [1, 5]
    assert validate_center_values(values) == {
        "recursos.espera_resultados_fuera": (
            "recursos.espera_resultados_fuera[0] cannot be 1: level 1 is classified at the "
            "door and never waits outside the box"
        )
    }
