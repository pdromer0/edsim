"""Leer lo escrito: `record_from_json` y `read_notebook_csv` (tarea 7.3).

Cada test dice qué error pilla. Los dos lectores son el inverso de `record_json` y de
`notebook_csv`: la ida y vuelta, con el escenario L y con un registro grande de un perfil
escandaloso (todos los despistes ocurren), y un error por cada cosa que un fichero o una fila de
bronce puede traer mal. De ellos dependen la CLI y la lectura de bronce: un lector que acepta de
más escondería un bronce corrupto detrás de una cuenta que no cuadra.
"""

import json

import pytest
from registro_factory import RUN, loud_profile, patient_log, run_l

from edsim.clinical_record import (
    NOTEBOOK_COLUMNS,
    NotebookRow,
    notebook_csv,
    read_notebook_csv,
    record,
    record_from_json,
    record_json,
)


def big_recording():
    """Un registro de 60 pacientes con el perfil escandaloso y un horizonte que deja correcciones
    pendientes: hay registros con campos vacíos, valores erróneos, duplicados y correcciones."""
    return record(patient_log(60), loud_profile(), 5, horizon=400.0, run_id=RUN)


# --- record_from_json ------------------------------------------------------------------------


@pytest.mark.parametrize("make", [run_l, big_recording], ids=["escenario_L", "perfil_ruidoso"])
def test_ida_y_vuelta_de_los_registros(make):
    """Cada línea escrita vuelve a ser el mismo `Record`, y vuelve a escribirse con los mismos
    bytes. Pilla un lector que pierde un `null`, convierte un entero en texto o cambia el orden."""
    recording = make()

    assert len(recording.records) > 0
    for original in recording.records:
        line = record_json(original)
        parsed = record_from_json(line)
        assert parsed == original
        assert record_json(parsed) == line


def test_el_registro_grande_tiene_de_todo():
    """Sin esto, la ida y vuelta del perfil ruidoso podría pasar sin probar un `null`, una
    corrección o un duplicado (un test que pasa de forma vacía)."""
    records = big_recording().records

    assert any(r.event_type == "record_corrected" for r in records)
    assert any(None in r.payload.values() for r in records)
    assert len({r.event_id for r in records}) == len(records)


def test_un_sim_time_entero_vuelve_como_float():
    """Pilla un `sim_time` que se queda entero: el resto del paquete lo trata como float."""
    line = json.loads(record_json(run_l().records[0]))
    line["sim_time"] = 1020
    parsed = record_from_json(json.dumps(line))

    assert parsed.sim_time == 1020.0
    assert isinstance(parsed.sim_time, float)


def edited(**changes):
    """Una línea del L con los cambios dados; la clave que vale `...` se quita."""
    data = json.loads(record_json(run_l().records[0]))
    for key, value in changes.items():
        if value is ...:
            del data[key]
        else:
            data[key] = value
    return json.dumps(data)


@pytest.mark.parametrize(
    "line",
    [
        "[]",
        '"texto"',
        "null",
        edited(event_id=...),
        edited(payload=...),
        edited(extra=1),
        edited(event_id=7),
        edited(event_type=None),
        edited(event_time=3),
        edited(episode_id=3),
        edited(patient_id=[]),
        edited(ingest_time=5),
        edited(schema_version=True),
        edited(schema_version="4"),
        edited(schema_version=4.0),
        edited(sim_time=True),
        edited(sim_time="1020"),
        edited(sim_time=None),
        edited(payload=[1]),
        edited(payload="x"),
    ],
)
def test_una_linea_que_no_es_un_registro_es_un_error(line):
    """Pilla un lector que acepta de más: lo que no es un registro no puede llegar a la cuenta."""
    with pytest.raises(ValueError):
        record_from_json(line)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "1" + "0" * 400])
def test_un_sim_time_que_no_es_finito_es_un_error(number):
    """NaN, los infinitos y un entero de 400 cifras (que no cabe en un float) no son tiempos."""
    line = edited(sim_time=0).replace('"sim_time": 0', f'"sim_time": {number}')

    with pytest.raises(ValueError, match="sim_time"):
        record_from_json(line)


def test_un_json_roto_es_un_value_error():
    """Pilla un `JSONDecodeError` que no sea un `ValueError`: la CLI solo atrapa `ValueError`."""
    with pytest.raises(ValueError):
        record_from_json("{no es json")


# --- read_notebook_csv -----------------------------------------------------------------------


@pytest.mark.parametrize("make", [run_l, big_recording], ids=["escenario_L", "perfil_ruidoso"])
def test_ida_y_vuelta_de_la_libreta(make):
    """Las filas vuelven iguales (con `nivel` y `edad` como enteros y `motivo` y `destino` como
    texto) y el CSV vuelve a escribirse con los mismos bytes."""
    recording = make()
    text = notebook_csv(recording.notebook)

    rows = read_notebook_csv(text)

    assert rows == tuple(recording.notebook)
    assert notebook_csv(rows) == text


def test_la_libreta_grande_tiene_de_todo():
    """Valores erróneos de los cuatro campos, vacíos, correcciones y sin escribir: sin esto, la
    ida y vuelta no probaría los tipos de `valor_verdadero` ni las filas sin `registro`."""
    notebook = big_recording().notebook

    assert {r.wrong_field for r in notebook} >= {"nivel", "edad", "motivo", "destino"}
    assert {r.kind for r in notebook} >= {"con_despistes", "duplicado", "correccion"}
    assert {r.kind for r in notebook} & {"perdido", "correccion_pendiente"}
    assert any(r.empty_field for r in notebook)


def test_los_valores_de_nivel_y_edad_son_enteros_y_los_demas_texto():
    """Pilla un lector que devuelve todo como texto (un `3` frente a `"3"` rompe la igualdad)."""
    rows = read_notebook_csv(notebook_csv(big_recording().notebook))
    by_field = {}
    for row in rows:
        if row.wrong_field is not None and row.kind == "con_despistes":
            by_field[row.wrong_field] = (type(row.true_value), type(row.recorded_value))

    assert by_field["nivel"] == (int, int)
    assert by_field["edad"] == (int, int)
    assert by_field["motivo"] == (str, str)
    assert by_field["destino"] == (str, str)


def test_una_libreta_solo_con_la_cabecera_no_tiene_filas():
    """El caso vacío: una ejecución sin hechos tiene libreta de cero filas, no un error."""
    assert read_notebook_csv(notebook_csv([])) == ()


HEADER = ",".join(NOTEBOOK_COLUMNS)
GOOD_ROW = "r-1,t-1,bien,0.0,0.0,,,,,,"


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("", 1),
        ("registro,hecho\n", 1),
        (f"{HEADER[::-1]}\n", 1),
        (f"{HEADER}\nr-1,t-1,bien\n", 2),
        (f"{HEADER}\n{GOOD_ROW}\nr-2,t-2,bien,0.0,0.0,,,,,,,extra\n", 3),
        (f"{HEADER}\nr-1,t-1,mala,0.0,0.0,,,,,,\n", 2),
        (f"{HEADER}\nr-1,t-1,bien,siete,0.0,,,,,,\n", 2),
        (f"{HEADER}\nr-1,t-1,bien,nan,0.0,,,,,,\n", 2),
        (f"{HEADER}\nr-1,t-1,bien,0.0,inf,,,,,,\n", 2),
        (f"{HEADER}\nr-1,t-1,bien,1e999,0.0,,,,,,\n", 2),
        (f"{HEADER}\nr-1,,bien,0.0,0.0,,,,,,\n", 2),
        (f"{HEADER}\nr-1,t-1,con_despistes,0.0,0.0,,,3,4,,\n", 2),
        (f"{HEADER}\nr-1,t-1,con_despistes,0.0,0.0,,nivel,tres,4,,\n", 2),
        (f"{HEADER}\nr-1,t-1,con_despistes,0.0,0.0,,edad,50,5.5,,\n", 2),
    ],
)
def test_una_libreta_mal_formada_es_un_error_con_su_linea(text, line):
    """Pilla un lector que acepta una cabecera o una fila mala, o que no dice dónde está."""
    with pytest.raises(ValueError, match=f"defectos.csv:{line}"):
        read_notebook_csv(text)


def test_una_fila_sin_registro_deja_el_registro_vacio():
    """Los hechos perdidos no tienen `registro`: la celda vacía es `None`, no una cadena vacía."""
    (row,) = read_notebook_csv(f"{HEADER}\n,t-1,perdido,,,,,,,,\n")

    assert row == NotebookRow(None, "t-1", "perdido")
