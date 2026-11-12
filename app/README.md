# EDsim Lab

App local de EDsim para ajustar un centro de urgencias, simularlo por lotes y
explorar sus ejecuciones guardadas. Desde el incremento del hito 4 (`app-v0.2.0`),
EDsim Lab simula con el modelo clínico. Cada paciente tiene edad, sexo, medio de
llegada, motivo, gravedad real oculta y un nivel de triaje con error. Las ejecuciones
provisionales del hito 3 se siguen abriendo; la app ya no las crea. Desde el
incremento del hito 5 (`app-v0.3.0`), también abre y simula el modelo del hito 5:
pacientes que se van sin ser vistos, cuatro destinos (alta, ingreso, traslado y
exitus) y la espera de cama de los ingresados, en su box o en el pasillo. Lo elige
el centro (`[camas]` en lugar de `[destino]`) junto con sus perfiles, y desde la
tarea 5.6 es el de `config/`. La etiqueta del incremento del hito 5, `app-v0.3.0`,
marca las páginas de la 5.5; los retoques del cierre del hito (5.8: la versión del
catálogo en la columna Modelo y una sola ayuda en Replay) llegaron después.

El alcance inicial está en la
[especificación de la fase 1](docs/specs/fase-1.md#objetivo-y-alcance-de-la-fase-1)
y los cambios posteriores, en la [especificación de incrementos](docs/specs/incrementos.md).

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
| Ejecutar | Ejecuciones | Ver el modelo de cada ejecución y la huella de los perfiles, elegir una, marcar A/B, descargarla y borrarla con confirmación. La columna Modelo distingue «Provisional», «Clínico · hito 4 (v3)» y «Clínico · hito 5 (v4)» por la versión del catálogo de su log. |
| Ejecutar | Simular | Elegir el fichero de perfiles y ver su resumen; partir del centro base, del cumplidor o de una variante; editar turnos, plantilla y boxes y, según el centro, la probabilidad de ingreso (solo un centro del hito 4, con `[destino]`) o la espera de cama (un centro del hito 5, con `[camas]`); guardar una variante, prever la carga (aún no con el hito 5, #103) y simular. |
| Analizar | Resultados | Consultar KPIs, los tres relojes, Manchester desde la clasificación con la censura del abandono, pretriaje, nivel 1 con mediana y p90, reparto observado, ocupación, censo, Little e invariantes; con el hito 5, el desenlace (abandono, destinos, espera de cama con sus cotas «≥», estancia por destino, boxes bloqueados y pasillo). El interruptor «Ver la verdad», antes de las descargas, añade el cumplimiento y el abandono por nivel real; sin él, la página no enseña nada del ground truth. |
| Analizar | Episodios | Filtrar por perfil y, con el hito 5, por abandono, cama y pasillo; seguir el recorrido y la sala de resultados; consultar gravedad, nivel real, calidad del triaje y el desenlace sorteado (paciencia, destino contrafactual, espera de cama) con «Ver la verdad». |
| Analizar | Comparar | Contrastar A y B con el tipo de emparejamiento: plantilla, clínico o sin emparejar; ver las diferencias de los perfiles clave a clave y, cuando estén emparejadas, paciente a paciente. Un hito 4 frente a un hito 5 queda sin emparejar: la tabla de bloqueos lo explica con la fila «Versión del catálogo». |
| Analizar | Replay | Reconstruir el servicio en el plano, con edad y motivo en la ficha y colores por nivel asignado; con el hito 5, los ingresados esperando cama, el pasillo y los que se van sin ser vistos, aparte de las salidas. |

La ejecución seleccionada se comparte entre páginas y aparece en `?run=…`.
Cada página incluye «¿Qué estoy viendo?» con los conceptos de su vista.

Con el abandono, el cumplimiento Manchester no quita a quien se va: si se va con su
reloj C (desde la clasificación) en su máximo o por encima, incumple; si se va antes,
no cuenta (está censurado). Ejemplo con tres pacientes de nivel 4 (máximo 120 min)
clasificados en el minuto 10: el primero ve al médico en el 40 (C = 30), el segundo
en el 100 (C = 90) y el tercero se va en el 160 (C = 150). El cumplimiento es 2 de 3,
el 66,7 %; quitar al tercero daría un 100 %.

## Primeros pasos con el hito 5

Un recorrido corto por lo que trae el modelo del hito 5:

1. **Simular.** Con el origen «Centro base» (`config/centro.toml`) y los perfiles de
   `config/perfiles.toml`, pulsa «Simular» y después «Ver resultados». En Ejecuciones,
   la nueva sale como «Clínico · hito 5 (v4)».
2. **Resultados.** Baja a «Desenlace: abandono, destinos y espera de cama»: el abandono
   antes y después del triaje, los cuatro destinos, la espera de cama con sus cotas «≥»
   y los boxes ocupados por ingresados.
3. **Episodios.** En «Filtros», «Se va sin ser visto» = Sí; elige uno en «Episodio».
   La ficha dice desde dónde se fue y cuándo. Activa «Ver la verdad»: su paciencia
   sorteada y el destino que habría tenido (el contrafactual); lo que ya no alcanzó
   sale como «no usada».
4. **Replay.** Desde la ficha, «Ver en el replay» abre el plano a la hora de su
   llegada, con el episodio resaltado. Avanza hasta la hora a la que se fue (la de la
   ficha): durante la hora siguiente aparece entre los que se van sin ser vistos,
   contados aparte de las salidas.

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

`config/perfiles.toml` contiene los perfiles clínicos por defecto; desde la tarea
5.6, con `config/centro.toml`, son el modelo del hito 5 (abandono, destinos y espera
de cama editable en Simular). Desde Simular puedes elegir otra ruta. Una ejecución clínica guarda una copia de sus perfiles
y su huella para poder reproducirla.

Desde la tarea 5.6, el centro base y el cumplidor tienen 36 boxes: los 30 del hito 4,
que se calibró sin boxes ocupados por ingresados, más los que ocupa de media la espera
de cama por la ley de Little (λ·W = 6,44 con la semilla de ajuste), redondeado. El
modelo del hito 4 se simula con sus copias congeladas (`tests/data/centro_h4.toml` y
`tests/data/perfiles_h4.toml`), que siguen con 30.

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
La selección de tests `slow` se explica en [AGENTS.md](AGENTS.md#selección-de-tests-slow).

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
