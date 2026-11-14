"""El tope común de los dobles de prueba que un bucle del código real llama una y otra vez.

Un doble que registra cada llamada (una lista que crece) y que un bucle sin fin puede llamar
sin parar, llena la memoria antes de que ningún límite de tiempo actúe: en la 7.5, una versión
incorrecta llevó el registro del consumidor falso a 7,5 GB en un minuto. Con un tope, ese bucle
falla en segundos con `RunawayLoop`, que dice qué doble y cuántas llamadas.

Regla (AGENTS.md, «Convenciones»): un doble que se llama en bucle lleva un tope que lanza un
error claro. El límite de tiempo por test (`timeout` en `pyproject.toml`) es la red general;
este tope es la primera, porque corta antes de que la memoria crezca.
"""


class RunawayLoop(AssertionError):
    """Un bucle llamó a un doble más veces que su tope: no iba a parar."""


def check_calls(calls: int, limit: int, what: str) -> None:
    """Lanza `RunawayLoop` si `calls`, las llamadas ya hechas a `what`, pasan de `limit`."""
    if calls > limit:
        raise RunawayLoop(f"{limit} llamadas a {what}: el bucle no para")
