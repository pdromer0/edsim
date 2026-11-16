# analitica: el proyecto dbt de EDsim

De bronce (lo que llega de Kafka) a preparación, plata y oro, como código: modelos SQL con sus dependencias, sus tests y su documentación. La especificación está en [docs/specs/hito-8.md](../docs/specs/hito-8.md).

Es un proyecto uv **aparte**, con su propio `pyproject.toml` y su propio `uv.lock`, fuera del workspace del núcleo (decisión 101, H8-2): las dependencias de dbt no tocan el lock del núcleo.

## Cómo se lanza

Siempre desde esta carpeta: dbt busca aquí `dbt_project.yml` y `profiles.yml`.

```bash
cd analitica
uv sync --locked                       # el entorno de dbt, en analitica/.venv
uv run dbt parse                       # comprueba Jinja, ref() y source(); no conecta
EDSIM_PG_BASE=BASE uv run dbt build --exclude tag:laboratorio  # la hoja del hospital, con sus unit tests y sus tests de datos
EDSIM_PG_BASE=BASE uv run dbt build --exclude tag:laboratorio --vars '{hoja: verdad}' --exclude-resource-type unit_test   # la verdad
EDSIM_PG_BASE=BASE uv run dbt build --exclude tag:laboratorio --vars '{hoja: ingenuo}' --exclude-resource-type unit_test  # lo registrado sin limpiar
EDSIM_PG_BASE=BASE uv run dbt build --select tag:laboratorio  # la tabla de tres columnas, después de las tres hojas
```

**Las tres hojas** (decisión 107, H8-8) son tres construcciones del mismo proyecto, cada una en sus esquemas:

| Hoja | Lee de | Limpieza | Escribe en | La leen |
| --- | --- | --- | --- | --- |
| `hospital` (por defecto) | `bronce.eventos` | Sí | `preparacion`, `plata`, `oro` | `hospital` y `laboratorio` |
| `verdad` | `verdad.eventos` | Sí (no hay nada que limpiar) | `verdad_preparacion`, `verdad_plata`, `verdad_oro` | `laboratorio` |
| `ingenuo` | `bronce.eventos` | No, como `compare.py` | `ingenuo_preparacion`, `ingenuo_plata`, `ingenuo_oro` | `laboratorio` |

La tabla de tres columnas (`laboratorio.tres_columnas`, etiqueta `laboratorio`) lee el oro de las tres y se construye aparte, con la hoja `hospital`; las tres hojas la excluyen. Los unit tests van con la hoja del hospital: en la verdad fallarían, porque sus filas de prueba traen `ingest_time`.

**Los permisos.** La configuración `grants` da `SELECT` en cada tabla al crearla, y el `on-run-end` (`dar_uso_de_esquemas`) da `USAGE` en los esquemas que tocó la construcción. Los roles `hospital` y `laboratorio` los crea la migración `002_verdad.sql`.

`BASE` es una base de prueba preparada con `edsim almacen preparar --postgres URL`. Sin `EDSIM_PG_BASE`, dbt construye en la base `edsim`, la de los datos de compose.

La conexión sale de `profiles.yml`: `EDSIM_PG_HOST` (`localhost`), `EDSIM_PG_PUERTO` (`5432`), `EDSIM_PG_USUARIO` (`edsim`), `EDSIM_PG_CLAVE` (`edsim`) y `EDSIM_PG_BASE` (`edsim`), con los valores de `compose.yaml` por defecto. Las pruebas usan su propia base con `EDSIM_PG_BASE`: nunca la base `edsim`.

`bronce.eventos` debe existir (`edsim almacen preparar`): dbt consulta los tipos de las columnas de los padres de un modelo también en los unit tests.

## Qué hay

| Ruta | Qué es |
| --- | --- |
| `dbt_project.yml` | El proyecto, la variable `hoja` (`hospital`, `verdad` o `ingenuo`) y la telemetría desactivada |
| `profiles.yml` | La conexión, con `env_var()` |
| `macros/generate_schema_name.sql` | Esquemas con el nombre exacto de su capa y, fuera del hospital, la hoja delante |
| `macros/fuente_registros.sql` | `bronce.eventos` o `verdad.eventos`, según la hoja |
| `macros/columnas_registro.sql` | Las columnas que pasan sin tocar por la preparación, según la hoja |
| `models/fuentes.yml` | Las tablas que dbt lee y no construye |
| `macros/primero.sql` | El primer registro de un tipo en cada episodio, por orden de anotación |
| `macros/emparejar.sql` | El emparejamiento por tiempo de una apertura y su cierre, con `sin_pareja` |
| `models/preparacion/` | `registros` (vista) y `registros_vigentes` (tabla, la limpieza), con su documentación y sus unit tests |
| `models/plata/` | Las ocho tablas con la forma de un HIS, con su documentación, sus unit tests y sus tests de datos |
| `models/preparacion/parametros.sql` | El origen, W y el horizonte de cada ejecución, del `inicio` de bronce o de `verdad.dias` (`macros/fuente_parametros.sql`) |
| `models/oro/` | `censo`, `cohorte`, `kpi_hora`, `kpi_turno`, `kpi_ejecucion` y `calidad`, con su documentación, sus unit tests y sus tests de datos |
| `models/laboratorio/` | `tres_columnas`: cada KPI en la verdad, sin limpiar y limpiado |
| `seeds/` | `maestro_boxes.csv` y `turnos.csv`, copias de `config/centro.toml` (`tests/test_semillas_analitica.py` las compara) |
| `macros/turno_de.sql` | El turno de una hora, con aritmética entera sobre las horas desde el origen |
| `macros/dar_uso_de_esquemas.sql` | El `USAGE` de los esquemas, al final de cada construcción |
| `macros/kpis_en_filas.sql` | Los nueve KPI de `kpi_ejecucion`, en filas |
| `tests/generic/` | `clave_unica` y `relacion`: unicidad y relación de una clave compuesta, que los de dbt no admiten |

Los tests de dbt corren en el job `tests-integracion` del CI, contra bases de prueba: los unit tests y la hoja del hospital, desde `tests_integracion/test_analitica.py`; las cuatro construcciones con una ejecución de 3 días, comparadas con `compare.py`, desde `tests_integracion/test_punta_a_punta.py`.
