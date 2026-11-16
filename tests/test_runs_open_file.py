"""`RunStore.open_file`: leer un fichero de la ejecución en flujo, con las pruebas de `read_file`.

La carga de la verdad (tarea 8.4) lee `eventos.jsonl`, que en un año pesa unos 550 MB: `read_file`
lo cargaría entero. `open_file` lo da línea a línea y no se salta ninguna de sus comprobaciones.
"""

import os

import pytest

from edsim.runs import RunStore, simulate_run


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    root = tmp_path_factory.mktemp("open-file")
    simulate_run(
        "tests/data/centro_ejemplo.toml",
        "tests/data/llegadas_ejemplo.toml",
        2,
        7,
        output_dir=root / "muestra",
        run_id="muestra",
        warmup_days=1,
        origin="cli",
    )
    return RunStore(root), root / "muestra"


@pytest.mark.parametrize("filename", ["eventos.jsonl", "ground_truth_episodios.csv", "run.json"])
def test_open_file_da_los_mismos_bytes_que_read_file(saved, filename):
    """Pilla un `open_file` que cambie los finales de línea o la codificación: el texto, vuelto
    a codificar, es el fichero tal cual."""
    store, _ = saved
    with store.open_file("muestra", filename) as source:
        text = source.read()
    assert text.encode("utf-8") == store.read_file("muestra", filename)


def test_open_file_da_el_fichero_linea_a_linea(saved):
    """Pilla un `open_file` que lea el fichero entero antes de dar la primera línea."""
    store, path = saved
    with store.open_file("muestra", "eventos.jsonl") as source:
        first = next(iter(source))
        assert first == (path / "eventos.jsonl").read_text(encoding="utf-8").split("\n")[0] + "\n"


@pytest.mark.parametrize("filename", ["../run.json", "extra.txt", "/etc/passwd", "registros/x"])
def test_open_file_rechaza_nombres_que_no_son_del_formato(saved, filename):
    """Pilla un `open_file` que abra cualquier ruta, no solo los ficheros del formato."""
    store, _ = saved
    with pytest.raises(ValueError, match="filename"):
        store.open_file("muestra", filename)


@pytest.mark.parametrize("kind", ["enlace", "carpeta", "fifo"])
def test_open_file_rechaza_lo_que_no_es_un_fichero_regular(saved, tmp_path, kind):
    """Pilla un `open_file` que siga un enlace fuera de la ejecución o se cuelgue con una FIFO."""
    store, path = saved
    copy = tmp_path / "copia"
    copy.mkdir()
    for name in store.run_files("muestra"):
        (copy / name).write_bytes((path / name).read_bytes())
    target = copy / "eventos.jsonl"
    target.unlink()
    if kind == "enlace":
        outside = tmp_path / "fuera"
        outside.write_text("{}\n", encoding="utf-8")
        target.symlink_to(outside)
    elif kind == "carpeta":
        target.mkdir()
    else:
        os.mkfifo(target)
    with pytest.raises(ValueError, match="regular"):
        RunStore(tmp_path).open_file("copia", "eventos.jsonl")
