# APP-0001. Interfaz Streamlit sin API

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

La primera interfaz sirve para explorar ejecuciones batch en el portátil, con un
solo usuario. El motor todavía no tiene el modo directo que necesitará control
en vivo. La estrategia incremental está en
[0031](../../../docs/decisiones/0031-app-web-incremental.md); el alcance funcional,
en la [especificación](../specs/fase-1.md#objetivo-y-alcance-de-la-fase-1).

## Decisión

Streamlit presenta y recoge datos llamando directamente a la superficie pública
de `edsim`, sin API intermedia. La simulación, los cálculos y la persistencia
permanecen en el núcleo; la API de FastAPI se abordará con el modo directo del
hito 6.

## Alternativas consideradas

- API y frontend propio desde esta fase: añaden un stack antes de disponer de
  algo en vivo que controlar ([estrategia](../specs/fase-1.md#decisión-y-estrategia)).
- Mantener `st.cache_data` para el análisis: `RunAnalysis` contiene `mappingproxy`,
  que pickle no serializa, y reconstruir el objeto en cada recarga añade coste.
  Se eligió compartirlo con `st.cache_resource`
  ([PR #35](https://github.com/pdromer0/edsim/pull/35)).
- Reejecutar la página completa al abrir una ficha: con 60 días, serializar el
  `Styler` de Episodios dominaba la recarga. La selección y la ficha pasaron a un
  fragmento ([PR #36](https://github.com/pdromer0/edsim/pull/36)).

## Consecuencias

- La navegación usa `st.navigation` y módulos en `views/`: `pages/` activaba
  también la navegación antigua y Replay podía saltarse el punto de entrada.
  La selección duradera se separa del estado de widgets y se restaura en la URL
  ([PR #31](https://github.com/pdromer0/edsim/pull/31)).
- La carga prevista usa `cache_data`; los resultados e índices, `cache_resource`.
  Estos últimos se comparten y deben tratarse como de solo lectura. Su identidad
  incluye catálogo, identificador y huella de `run.json`; las cachés grandes se
  limitan a cuatro entradas
  ([PR #33](https://github.com/pdromer0/edsim/pull/33),
  [#35](https://github.com/pdromer0/edsim/pull/35),
  [#38](https://github.com/pdromer0/edsim/pull/38)).
- Los fragmentos evitan reconstruir tablas o detalles en interacciones parciales.
  En Episodios, seleccionar una ficha de 60 días bajó a 0,06 s de mediana; cambiar
  filtros sigue costando unos 2 s. El índice independiente evitó empeorar el
  lector de Resultados por encima del umbral acordado
  ([anexo A.5](../specs/fase-1.md#tarea-a5-página-episodios)).
- Replay consulta como mucho una hora de eventos por fotograma, pero su primera
  entrada lee y valida el log para resultados e índice por separado. Con 60 días
  fueron 11,16 s en frío; los máximos de fotograma medidos fueron 28,0 ms con
  14 días y 16,2 ms con 60 días, por debajo de 200 ms. Son medidas con AppTest y
  peticiones parciales, sin pintado del navegador
  ([PR #38](https://github.com/pdromer0/edsim/pull/38)).
- AppTest no pulsa filas de `st.dataframe`; se usa un selector. Su navegación y
  reejecución no reproducen siempre el navegador: las pruebas restauran el
  contexto necesario y `FragmentRunner` prueba peticiones parciales reales.
  El adaptador depende de detalles internos de Streamlit y habrá que revisarlo
  al actualizarlo. La presentación visual sigue requiriendo revisión en el
  navegador ([PR #31](https://github.com/pdromer0/edsim/pull/31),
  [#34](https://github.com/pdromer0/edsim/pull/34),
  [#36](https://github.com/pdromer0/edsim/pull/36),
  [#38](https://github.com/pdromer0/edsim/pull/38)).
