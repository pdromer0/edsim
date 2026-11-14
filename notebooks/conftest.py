"""Límite de tiempo de los notebooks, que `pytest --nbmake notebooks/` ejecuta como tests."""

from pathlib import Path

import pytest

NOTEBOOK_TIMEOUT = 1800
"""Segundos por notebook entero. El peor, en modo rápido, tarda 25 s (14-nov-2026); el modo
normal tarda más. El límite que corta de verdad es el de `nbmake` por celda
(`--nbmake-timeout`, 300 s por defecto): este solo es la red por si algo lo esquiva, y el
límite general de 60 s del `pyproject.toml` no deja ejecutar el modo normal."""


def pytest_collection_modifyitems(items):
    """Da a los notebooks el límite de `NOTEBOOK_TIMEOUT`, mayor que el general."""
    here = Path(__file__).parent
    for item in items:
        if item.path.is_relative_to(here) and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(NOTEBOOK_TIMEOUT))
