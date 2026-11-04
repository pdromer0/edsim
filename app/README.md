# EDsim Lab

App local de EDsim para ajustar un centro de urgencias, simularlo por lotes y
explorar sus ejecuciones guardadas. La fase 1 usa el motor del hito 3; su alcance
y los incrementos previstos están en la
[especificación](docs/specs/fase-1.md#objetivo-y-alcance-de-la-fase-1).

## Preparar y arrancar

Desde la raíz del repositorio, con [uv](https://docs.astral.sh/uv/getting-started/installation/)
instalado:

```bash
uv sync --all-packages
uv run --package edsim-app edsim-app
```

Abre `http://localhost:8501`. El lanzador fija localhost y el puerto 8501; desde
Windows se accede por el reenvío de localhost de WSL2. Se detiene con Ctrl+C.
Es una app para un usuario en su equipo, sin autenticación ni despliegue remoto.

El workspace comparte `.venv` y `uv.lock` con el núcleo. Usa
`uv sync --all-packages` para preparar ambos paquetes: `uv sync` simple sincroniza
solo el núcleo y retira la app y sus dependencias exclusivas. El arranque con
`--package edsim-app` instala lo que falte.

## Las seis páginas

| Grupo | Página | Para qué sirve |
| --- | --- | --- |
| Ejecutar | Ejecuciones | Abrir el catálogo, elegir una ejecución, marcar A/B, descargarla y borrarla con confirmación. |
| Ejecutar | Simular | Editar el centro, guardar una variante TOML, prever la carga y simular el fichero guardado. |
| Analizar | Resultados | Consultar KPIs, esperas, ocupación, censo, Little e invariantes. |
| Analizar | Episodios | Filtrar pacientes, seguir su recorrido y contrastarlo con «Ver la verdad». |
| Analizar | Comparar | Contrastar A y B y comprobar el emparejamiento antes de mostrar diferencias paciente a paciente. |
| Analizar | Replay | Reconstruir un instante del servicio y reproducir su evolución en el plano. |

La ejecución seleccionada se comparte entre páginas y aparece en `?run=…`.
Cada página incluye «¿Qué estoy viendo?» con los conceptos de su vista.

## Datos en disco

El catálogo predeterminado es `resultados/ejecuciones/`, relativo a la carpeta
desde la que se arranca. Para usar otro catálogo:

```bash
EDSIM_EJECUCIONES=/ruta/al/catalogo uv run --package edsim-app edsim-app
```

`EDSIM_EJECUCIONES` admite también una ruta relativa al directorio de arranque;
la página Ejecuciones muestra la ruta utilizada. Esta variable cambia el catálogo
de la app. Para las configuraciones y variantes, arranca desde la raíz del
repositorio: se usan `config/` y `resultados/variantes/`.

La CLI y la app comparten el
[formato de ejecución](../docs/decisiones/0032-ejecuciones-en-carpetas-reproducibles.md).
Las ejecuciones predeterminadas de `edsim motor simular` aparecen en el catálogo.
Para conservar una variante en Git, cópiala a `config/` y versiónala a mano;
los experimentos se mantienen en `resultados/`.

## Tests

Desde la raíz:

```bash
# App: comprobaciones rápidas, incluidos los humos de las seis páginas
uv run --package edsim-app pytest app/tests -m "not slow"
# App: suite completa, con las integraciones marcadas slow
uv run --package edsim-app pytest app/tests
# Núcleo: suite rápida y completa
uv run pytest -m "not slow"
uv run pytest
# Lint y comprobación del formato de ambos paquetes
uv run ruff check .
uv run ruff format --check .
```

Las páginas se prueban con AppTest sin arrancar un servidor. Las comprobaciones
de interfaz y las medidas con AppTest se completan con revisión en el navegador.
La selección de tests `slow` se explica en [AGENTS.md](AGENTS.md#pruebas-y-convenciones).

## Frontera y documentación

La app recoge y presenta datos. Simulación, cálculos y persistencia viven en
`edsim`, con tests; los servicios de ejecuciones que usa se exportan en
`edsim.runs.__all__`. El núcleo no importa Streamlit, pandas ni `edsim_app`.
Los tests de frontera y los jobs separados de CI comprueban esa dirección de
dependencias.

- [Especificación y anexo de la fase 1](docs/specs/fase-1.md)
- [ADR de la app](docs/decisiones/README.md)
- [ADR del núcleo](../docs/decisiones/README.md)
- [Diario de la fase y comparación entre agentes](docs/diario/fase-1.md)
- [Instrucciones para trabajar en la app](AGENTS.md)
