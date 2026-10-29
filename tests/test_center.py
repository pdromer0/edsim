import copy
import dataclasses
import math
from pathlib import Path

import pytest

from edsim.engine.center import CenterConfig, load_center

EXAMPLE = Path(__file__).parent / "data" / "centro_ejemplo.toml"
CONFIG = Path(__file__).parents[1] / "config" / "centro.toml"

# Los valores de tests/data/centro_ejemplo.toml, por sección, para construir variantes.
DEFAULT = {
    "turnos": {"inicio": [8, 15, 22]},
    "recursos": {"enfermeria_triaje": [3, 3, 2], "medicos": [12, 12, 7], "boxes": 30},
    "triaje": {"reparto_niveles": [0.3, 12.1, 33.6, 52.6, 1.4]},
    "duraciones": {
        "triaje": [5, 10],
        "valoracion": [20, 45],
        "reevaluacion": [10, 20],
        "respuesta_pruebas": [60, 150],
    },
    "pruebas": {"probabilidad": [0.95, 0.85, 0.70, 0.40, 0.20]},
    "destino": {"probabilidad_ingreso": [0.80, 0.45, 0.15, 0.04, 0.01]},
}

LEVEL_KEYS = ["triaje.reparto_niveles", "pruebas.probabilidad", "destino.probabilidad_ingreso"]
SHIFT_KEYS = ["recursos.enfermeria_triaje", "recursos.medicos"]
DURATION_KEYS = [
    "duraciones.triaje",
    "duraciones.valoracion",
    "duraciones.reevaluacion",
    "duraciones.respuesta_pruebas",
]
NUMERIC_LIST_KEYS = LEVEL_KEYS + DURATION_KEYS


def _toml_value(value) -> str:
    """Write one value as TOML: tomllib can only read."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)  # nan e inf se escriben igual que en TOML
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"tipo no previsto en el test: {type(value)}")


def write_center(tmp_path: Path, changes: dict | None = None) -> Path:
    """Write the example center with some keys changed, added or removed (None).

    Keys of ``changes`` are ``"section.key"`` for one value or ``"section"`` for a
    whole section; a section that is not a dict is written as a plain value.
    """
    data = copy.deepcopy(DEFAULT)
    for dotted, value in (changes or {}).items():
        section, _, key = dotted.partition(".")
        if not key:
            data[section] = value
        elif value is None:
            del data[section][key]
        else:
            data.setdefault(section, {})[key] = value

    lines = []
    plain = {s: v for s, v in data.items() if v is not None and not isinstance(v, dict)}
    lines += [f"{s} = {_toml_value(v)}" for s, v in plain.items()]  # antes de las tablas
    for section, values in data.items():
        if isinstance(values, dict):
            lines.append(f"[{section}]")
            lines += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    path = tmp_path / "centro.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def with_value(dotted: str, index: int, value) -> dict:
    """Change for ``write_center``: the list under ``dotted`` with one value replaced."""
    section, key = dotted.split(".")
    values = list(DEFAULT[section][key])
    values[index] = value
    return {dotted: values}


def load(tmp_path: Path, changes: dict) -> CenterConfig:
    return load_center(write_center(tmp_path, changes))


@pytest.fixture(scope="module")
def center() -> CenterConfig:
    return load_center(EXAMPLE)


# --- Carga y normalización ---------------------------------------------------


def test_carga_del_toml_de_ejemplo(center):
    assert center.shift_starts == (8, 15, 22)
    assert center.triage_nurses == (3, 3, 2)
    assert center.doctors == (12, 12, 7)
    assert center.boxes == 30
    assert center.triage_time == (5.0, 10.0)
    assert center.assessment_time == (20.0, 45.0)
    assert center.reassessment_time == (10.0, 20.0)
    assert center.test_turnaround == (60.0, 150.0)
    assert center.test_probability == (0.95, 0.85, 0.70, 0.40, 0.20)
    assert center.admission_probability == (0.80, 0.45, 0.15, 0.04, 0.01)


def test_config_de_produccion_es_valida():
    # Los valores a mano usan el centro de ejemplo, que no se recalibra; este test solo
    # comprueba que el centro base, que sí cambiará en el hito 4, carga y es válido.
    c = load_center(CONFIG)

    assert isinstance(c, CenterConfig)
    assert sum(c.level_shares) == pytest.approx(1, rel=1e-12)


def test_toml_escrito_por_el_test_igual_que_el_de_ejemplo(tmp_path, center):
    # Comprueba el helper: sin cambios, el TOML escrito da el mismo centro.
    assert load_center(write_center(tmp_path)) == center


def test_tipos_normalizados(center):
    # Enteros en las capacidades y horas; floats en duraciones y probabilidades.
    assert all(type(x) is int for x in center.shift_starts + center.doctors + center.triage_nurses)
    assert type(center.boxes) is int
    assert all(type(x) is float for x in center.triage_time + center.level_shares)
    assert all(type(x) is float for x in center.test_probability)


def test_reparto_normalizado_a_suma_uno(center):
    # Los porcentajes suman 100,0: el nivel 1 queda en 0,3 / 100 = 0,003.
    assert sum(center.level_shares) == pytest.approx(1, rel=1e-12)
    assert center.level_shares[0] == pytest.approx(0.003, rel=1e-12)
    assert center.level_shares[3] == pytest.approx(0.526, rel=1e-12)


def test_reparto_no_necesita_sumar_100(tmp_path, center):
    # En tanto por uno o en porcentaje que no suma 100: se divide por la suma.
    for factor in (0.01, 2):
        shares = [factor * x for x in DEFAULT["triaje"]["reparto_niveles"]]
        c = load(tmp_path, {"triaje.reparto_niveles": shares})
        assert c.level_shares == pytest.approx(center.level_shares, rel=1e-12)


@pytest.mark.parametrize(
    "shares",
    [[0, 12.1, 33.6, 52.6, 1.4], [0, 0, 1, 0, 0], [0.3, 12.1, 33.6, 52.6, 0]],
)
def test_reparto_con_ceros_valido(tmp_path, shares):
    # Las condiciones extremas de la tarea 3.6 necesitan niveles con peso 0.
    c = load(tmp_path, {"triaje.reparto_niveles": shares})

    assert [x == 0 for x in c.level_shares] == [x == 0 for x in shares]
    assert sum(c.level_shares) == pytest.approx(1, rel=1e-12)


@pytest.mark.parametrize(
    "shares",
    [
        [0.3, 12.1, 33.6, 52.6, 1.4],
        # Normalizado suma 0.9999999999999999: dividir otra vez cambiaría el último bit.
        [0.3, 12.1, 33.6, 52.6, 0],
    ],
)
def test_normalizacion_idempotente(center, shares):
    # Construir con el reparto ya normalizado no lo vuelve a cambiar, ni en un bit.
    first = dataclasses.replace(center, level_shares=shares)
    again = dataclasses.replace(first)

    assert again.level_shares == first.level_shares


def test_inmutable(center):
    assert isinstance(center.level_shares, tuple)
    assert isinstance(center.doctors, tuple)
    assert isinstance(center.triage_time, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        center.boxes = 40


def test_construccion_directa_tambien_valida(center):
    # Sin pasar por load_center, el centro se valida igual.
    with pytest.raises(ValueError, match=r"recursos\.medicos must have 3 values, got 2"):
        dataclasses.replace(center, doctors=(12, 12))


def test_construccion_directa_acepta_listas(center):
    c = dataclasses.replace(center, doctors=[10, 10, 5])

    assert c.doctors == (10, 10, 5)


# --- Errores: claves -----------------------------------------------------------


def test_falta_una_clave(tmp_path):
    with pytest.raises(ValueError, match=r"missing keys: recursos\.boxes"):
        load(tmp_path, {"recursos.boxes": None})


def test_sobra_una_clave(tmp_path):
    # Una errata no puede pasar en silencio: falta la buena y sobra la mala.
    with pytest.raises(
        ValueError, match=r"missing keys: recursos\.boxes; unknown keys: recursos\.boxs"
    ):
        load(tmp_path, {"recursos.boxes": None, "recursos.boxs": 30})


def test_falta_una_seccion(tmp_path):
    with pytest.raises(ValueError, match=r"missing keys: destino\b"):
        load(tmp_path, {"destino": None})


def test_sobra_una_seccion(tmp_path):
    with pytest.raises(ValueError, match=r"unknown keys: personal\b"):
        load(tmp_path, {"personal": {"celadores": [2, 2, 1]}})


def test_seccion_que_no_es_tabla(tmp_path):
    with pytest.raises(ValueError, match="turnos must be a table"):
        load(tmp_path, {"turnos": [8, 15, 22]})


# --- Errores: longitudes -------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "n"),
    [("turnos.inicio", 2), ("turnos.inicio", 4)]
    + [(k, n) for k in SHIFT_KEYS for n in (2, 4)]
    + [(k, n) for k in LEVEL_KEYS for n in (4, 6)]
    + [(k, n) for k in DURATION_KEYS for n in (1, 3)],
)
def test_numero_de_valores_incorrecto(tmp_path, key, n):
    section, name = key.split(".")
    values = (list(DEFAULT[section][name]) * 3)[:n]
    if key == "turnos.inicio":
        values = list(range(1, n + 1))  # crecientes, para que solo falle la longitud

    with pytest.raises(ValueError, match=rf"{key} must have \d values, got {n}"):
        load(tmp_path, {key: values})


@pytest.mark.parametrize("key", ["turnos.inicio", *SHIFT_KEYS, *NUMERIC_LIST_KEYS])
def test_no_es_lista(tmp_path, key):
    with pytest.raises(ValueError, match=rf"{key} must be a list"):
        load(tmp_path, {key: 7})


# --- Errores: turnos -----------------------------------------------------------


@pytest.mark.parametrize("hours", [[8, 22, 15], [8, 8, 22], [22, 8, 15]])
def test_horas_no_crecientes(tmp_path, hours):
    with pytest.raises(ValueError, match=r"turnos\.inicio must be strictly increasing"):
        load(tmp_path, {"turnos.inicio": hours})


@pytest.mark.parametrize(("index", "hour"), [(0, -1), (2, 24)])
def test_horas_fuera_de_rango(tmp_path, index, hour):
    with pytest.raises(ValueError, match=rf"turnos\.inicio\[{index}\] must be between 0 and 23"):
        load(tmp_path, with_value("turnos.inicio", index, hour))


@pytest.mark.parametrize("hour", [8.5, 8.0, True, "8", math.nan])
def test_horas_no_enteras(tmp_path, hour):
    with pytest.raises(ValueError, match=r"turnos\.inicio\[0\] must be an integer"):
        load(tmp_path, with_value("turnos.inicio", 0, hour))


def test_horas_limite_validas(tmp_path):
    assert load(tmp_path, {"turnos.inicio": [0, 12, 23]}).shift_starts == (0, 12, 23)


# --- Errores: capacidades ------------------------------------------------------


@pytest.mark.parametrize("key", SHIFT_KEYS)
@pytest.mark.parametrize("value", [0, -1])
def test_plantilla_menor_que_uno(tmp_path, key, value):
    with pytest.raises(ValueError, match=rf"{key}\[1\] must be at least 1, got {value}"):
        load(tmp_path, with_value(key, 1, value))


@pytest.mark.parametrize("key", SHIFT_KEYS)
@pytest.mark.parametrize("value", [3.0, 2.5, True, "3", math.inf])
def test_plantilla_no_entera(tmp_path, key, value):
    # True es un int en Python, pero no una plantilla de 1.
    with pytest.raises(ValueError, match=rf"{key}\[2\] must be an integer"):
        load(tmp_path, with_value(key, 2, value))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (0, "must be at least 1"),
        (-30, "must be at least 1"),
        (30.0, "must be an integer"),
        (True, "must be an integer"),
        ("30", "must be an integer"),
    ],
)
def test_boxes_no_validos(tmp_path, value, message):
    with pytest.raises(ValueError, match=rf"recursos\.boxes {message}"):
        load(tmp_path, {"recursos.boxes": value})


# --- Errores: reparto, duraciones y probabilidades -----------------------------


@pytest.mark.parametrize("key", NUMERIC_LIST_KEYS)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "7", True])
def test_valores_no_finitos_o_no_numericos(tmp_path, key, value):
    with pytest.raises(ValueError, match=rf"{key}\[1\]"):
        load(tmp_path, with_value(key, 1, value))


def test_reparto_negativo(tmp_path):
    with pytest.raises(ValueError, match=r"triaje\.reparto_niveles\[2\] must not be negative"):
        load(tmp_path, with_value("triaje.reparto_niveles", 2, -1.0))


def test_reparto_todo_ceros(tmp_path):
    with pytest.raises(ValueError, match=r"triaje\.reparto_niveles must have a positive sum"):
        load(tmp_path, {"triaje.reparto_niveles": [0, 0, 0, 0, 0]})


@pytest.mark.parametrize("key", DURATION_KEYS)
@pytest.mark.parametrize("median", [0, -5])
def test_mediana_no_positiva(tmp_path, key, median):
    with pytest.raises(ValueError, match=rf"{key}\[0\] \(median\) must be positive"):
        load(tmp_path, with_value(key, 0, median))


@pytest.mark.parametrize("key", DURATION_KEYS)
@pytest.mark.parametrize("delta", [0, -1])
def test_p90_no_mayor_que_la_mediana(tmp_path, key, delta):
    section, name = key.split(".")
    median = DEFAULT[section][name][0]

    with pytest.raises(ValueError, match=rf"{key}: p90 must be greater than the median"):
        load(tmp_path, {key: [median, median + delta]})


@pytest.mark.parametrize("key", ["pruebas.probabilidad", "destino.probabilidad_ingreso"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_probabilidad_fuera_de_rango(tmp_path, key, value):
    with pytest.raises(ValueError, match=rf"{key}\[3\] must be between 0 and 1"):
        load(tmp_path, with_value(key, 3, value))


@pytest.mark.parametrize("key", ["pruebas.probabilidad", "destino.probabilidad_ingreso"])
def test_probabilidades_limite_validas(tmp_path, key):
    c = load(tmp_path, {key: [1, 1, 0.5, 0, 0]})
    field = "test_probability" if key.startswith("pruebas") else "admission_probability"

    assert getattr(c, field) == (1.0, 1.0, 0.5, 0.0, 0.0)
