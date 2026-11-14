"""`read_recorded_run` y `read_recorded_records`: leer lo registrado de una ejecución (tarea 7.3).

Cada test dice qué error pilla. Las ejecuciones son copias de la `clinica` de 3 días de
`clinical_store`, registradas con `record_run` con los tres perfiles; los recuentos del test se
calculan con código propio (contar líneas), no con el lector. Los errores se prueban sobre una
copia de la carpeta del registro que el test estropea.
"""

import json
import shutil

import pytest
from registro_factory import PROFILES_FILE
from runs_factory import copy_run

from edsim.clinical_record import PROFILE_NAMES
from edsim.runs import (
    RecordedRun,
    read_recorded_records,
    read_recorded_run,
    record_run,
)
from edsim.runs.recorded import RunLogError

RUN = "clinica"


@pytest.fixture(scope="module")
def recorded_store(clinical_store, tmp_path_factory):
    """Una copia de `clinica` con sus tres registros (limpio, realista y hostil), semilla de la
    ejecución, y el realista con la semilla 5."""
    root = tmp_path_factory.mktemp("registradas")
    store, _ = copy_run(clinical_store, RUN, root)
    for profile in PROFILE_NAMES:
        record_run(store, RUN, profile, profiles_file=PROFILES_FILE)
    record_run(store, RUN, "realista", 5, profiles_file=PROFILES_FILE)
    return store


@pytest.fixture
def broken(recorded_store, tmp_path):
    """Una copia de `registros/realista-s<semilla>/` que el test puede estropear."""
    seed = recorded_store.open(RUN).seed
    store, run_dir = copy_run(recorded_store, RUN, tmp_path)
    shutil.copytree(recorded_store.root / RUN / "registros", run_dir / "registros", symlinks=True)
    return store, run_dir / "registros" / f"realista-s{seed}"


def lines(path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line]


def test_lee_la_verdad_el_horizonte_el_calentamiento_y_la_libreta(recorded_store):
    """Las cifras de la ejecución, contadas aparte: eventos del log, filas de la libreta, y el
    horizonte y el calentamiento en minutos (días × 1.440). Pilla un horizonte en días, o un
    calentamiento que se queda en días (el censo medio saldría de otras horas)."""
    saved = recorded_store.open(RUN)
    run = read_recorded_run(recorded_store, RUN, "realista")

    assert isinstance(run, RecordedRun)
    assert run.run_id == RUN
    assert run.derived_run_id == f"{RUN}_realista_s{saved.seed}"
    assert (run.profile, run.seed) == ("realista", saved.seed)
    assert len(run.truth) == len(lines(recorded_store.root / RUN / "eventos.jsonl"))
    assert len(run.notebook) == len(lines(run.path / "defectos.csv")) - 1
    assert run.horizon == saved.days * 1440 == run.info["horizonte"]
    assert run.warmup == saved.warmup_days * 1440
    assert 0 < run.warmup < run.horizon
    assert run.path == recorded_store.root / RUN / "registros" / f"realista-s{saved.seed}"


def test_la_semilla_por_defecto_es_la_de_la_ejecucion_y_se_puede_elegir(recorded_store):
    """Pilla una semilla por defecto que no es la de la ejecución, o una elegida que se ignora."""
    default = read_recorded_run(recorded_store, RUN, "realista")
    chosen = read_recorded_run(recorded_store, RUN, "realista", 5)

    assert chosen.seed == 5
    assert chosen.derived_run_id == f"{RUN}_realista_s5"
    assert chosen.path.name == "realista-s5"
    assert default.seed != 5
    assert chosen.notebook != default.notebook  # otra semilla anota la misma verdad de otro modo


def test_los_registros_son_los_de_registrado_jsonl(recorded_store):
    """Un registro por línea, en el orden escrito, con los `event_id` de la ejecución derivada."""
    run = read_recorded_run(recorded_store, RUN, "realista")

    records = read_recorded_records(run)

    assert len(records) == len(lines(run.path / "registrado.jsonl"))
    assert [r.event_id for r in records] == [
        json.loads(line)["event_id"] for line in lines(run.path / "registrado.jsonl")
    ]
    assert {r.run_id for r in records} == {run.derived_run_id}


@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_la_cuenta_cuadra_con_la_ejecucion_real_de_cada_perfil(recorded_store, profile):
    """De punta a punta con ficheros reales: verdad, libreta y registros de cada perfil dan una
    conciliación sin error, con los hechos de la verdad y los registros escritos. Con el limpio,
    todos los indicadores iguales a los de la verdad."""
    run = read_recorded_run(recorded_store, RUN, profile)
    records = read_recorded_records(run)

    comparison = run.compare(records)

    assert comparison.reconciliation.facts == len(run.truth)
    assert comparison.reconciliation.records == len(records)
    assert sum(comparison.reconciliation.by_kind.values()) == len(run.notebook)
    assert comparison.truth.arrivals > 0
    assert comparison.truth.time_to_triage is not None
    if profile == "limpio":
        assert comparison.truth == comparison.recorded
    else:
        assert comparison.truth != comparison.recorded


def test_leer_no_toca_nada(recorded_store):
    """Leer la ejecución y sus registros no escribe: el tamaño y la fecha de cada fichero siguen
    igual (la comparación es una lectura)."""
    folder = recorded_store.root / RUN

    def prints():
        return {
            p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }

    before = prints()
    run = read_recorded_run(recorded_store, RUN, "hostil")
    read_recorded_records(run)

    assert prints() == before


# --- Errores -----------------------------------------------------------------------------------


def test_un_registro_que_no_existe_dice_como_generarlo(recorded_store):
    """Una semilla sin registro: `FileNotFoundError` con el perfil, la semilla y la carpeta."""
    with pytest.raises(FileNotFoundError, match="hostil-s99"):
        read_recorded_run(recorded_store, RUN, "hostil", 99)


@pytest.mark.parametrize(
    ("run_id", "profile", "seed"),
    [("clinica", "feroz", None), ("clinica", "realista", -1), ("clinica", "realista", True)],
)
def test_un_perfil_o_una_semilla_malos_son_value_error(recorded_store, run_id, profile, seed):
    """Se comprueban antes de buscar en el disco: un `ValueError`, no un fichero que no existe."""
    with pytest.raises(ValueError):
        read_recorded_run(recorded_store, run_id, profile, seed)


def test_una_ejecucion_que_no_existe_es_un_error(recorded_store):
    with pytest.raises((OSError, ValueError)):
        read_recorded_run(recorded_store, "no-existe", "realista")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("run_id", "otra_s1"),
        ("run_id_origen", "otra"),
        ("perfil", "hostil"),
        ("semilla", 99),
        ("horizonte", True),
        ("horizonte", "4320"),
    ],
)
def test_un_registro_json_de_otro_registro_es_un_error_de_datos(broken, key, value):
    """Una carpeta copiada con otro nombre, o un `registro.json` con un horizonte que no es un
    número: `RunLogError`, no una comparación contra la verdad de otra ejecución."""
    store, path = broken
    info = json.loads((path / "registro.json").read_text(encoding="utf-8"))
    info[key] = value
    (path / "registro.json").write_text(json.dumps(info), encoding="utf-8")

    with pytest.raises(RunLogError, match="registro.json"):
        read_recorded_run(store, RUN, "realista")


@pytest.mark.parametrize("content", ["{no es json", "[]", "3"])
def test_un_registro_json_que_no_es_un_objeto_es_un_error_de_datos(broken, content):
    store, path = broken
    (path / "registro.json").write_text(content, encoding="utf-8")

    with pytest.raises(RunLogError, match="registro.json"):
        read_recorded_run(store, RUN, "realista")


def test_una_libreta_estropeada_es_un_error_de_datos_con_su_linea(broken):
    """Una fila con una celda de menos: `RunLogError` que dice la línea de `defectos.csv`."""
    store, path = broken
    text = (path / "defectos.csv").read_text(encoding="utf-8").split("\n")
    text[3] = "una,fila,corta"
    (path / "defectos.csv").write_text("\n".join(text), encoding="utf-8")

    with pytest.raises(RunLogError, match=r"defectos\.csv:4"):
        read_recorded_run(store, RUN, "realista")


def test_un_registro_estropeado_es_un_error_de_datos_con_su_linea(broken):
    """Una línea de `registrado.jsonl` que no es un registro: `RunLogError` con su línea."""
    store, path = broken
    text = (path / "registrado.jsonl").read_text(encoding="utf-8").split("\n")
    text[1] = '{"event_id": 1}'
    (path / "registrado.jsonl").write_text("\n".join(text), encoding="utf-8")
    run = read_recorded_run(store, RUN, "realista")  # la verdad y la libreta se leen bien

    with pytest.raises(RunLogError, match=r"registrado\.jsonl:2"):
        read_recorded_records(run)


def test_un_fichero_que_no_es_regular_no_se_lee(broken):
    """Un enlace en lugar de `defectos.csv` se rechaza, como en `RunStore`."""
    store, path = broken
    target = path / "defectos.copia"
    target.write_bytes((path / "defectos.csv").read_bytes())
    (path / "defectos.csv").unlink()
    (path / "defectos.csv").symlink_to(target)

    with pytest.raises(RunLogError, match="not a regular file"):
        read_recorded_run(store, RUN, "realista")


def test_la_verdad_de_otra_ejecucion_es_un_error_de_datos(broken):
    """Un `eventos.jsonl` con una línea que no es un evento: el `RunLogError` de `generar`."""
    store, path = broken
    events = path.parent.parent / "eventos.jsonl"
    events.write_text("no es un evento\n", encoding="utf-8")

    with pytest.raises(RunLogError, match=r"eventos\.jsonl:1"):
        read_recorded_run(store, RUN, "realista")
