"""De la ejecución guardada a las filas de `verdad`, sin conectar (tarea 8.4, H8-6).

Cada test dice qué error pilla. Los valores esperados salen de leer los ficheros a mano, con `csv`
y `json` de la biblioteca estándar, sin pasar por `edsim.store.truth`: así una columna mal mapeada o
en otro orden no se esconde detrás del mismo código. La ejecución es del hito 5 (esquema 4) de dos
días, la de `test_record_run.py`.
"""

import csv
import inspect
import json
import re
from pathlib import Path

import pytest
from registro_factory import PROFILES_FILE
from runs_factory import copy_run

from edsim.runs import RunStore, record_run, simulate_run
from edsim.store.truth import EVENT_COLUMNS, TruthError, truth_run

DATA = Path(__file__).parent / "data"
FUENTES = Path(__file__).resolve().parent.parent / "analitica" / "models" / "fuentes.yml"
RUN = "hito5"
LIMPIO_SEED = 3
"""La semilla del perfil `limpio`; el `realista` usa la de la ejecución (7)."""


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """La ejecución del hito 5 (catálogo v4) de 2 días, sin registros, de solo lectura."""
    root = tmp_path_factory.mktemp("verdad-base")
    simulate_run(
        DATA / "centro_h5_ejemplo.toml",
        DATA / "llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / RUN,
        run_id=RUN,
        warmup_days=1,
        origin="cli",
        profiles=DATA / "perfiles_h5_ejemplo.toml",
    )
    return RunStore(root)


@pytest.fixture(scope="module")
def recorded(base, tmp_path_factory):
    """Una copia de la ejecución con dos registros: `realista` (semilla 7) y `limpio` (3)."""
    store, path = copy_run(base, RUN, tmp_path_factory.mktemp("verdad-registrada"))
    record_run(store, RUN, "realista", profiles_file=PROFILES_FILE)
    record_run(store, RUN, "limpio", LIMPIO_SEED, profiles_file=PROFILES_FILE)
    return store, path


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    """La cabecera y las filas de un CSV, tal como están en el fichero."""
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.reader(source))
    return rows[0], rows[1:]


def nullable(row: list[str]) -> tuple:
    return tuple(None if cell == "" else cell for cell in row)


def table(run, name):
    return next(t for t in run.tables if t.name == name)


def test_las_cuatro_tablas_van_en_el_orden_de_la_carga(base):
    """Pilla un orden que cargue la libreta antes que los eventos: el de la especificación."""
    run = truth_run(base, RUN)

    assert [t.qualified_name for t in run.tables] == [
        "verdad.eventos",
        "verdad.episodios",
        "verdad.dias",
        "verdad.libreta",
    ]
    assert [len(t.columns) for t in run.tables] == [11, 65, 15, 15]


def test_las_filas_de_eventos_son_las_de_eventos_jsonl(base):
    """Pilla una columna de eventos mal mapeada o en otro orden, o un payload que no es el del
    fichero. Las filas, de la primera a la última, salen de leer cada línea con `json`."""
    lines = [
        line for line in (base.root / RUN / "eventos.jsonl").read_text("utf-8").split("\n") if line
    ]
    envelope = [c for c in table(truth_run(base, RUN), "eventos").columns if c != "payload"]

    rows = list(table(truth_run(base, RUN), "eventos").rows())

    assert len(rows) == len(lines) > 100
    for line, row in zip(lines, rows, strict=True):
        data = json.loads(line)
        assert row[: len(envelope)] == tuple(data[c] for c in envelope)
        assert json.loads(row[-1]) == data["payload"]
    assert rows[0][0] == f"{RUN}-000000000"
    assert rows[-1][0] == json.loads(lines[-1])["event_id"]


def test_las_filas_de_episodios_son_las_del_csv(base):
    """Pilla una columna de la ficha mal mapeada o en otro orden (las 65), un vacío que no pasa
    a `None` o una fila que falte: todas las filas, con su primera y su última."""
    header, expected = read_csv(base.root / RUN / "ground_truth_episodios.csv")
    episodes = table(truth_run(base, RUN), "episodios")

    rows = list(episodes.rows())

    assert episodes.columns == tuple(header)
    assert len(header) == 65
    assert rows == [nullable(row) for row in expected]
    assert len(rows) > 100
    assert rows[0][0] == "EP-000000"
    # `respuesta_pruebas` está siempre vacía con el modelo clínico: es el único NULL.
    index = header.index("respuesta_pruebas")
    assert {i for row in rows for i, cell in enumerate(row) if cell is None} == {index}


def test_las_filas_de_dias_son_las_del_csv(base):
    """Pilla que `dias` pierda las columnas de parámetros o se salte un día."""
    header, expected = read_csv(base.root / RUN / "ground_truth_dias.csv")
    days = table(truth_run(base, RUN), "dias")

    rows = list(days.rows())

    assert days.columns == tuple(header)
    assert rows == [nullable(row) for row in expected]
    assert [row[0] for row in rows] == ["0", "1"]


def test_la_libreta_lleva_un_registro_por_carpeta_con_su_run_id_derivado(recorded):
    """Pilla una libreta que mezcle los perfiles, que no ponga el `run_id` derivado, el perfil y
    la semilla delante, o que pierda las celdas vacías (`NULL`)."""
    store, path = recorded
    run = truth_run(store, RUN)
    ledger = table(run, "libreta")
    expected = []
    for name, profile, seed in (("limpio-s3", "limpio", 3), ("realista-s7", "realista", 7)):
        _, notebook = read_csv(path / "registros" / name / "defectos.csv")
        prefix = (RUN, f"{RUN}_{profile}_s{seed}", profile, seed)
        expected += [(*prefix, *nullable(row)) for row in notebook]

    rows = list(ledger.rows())

    assert run.recordings == ("limpio-s3", "realista-s7")
    assert ledger.columns[:4] == ("run_id_origen", "run_id", "perfil", "semilla")
    assert rows == expected
    assert {row[2] for row in rows} == {"limpio", "realista"}
    # Un hecho perdido no tiene `registro`: una celda vacía, `None` y no un texto vacío.
    lost = [row for row in rows if row[6] == "perdido"]
    assert lost and all(row[4] is None for row in lost)


def test_sin_registros_la_libreta_queda_vacia(base):
    """Pilla un error donde la especificación dice que no lo hay: una ejecución sin `registros/`
    se carga, con la libreta vacía."""
    run = truth_run(base, RUN)

    assert run.recordings == ()
    assert list(table(run, "libreta").rows()) == []


def test_las_filas_llegan_de_una_en_una(base):
    """Pilla una función que arme la lista entera: un año son 1,4 millones de eventos y otras
    tantas filas de libreta, que en una lista de Python pesarían demasiado en un WSL de 7 GB."""
    for t in truth_run(base, RUN).tables:
        rows = t.rows()
        assert inspect.isgenerator(rows), t.name
        assert next(rows, None) is not None or t.name == "libreta"


def test_las_columnas_de_eventos_son_las_que_declara_dbt():
    """El contrato con la 8.1: `source('verdad', 'eventos')` declara estas once columnas. Pilla
    una columna de más (las de Kafka, `valor`, `ingest_time`) o de menos."""
    declared = []
    in_verdad = in_eventos = False
    for line in FUENTES.read_text("utf-8").split("\n"):
        if re.fullmatch(r"  - name: \w+", line):
            in_verdad = line.strip() == "- name: verdad"
        elif in_verdad and re.fullmatch(r"      - name: \w+", line):
            in_eventos = line.strip() == "- name: eventos"
        elif in_verdad and in_eventos and (m := re.fullmatch(r"          - name: (\w+)", line)):
            declared.append(m[1])

    assert len(declared) == 11
    assert EVENT_COLUMNS == tuple(declared)


# --- D1: solo el modelo actual ------------------------------------------------------------


@pytest.mark.parametrize(
    ("run_id", "schema"), [("clinica", 3), ("provisional", 1)], ids=["hito-4", "provisional"]
)
def test_una_ejecucion_de_otro_esquema_es_un_error_claro(clinical_store, run_id, schema):
    """Pilla una carga que acepte una ficha de 57 o 18 columnas: el error dice el esquema de la
    ejecución y cómo regenerarla, antes de leer una sola fila."""
    with pytest.raises(TruthError, match=rf"esquema {schema}.*edsim motor simular"):
        truth_run(clinical_store, run_id)


# --- Ficheros que no son lo que escribió el motor -----------------------------------------


@pytest.fixture
def copy(base, tmp_path):
    """Una copia que el test puede estropear: su `RunStore` y su carpeta."""
    return copy_run(base, RUN, tmp_path)


@pytest.mark.parametrize("filename", ["ground_truth_episodios.csv", "ground_truth_dias.csv"])
def test_una_cabecera_distinta_se_rechaza_antes_de_cargar(copy, filename):
    """Pilla una carga que lea un CSV con otra cabecera, con las columnas corridas: el error sale
    de `truth_run`, antes de las filas, y dice el fichero."""
    store, path = copy
    text = (path / filename).read_text("utf-8")
    (path / filename).write_text(
        text.replace("episodio", "episodios", 1).replace("dia,", "día,", 1)
    )

    with pytest.raises(TruthError, match=rf"{filename}:1: la cabecera"):
        truth_run(store, RUN)


def test_una_fila_con_menos_celdas_dice_su_linea(copy):
    """Pilla una fila corta que se cargue con las celdas corridas: el error da el fichero y la
    línea física (la cabecera es la 1)."""
    store, path = copy
    lines = (path / "ground_truth_episodios.csv").read_text("utf-8").split("\n")
    lines[3] = lines[3].rsplit(",", 1)[0]
    (path / "ground_truth_episodios.csv").write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(TruthError, match=r"ground_truth_episodios.csv:4: 64 celdas y la cabecera"):
        list(table(truth_run(store, RUN), "episodios").rows())


def test_una_fila_de_otra_ejecucion_se_rechaza(copy):
    """Pilla un CSV de otra ejecución copiado a esta carpeta: cada fila lleva su `run_id`."""
    store, path = copy
    text = (path / "ground_truth_dias.csv").read_text("utf-8")
    (path / "ground_truth_dias.csv").write_text(text.replace(f",{RUN}\n", ",otra\n", 1))

    with pytest.raises(TruthError, match=r"ground_truth_dias.csv:2: run_id es 'otra'"):
        list(table(truth_run(store, RUN), "dias").rows())


def test_una_linea_rota_de_eventos_dice_su_numero(copy):
    """Pilla un `eventos.jsonl` con una línea que no es un evento y que se cuele en la carga."""
    store, path = copy
    lines = (path / "eventos.jsonl").read_text("utf-8").split("\n")
    lines[2] = '{"no": "es un evento"}'
    (path / "eventos.jsonl").write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(TruthError, match=r"eventos.jsonl:3: "):
        list(table(truth_run(store, RUN), "eventos").rows())


def test_un_evento_de_otra_ejecucion_se_rechaza(copy):
    """Pilla un log que pertenece a otra ejecución: sus `event_id` chocarían con los de esta."""
    store, path = copy
    text = (path / "eventos.jsonl").read_text("utf-8")
    (path / "eventos.jsonl").write_text(text.replace(f'"run_id": "{RUN}"', '"run_id": "otra"', 1))

    with pytest.raises(TruthError, match=r"eventos.jsonl:1: .*otra"):
        list(table(truth_run(store, RUN), "eventos").rows())


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("otro", r"solo puede haber carpetas <perfil>-s<semilla>"),
        ("realista-7", r"solo puede haber carpetas <perfil>-s<semilla>"),
        ("extremo-s1", r"solo puede haber carpetas <perfil>-s<semilla>"),
        ("realista-s007", r"la semilla no está escrita como un entero"),
    ],
)
def test_una_carpeta_de_registros_con_otro_nombre_es_un_error(recorded, tmp_path, name, message):
    """Pilla una carpeta que se salte en silencio: la libreta de la ejecución quedaría a medias
    sin que nadie lo sepa."""
    store, path = copy_run(recorded[0], RUN, tmp_path)
    (path / "registros" / name).mkdir(parents=True)

    with pytest.raises(TruthError, match=message):
        truth_run(store, RUN)


def test_una_libreta_que_falta_es_un_error(recorded, tmp_path):
    """Pilla una carpeta de registro sin `defectos.csv` que deje la libreta de ese perfil vacía
    sin avisar."""
    store, path = copy_run(recorded[0], RUN, tmp_path)
    for name in ("limpio-s3", "realista-s7"):
        source = recorded[1] / "registros" / name
        (path / "registros" / name).mkdir(parents=True)
        for file in source.iterdir():
            (path / "registros" / name / file.name).write_bytes(file.read_bytes())
    (path / "registros" / "limpio-s3" / "defectos.csv").unlink()

    with pytest.raises(TruthError, match=r"limpio-s3.*falta el fichero de la libreta"):
        truth_run(store, RUN)
