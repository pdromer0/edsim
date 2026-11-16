"""Las semillas de dbt frente a `config/centro.toml` (tarea 8.5, decisión 106, H8-7).

`analitica/seeds/maestro_boxes.csv` y `turnos.csv` copian la capacidad y los turnos del centro
para que oro los lea en SQL. Pilla cambiar uno sin el otro: más boxes en `centro.toml` sin el
maestro, o un turno que empieza a otra hora. Se lee con `tomllib` y `csv`, sin el código del
paquete que carga el centro.
"""

import csv
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "analitica" / "seeds"


def centro() -> dict:
    with (ROOT / "config" / "centro.toml").open("rb") as source:
        return tomllib.load(source)


def rows(name: str) -> list[dict[str, str]]:
    with (SEEDS / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def test_el_maestro_de_boxes_tiene_los_boxes_del_centro_numerados_desde_1():
    boxes = centro()["recursos"]["boxes"]

    assert boxes == 36  # el número del que habla la especificación: si cambia, que se vea
    assert [int(row["box"]) for row in rows("maestro_boxes.csv")] == list(range(1, boxes + 1))


def test_los_turnos_empiezan_a_las_horas_del_centro():
    inicio = centro()["turnos"]["inicio"]

    turnos = rows("turnos.csv")

    assert [int(row["inicio"]) for row in turnos] == inicio
    assert [row["turno"] for row in turnos] == ["manana", "tarde", "noche"]
