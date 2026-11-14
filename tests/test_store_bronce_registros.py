"""Los registros desde bronce: `records_from_lines` y `read_bronze_records` (tarea 7.3).

Cada test dice qué error pilla. El SQL de la última publicación (`READ_LINES`) no se ejecuta aquí:
lo prueba la integración, contra el Postgres de `compose.yaml` (`test_comparar.py`); aquí, la parte
que no necesita base de datos: de las líneas de bronce a los `Record`, y que la lectura pide la
ejecución derivada a `read_bronze_lines`.
"""

import pytest
from registro_factory import big_recording, run_l
from runaway import check_calls

from edsim.clinical_record import record_json
from edsim.store import postgres
from edsim.store.postgres import BronzeReadError, read_bronze_records, records_from_lines


def lines_of(recording) -> list[str]:
    return [record_json(r) for r in recording.records]


@pytest.mark.parametrize("make", [run_l, big_recording], ids=["escenario_L", "perfil_ruidoso"])
def test_las_lineas_de_bronce_vuelven_a_ser_los_registros_en_orden(make):
    """Cada `valor` de bronce (la línea de `registrado.jsonl`) es el mismo `Record`, y en el mismo
    orden. Pilla un orden que se pierde, o un campo (un `null`, un anidado) que no vuelve igual
    que con la lectura de ficheros: la comparación con Postgres sería otra."""
    recording = make()

    assert records_from_lines(lines_of(recording)) == list(recording.records)


def test_sin_lineas_no_hay_registros():
    """Una ejecución que bronce no tiene: lista vacía, y es la conciliación quien dice que falta."""
    assert records_from_lines([]) == []


@pytest.mark.parametrize(
    "bad", ["{roto", "[]", '{"event_id": "x"}', "null"], ids=["json", "lista", "claves", "null"]
)
def test_una_linea_que_no_es_un_registro_es_un_error_de_bronce_que_dice_cual(bad):
    """El tercer valor está mal: `BronzeReadError` con su posición; nunca un `JSONDecodeError`
    ni un `ValueError` sueltos, que la CLI contaría como error de uso."""
    lines = lines_of(run_l())
    lines[2] = bad

    with pytest.raises(BronzeReadError, match="valor 3 de bronce"):
        records_from_lines(lines)


def test_read_bronze_records_lee_la_ejecucion_derivada_y_construye_los_registros(monkeypatch):
    """`read_bronze_records` pide a `read_bronze_lines` la URL y el `run_id` que le dan (el
    derivado, no el de la verdad) y devuelve sus registros. El doble de lectura lleva tope."""
    recording = run_l()
    calls = []

    def fake_lines(url, run_id):
        calls.append((url, run_id))
        check_calls(len(calls), 3, "read_bronze_lines")
        return lines_of(recording)

    monkeypatch.setattr(postgres, "read_bronze_lines", fake_lines)

    records = read_bronze_records("postgresql://u:p@h/db", "r2026_prueba_s7")

    assert calls == [("postgresql://u:p@h/db", "r2026_prueba_s7")]
    assert records == list(recording.records)
