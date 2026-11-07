"""Auxiliares para trabajar con ejecuciones guardadas en los tests (tarea 4.8a)."""

from pathlib import Path

from edsim.runs import RunStore


def copy_run(store, run_id, root, new_id=None):
    """Copia una ejecución guardada en ``root`` y devuelve su ``RunStore`` y su carpeta."""
    destination = Path(root) / (new_id or run_id)
    destination.mkdir(parents=True)
    for name in store.run_files(run_id):
        (destination / name).write_bytes(store.read_file(run_id, name))
    return RunStore(root), destination
