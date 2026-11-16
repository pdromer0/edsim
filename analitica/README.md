# analitica: el proyecto dbt de EDsim

De bronce (lo que llega de Kafka) a preparación, plata y oro, como código: modelos SQL con sus dependencias, sus tests y su documentación. La especificación está en [docs/specs/hito-8.md](../docs/specs/hito-8.md).

Es un proyecto uv **aparte**, con su propio `pyproject.toml` y su propio `uv.lock`, fuera del workspace del núcleo (decisión 101, H8-2): las dependencias de dbt no tocan el lock del núcleo.

## Cómo se lanza

Siempre desde esta carpeta: dbt busca aquí `dbt_project.yml` y `profiles.yml`.

```bash
cd analitica
uv sync --locked                       # el entorno de dbt, en analitica/.venv
uv run dbt parse                       # comprueba Jinja, ref() y source(); no conecta
uv run dbt build --select preparacion  # construye la preparación y pasa sus unit tests
uv run dbt build --vars '{hoja: ingenuo}'  # otra hoja, en sus propios esquemas
```

La conexión sale de `profiles.yml`: `EDSIM_PG_HOST` (`localhost`), `EDSIM_PG_PUERTO` (`5432`), `EDSIM_PG_USUARIO` (`edsim`), `EDSIM_PG_CLAVE` (`edsim`) y `EDSIM_PG_BASE` (`edsim`), con los valores de `compose.yaml` por defecto. Las pruebas usan su propia base con `EDSIM_PG_BASE`: nunca la base `edsim`.

`bronce.eventos` debe existir (`edsim almacen preparar`): dbt consulta los tipos de las columnas de los padres de un modelo también en los unit tests.

## Qué hay

| Ruta | Qué es |
| --- | --- |
| `dbt_project.yml` | El proyecto, la variable `hoja` (`hospital`, `verdad` o `ingenuo`) y la telemetría desactivada |
| `profiles.yml` | La conexión, con `env_var()` |
| `macros/generate_schema_name.sql` | Esquemas con el nombre exacto de su capa y, fuera del hospital, la hoja delante |
| `macros/fuente_registros.sql` | `bronce.eventos` o `verdad.eventos`, según la hoja |
| `models/fuentes.yml` | Las tablas que dbt lee y no construye |
| `models/preparacion/` | `registros` (vista) y `registros_vigentes` (tabla, la limpieza), con su documentación y sus unit tests |

Los tests de dbt corren en el job `tests-integracion` del CI, desde `tests_integracion/test_analitica.py`, contra una base de prueba.
