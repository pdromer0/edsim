"""`record_run`: lo registrado de una ejecución guardada, escrito junto a ella (tarea 7.2).

Cada test dice qué error pilla. Las ejecuciones son las de 3 días de `clinical_store` (provisional,
hito 4 y hito 4 con sala) y una del hito 5, escritas con `simulate_run`; ningún test las toca:
trabajan sobre copias de `copy_run`. Las huellas y los recuentos se calculan con código propio del
test, no con el de `record_run`.
"""

import csv
import hashlib
import json
import os
from pathlib import Path

import pytest
from registro_factory import PROFILES_FILE
from runs_factory import copy_run

from edsim.clinical_record import NOTEBOOK_COLUMNS, PROFILE_NAMES
from edsim.runs import RecordRunResult, RunStore, record_run, simulate_run

DATA = Path(__file__).parent / "data"
RUNS = ("clinica", "provisional", "clinica-sala")
RECORDING_FILES = {"registrado.jsonl", "defectos.csv", "registro_clinico.toml", "registro.json"}
OLD = 1_000_000_000_000_000_000  # ns: una fecha de 2001, anterior a cualquier fichero de test


@pytest.fixture(scope="module")
def hito5_store(tmp_path_factory):
    """Una ejecución del hito 5 (catálogo v4), de 2 días, para recorrer las cuatro versiones."""
    root = tmp_path_factory.mktemp("hito5-registro")
    simulate_run(
        DATA / "centro_h5_ejemplo.toml",
        DATA / "llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / "hito5",
        run_id="hito5",
        warmup_days=1,
        origin="cli",
        profiles=DATA / "perfiles_h5_ejemplo.toml",
    )
    return RunStore(root)


def fresh(store, tmp_path, run_id="clinica"):
    """Una copia de la ejecución en `tmp_path`: su `RunStore` y su carpeta."""
    return copy_run(store, run_id, tmp_path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prints(directory: Path) -> dict:
    """La huella de cada fichero de una carpeta: tamaño, SHA-256 y `mtime_ns`, sin `registros`."""
    out = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and "registros" not in path.relative_to(directory).parts:
            stat = path.stat()
            out[path.relative_to(directory).as_posix()] = (
                stat.st_size,
                sha(path),
                stat.st_mtime_ns,
            )
    return out


def age(directory: Path) -> None:
    """Pone a cada fichero una fecha vieja: un rewrite, aunque sea igual, la cambia."""
    for path in directory.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(OLD, OLD))


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")[:-1]


def test_escribe_los_cuatro_ficheros_en_registros_perfil_semilla(clinical_store, tmp_path):
    """Pilla una carpeta con otro nombre, ficheros de más o de menos, o restos de la temporal."""
    store, run_dir = fresh(clinical_store, tmp_path)
    result = record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert isinstance(result, RecordRunResult)
    assert result.path == run_dir / "registros" / "realista-s7"
    assert {p.name for p in result.path.iterdir()} == RECORDING_FILES
    assert [p.name for p in (run_dir / "registros").iterdir()] == ["realista-s7"]
    assert not [p for p in run_dir.iterdir() if p.name.startswith(".")], "restos de la temporal"


def test_registro_json_dice_de_donde_sale_lo_registrado(clinical_store, tmp_path):
    """Pilla un `registro.json` con claves de menos, en otro orden o con una huella que no es."""
    store, _ = fresh(clinical_store, tmp_path)
    result = record_run(store, "clinica", "hostil", 7, profiles_file=PROFILES_FILE)
    info = json.loads((result.path / "registro.json").read_text(encoding="utf-8"))
    assert list(info) == [
        "run_id",
        "run_id_origen",
        "perfil",
        "semilla",
        "horizonte",
        "huella",
        "cuenta",
    ]
    assert info["run_id"] == "clinica_hostil_s7"
    assert (info["run_id_origen"], info["perfil"], info["semilla"]) == ("clinica", "hostil", 7)
    assert info["horizonte"] == 3 * 1440
    assert info["huella"] == hashlib.sha256(PROFILES_FILE.read_bytes()).hexdigest()[:12]
    assert dict(result.info) == info
    # La cuenta, recontada a mano: hechos de la verdad y registros escritos.
    truth = [json.loads(line) for line in lines(store.root / "clinica" / "eventos.jsonl")]
    resource = [e for e in truth if e["source_system"] == "rrhh"]
    assert info["cuenta"]["hechos_recursos"] == len(resource)
    assert info["cuenta"]["hechos_pacientes"] == len(truth) - len(resource)
    assert info["cuenta"]["registros"] == len(lines(result.path / "registrado.jsonl"))


def test_la_copia_del_fichero_es_la_que_se_uso(clinical_store, tmp_path):
    """Pilla un perfil leído del original en vez de la copia, o una copia con otro contenido.

    Se usa otro fichero (con el olvido del realista a 0,5): la copia, la huella y lo registrado
    tienen que ser los suyos.
    """
    store, _ = fresh(clinical_store, tmp_path)
    text = PROFILES_FILE.read_text(encoding="utf-8")
    assert text.count("olvido = 0.005 ") == 1
    other = tmp_path / "otros_perfiles.toml"
    other.write_text(text.replace("olvido = 0.005 ", "olvido = 0.5   "), encoding="utf-8")
    result = record_run(store, "clinica", "realista", 7, profiles_file=other)
    assert (result.path / "registro_clinico.toml").read_bytes() == other.read_bytes()
    assert result.info["huella"] == hashlib.sha256(other.read_bytes()).hexdigest()[:12]
    cuenta = result.info["cuenta"]
    assert 0.4 < cuenta["perdido"] / cuenta["hechos_pacientes"] < 0.6


def test_la_semilla_por_defecto_es_la_de_la_ejecucion(clinical_store, tmp_path):
    """Pilla una semilla por defecto que no es la de `run.json` (V25: un 0 fijo)."""
    store, run_dir = fresh(clinical_store, tmp_path)
    seed = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["seed"]
    assert seed != 0
    result = record_run(store, "clinica", "realista", profiles_file=PROFILES_FILE)
    assert result.path.name == f"realista-s{seed}"
    assert result.info["semilla"] == seed
    assert result.info["run_id"] == f"clinica_realista_s{seed}"


def test_mismos_bytes_con_la_misma_verdad_perfil_y_semilla(clinical_store, tmp_path):
    """Pilla un fichero que depende de algo más que de la entrada (la hora, el orden de un set)."""
    first, _ = fresh(clinical_store, tmp_path / "a")
    second, _ = fresh(clinical_store, tmp_path / "b")
    a = record_run(first, "clinica", "hostil", 11, profiles_file=PROFILES_FILE).path
    b = record_run(second, "clinica", "hostil", 11, profiles_file=PROFILES_FILE).path
    for name in RECORDING_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_otra_semilla_otros_despistes_sobre_la_misma_verdad(clinical_store, tmp_path):
    """Pilla una semilla que no llega al dado o que cambia los hechos.."""
    store, run_dir = fresh(clinical_store, tmp_path)
    a = record_run(store, "clinica", "realista", 1, profiles_file=PROFILES_FILE).path
    b = record_run(store, "clinica", "realista", 2, profiles_file=PROFILES_FILE).path
    assert (a / "defectos.csv").read_bytes() != (b / "defectos.csv").read_bytes()

    def facts(path):
        rows = csv.DictReader((path / "defectos.csv").open(encoding="utf-8"))
        return sorted({row["hecho"] for row in rows})

    assert facts(a) == facts(b)
    truth = [json.loads(line)["event_id"] for line in lines(run_dir / "eventos.jsonl")]
    assert facts(a) == sorted(truth)


@pytest.mark.parametrize("run_id", RUNS)
def test_el_perfil_limpio_es_la_verdad_salvo_los_identificadores(clinical_store, tmp_path, run_id):
    """Pilla un limpio que altera algo: cada registro es el evento verdadero con otro id.

    Compara los diccionarios JSON línea a línea, quitando `event_id` y `run_id`, y la libreta
    solo debe tener hechos `bien`.
    """
    store, run_dir = fresh(clinical_store, tmp_path, run_id)
    path = record_run(store, run_id, "limpio", 3, profiles_file=PROFILES_FILE).path
    truth = [json.loads(line) for line in lines(run_dir / "eventos.jsonl")]
    recorded = [json.loads(line) for line in lines(path / "registrado.jsonl")]
    assert len(recorded) == len(truth) > 100

    def bare(event):
        return {k: v for k, v in event.items() if k not in ("event_id", "run_id")}

    assert [bare(r) for r in recorded] == [bare(t) for t in truth]
    assert {r["run_id"] for r in recorded} == {f"{run_id}_limpio_s3"}
    assert [r["event_id"] for r in recorded][:2] == [
        f"{run_id}_limpio_s3-000000001",
        f"{run_id}_limpio_s3-000000002",
    ]
    rows = list(csv.DictReader((path / "defectos.csv").open(encoding="utf-8")))
    assert {row["clase"] for row in rows} == {"bien"}
    assert [row["hecho"] for row in rows] == [t["event_id"] for t in truth]


@pytest.mark.parametrize("run_id", RUNS)
def test_no_toca_los_ficheros_de_la_ejecucion(clinical_store, tmp_path, run_id):
    """Pilla un `record_run` que reescribe un fichero de la ejecución (V8), aunque sea igual.

    La huella es tamaño, SHA-256 y `mtime_ns`, con los ficheros puestos a una fecha vieja antes:
    reescribir `eventos.jsonl` con los mismos bytes cambia el `mtime`.
    """
    store, run_dir = fresh(clinical_store, tmp_path, run_id)
    age(run_dir)
    before = prints(run_dir)
    names_before = {p.name for p in run_dir.iterdir()}
    assert "eventos.jsonl" in before and "ground_truth_episodios.csv" in before
    for name in PROFILE_NAMES:
        record_run(store, run_id, name, 5, profiles_file=PROFILES_FILE)
    assert prints(run_dir) == before
    assert {p.name for p in run_dir.iterdir()} == names_before | {"registros"}


def test_la_ejecucion_sigue_siendo_valida_para_el_catalogo(clinical_store, tmp_path):
    """Pilla una subcarpeta que rompe `RunStore`: se abre, se lista y se archiva igual."""
    store, run_dir = fresh(clinical_store, tmp_path)
    archive = store.archive("clinica")
    info = store.open("clinica")
    record_run(store, "clinica", "realista", profiles_file=PROFILES_FILE)
    assert store.open("clinica") == info
    assert [i.run_id for i in store.list()] == ["clinica"]
    assert store.invalid() == []
    assert store.archive("clinica") == archive


def test_cada_version_del_catalogo_con_el_hostil_cuadra(clinical_store, hito5_store, tmp_path):
    """Pilla una versión del catálogo que `record_run` no sabe leer (v1, v3 y v4).

    `record` lanza `RuntimeError` si la cuenta no cuadra, así que escribir ya es comprobarlo; el
    test mira además que salgan las clases de verdad: lo registrado no es una copia de la verdad.
    """
    versions = set()
    for source, run_id in (
        (clinical_store, "provisional"),
        (clinical_store, "clinica"),
        (hito5_store, "hito5"),
    ):
        store, _ = fresh(source, tmp_path / run_id, run_id)
        path = record_run(store, run_id, "hostil", 9, profiles_file=PROFILES_FILE).path
        rows = list(csv.DictReader((path / "defectos.csv").open(encoding="utf-8")))
        assert {"con_despistes", "perdido", "duplicado"} <= {row["clase"] for row in rows}, run_id
        versions.add(store.open(run_id).catalog_version)
    assert versions == {1, 3, 4}


# --- Errores antes de escribir ------------------------------------------------------------


def nothing_left(run_dir: Path) -> bool:
    return not (run_dir / "registros").exists() and not [
        p for p in run_dir.iterdir() if p.name.startswith(".")
    ]


@pytest.mark.parametrize(
    ("profile", "seed", "message"),
    [
        ("caotico", 7, "unknown profile"),
        ("realista", -1, "seed must be an integer >= 0"),
        ("realista", True, "seed must be an integer >= 0"),
        ("realista", 1.5, "seed must be an integer >= 0"),
    ],
    ids=["perfil_desconocido", "semilla_negativa", "semilla_bool", "semilla_decimal"],
)
def test_un_perfil_o_una_semilla_no_validos_no_dejan_nada(
    clinical_store, tmp_path, profile, seed, message
):
    """Pilla un error que llega después de crear carpetas: no puede quedar nada."""
    store, run_dir = fresh(clinical_store, tmp_path)
    with pytest.raises(ValueError, match=message):
        record_run(store, "clinica", profile, seed, profiles_file=PROFILES_FILE)
    assert nothing_left(run_dir)


def test_un_run_id_derivado_que_no_cabe_falla_antes_de_crear_nada(clinical_store, tmp_path):
    """Pilla el `run_id` largo que con `_realista_s7` ya no cabe en 64 caracteres (nota 5 del 13).

    La copia lleva el `run_id` largo también en su `run.json`, para que sea una ejecución válida
    (el límite exacto de 64 lo prueba `derived_run_id` en la 7.1). El error sale antes de leer el
    log: si lo leyera, diría que sus eventos no son de esa ejecución.
    """
    long_id = "r" * 54
    store, run_dir = copy_run(clinical_store, "clinica", tmp_path, long_id)
    info = (run_dir / "run.json").read_text(encoding="utf-8")
    assert info.count('"run_id": "clinica"') == 1
    (run_dir / "run.json").write_text(
        info.replace('"run_id": "clinica"', f'"run_id": "{long_id}"'), encoding="utf-8"
    )
    assert len(f"{long_id}_realista_s7") > 64
    with pytest.raises(ValueError, match="derived run_id"):
        record_run(store, long_id, "realista", 7, profiles_file=PROFILES_FILE)
    assert nothing_left(run_dir)


def test_una_ejecucion_que_no_existe(clinical_store, tmp_path):
    """Pilla una ejecución ausente que se confunde con otro error."""
    store, _ = fresh(clinical_store, tmp_path)
    with pytest.raises(OSError):
        record_run(store, "no-existe", "realista", profiles_file=PROFILES_FILE)


@pytest.mark.parametrize("problem", ["ausente", "invalido"])
def test_un_fichero_de_perfiles_malo_no_deja_nada(clinical_store, tmp_path, problem):
    """Pilla un fichero de perfiles ilegible: falla sin dejar la carpeta temporal ni `registros`."""
    store, run_dir = fresh(clinical_store, tmp_path)
    bad = tmp_path / "malos.toml"
    if problem == "invalido":
        bad.write_text("[limpio]\nolvido = 3\n", encoding="utf-8")
        error = ValueError
    else:
        error = OSError
    with pytest.raises(error):
        record_run(store, "clinica", "realista", 7, profiles_file=bad)
    assert nothing_left(run_dir)


def test_una_linea_rota_del_log_dice_su_numero_y_no_deja_nada(clinical_store, tmp_path):
    """Pilla un log ilegible que se traga la línea: el error dice `eventos.jsonl:3`."""
    store, run_dir = fresh(clinical_store, tmp_path)
    events = run_dir / "eventos.jsonl"
    text = events.read_text(encoding="utf-8").split("\n")
    text[2] = '{"esto": "no es un evento"}'
    events.write_text("\n".join(text), encoding="utf-8")
    with pytest.raises(ValueError, match=r"eventos\.jsonl:3:"):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert nothing_left(run_dir)


def test_un_log_vacio_da_ficheros_vacios_y_la_cuenta_a_cero(clinical_store, tmp_path):
    """Pilla un log vacío que revienta (`record` lo admite) o que escribe lo que no hay."""
    store, run_dir = fresh(clinical_store, tmp_path)
    (run_dir / "eventos.jsonl").write_text("", encoding="utf-8")
    result = record_run(store, "clinica", "hostil", 7, profiles_file=PROFILES_FILE)
    assert (result.path / "registrado.jsonl").read_bytes() == b""
    assert lines(result.path / "defectos.csv") == [",".join(NOTEBOOK_COLUMNS)]
    assert set(result.info["cuenta"].values()) == {0}


# --- Destino y atomicidad -----------------------------------------------------------------


def test_un_destino_que_existe_no_se_sobrescribe(clinical_store, tmp_path):
    """Pilla un segundo `record_run` que pisa el primero."""
    store, run_dir = fresh(clinical_store, tmp_path)
    first = record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE).path
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    with pytest.raises(FileExistsError, match="realista-s7"):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == before
    assert not [p for p in run_dir.iterdir() if p.name.startswith(".")]


def test_registros_que_es_un_fichero_es_un_error_claro(clinical_store, tmp_path):
    """Pilla un `registros` que no es una carpeta: no se pisa ni se borra."""
    store, run_dir = fresh(clinical_store, tmp_path)
    (run_dir / "registros").write_text("no soy una carpeta", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert (run_dir / "registros").read_text(encoding="utf-8") == "no soy una carpeta"
    assert not [p for p in run_dir.iterdir() if p.name.startswith(".")]


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("disco lleno"), KeyboardInterrupt()],
    ids=lambda failure: type(failure).__name__,
)
def test_un_fallo_a_mitad_no_deja_una_carpeta_a_medias(
    clinical_store, tmp_path, monkeypatch, failure
):
    """Pilla una escritura sin carpeta temporal (V24): un fallo tras `registrado.jsonl`.

    La libreta es lo último que se escribe; si falla, ni `registros/realista-s7` ni la temporal
    pueden quedar, tampoco con Ctrl+C.
    """
    store, run_dir = fresh(clinical_store, tmp_path)

    def broken(rows):
        raise failure

    monkeypatch.setattr("edsim.runs.recorded.notebook_csv", broken)
    with pytest.raises(type(failure)):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert nothing_left(run_dir)


def test_un_fallo_al_renombrar_no_deja_la_temporal(clinical_store, tmp_path, monkeypatch):
    """Pilla un fallo en el renombrado final: la temporal se borra y el destino no existe."""
    store, run_dir = fresh(clinical_store, tmp_path)
    real_rename = Path.rename

    def fail(self, target):
        if self.name.startswith(".registros-"):
            raise OSError("sin permiso")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError, match="sin permiso"):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert not (run_dir / "registros" / "realista-s7").exists()
    assert not [p for p in run_dir.iterdir() if p.name.startswith(".")]


def test_un_registro_que_aparece_a_mitad_se_dice_como_destino_existente(
    clinical_store, tmp_path, monkeypatch
):
    """Pilla una carrera con otro `generar`: el renombrado falla y el error es `FileExistsError`.

    Se simula con un `rename` que primero deja escrito el destino, como haría el otro proceso.
    """
    store, run_dir = fresh(clinical_store, tmp_path)
    destination = run_dir / "registros" / "realista-s7"
    real_rename = Path.rename

    def lose_the_race(self, target):
        if self.name.startswith(".registros-"):
            destination.mkdir(parents=True)
            (destination / "otro.txt").write_text("del otro proceso", encoding="utf-8")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", lose_the_race)
    with pytest.raises(FileExistsError, match="realista-s7"):
        record_run(store, "clinica", "realista", 7, profiles_file=PROFILES_FILE)
    assert (destination / "otro.txt").read_text(encoding="utf-8") == "del otro proceso"
    assert not [p for p in run_dir.iterdir() if p.name.startswith(".")]
