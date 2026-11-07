# 0032. Ejecuciones en carpetas reproducibles

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

La app necesita un catálogo que sobreviva al cierre de la sesión y permita
reproducir lo simulado. La CLI escribía resultados en una carpeta reutilizable,
sin archivar las configuraciones ni los metadatos del catálogo. Ambas entradas
necesitan el mismo contrato de persistencia
([anexo A.2a](../../app/docs/specs/fase-1.md#tarea-a2a-núcleo-de-ejecuciones)).

## Decisión

Una ejecución es una carpeta `resultados/ejecuciones/<run_id>/` con el log, los
dos CSV de ground truth, las copias exactas de los dos TOML y `run.json`.
La CLI y la app la escriben mediante `edsim.runs.simulate_run`, que prepara una
carpeta temporal oculta junto al destino y la publica al terminar.
Los ficheros son la fuente de verdad, sin base de datos ni catálogo persistente
separado.

## Alternativas consideradas

- Conservar la escritura directa en una carpeta reutilizable: puede dejar
  resultados parciales visibles y mezclar una ejecución nueva con la anterior.
- Leer las configuraciones originales durante la simulación y copiarlas después:
  una modificación entre lecturas separaría lo simulado de lo archivado. El test
  que cambia el original tras la copia detectó esa versión incorrecta
  ([PR #30](https://github.com/pdromer0/edsim/pull/30)).
- Mezclar metadatos y análisis transitorio en `RunInfo`: exigiría campos opcionales
  según de dónde proceda el objeto. `RunInfo` representa siempre `run.json`;
  `SimulationResult` añade análisis y violaciones de la operación recién hecha
  ([PR #30](https://github.com/pdromer0/edsim/pull/30)).

## Consecuencias

- Se copian primero los TOML byte a byte, se simula desde esas copias y se
  calculan sus huellas. Con los mismos parámetros y `run_id`, volver a simular
  desde ellas reproduce el log; los CSV conservan las cadenas de ruta originales
  como procedencia ([PR #30](https://github.com/pdromer0/edsim/pull/30)).
- `run.json`, con formato versionado, se escribe el último. Se rechazan destinos
  ocupados y el `run_id` se valida donde se convierte en ruta. El catálogo ignora
  los temporales; un `finally` limpia ante errores y `KeyboardInterrupt`. Una
  terminación forzada puede dejar un temporal oculto. Las ejecuciones con
  violaciones se conservan para diagnóstico ([PR #30](https://github.com/pdromer0/edsim/pull/30)).
- La revisión descubrió que `mkdtemp` transmitía permisos 0700 a la carpeta
  publicada. Se toman los permisos de un `mkdir` normal sin cambiar la umask
  global ([PR #30](https://github.com/pdromer0/edsim/pull/30)).
- Se mantiene el límite de 60 días y el valor inicial de 14. En A.2a, 60 días
  produjeron un log de 81,4 MB: mediana de 12,4 s para el servicio de simulación
  y 3,82 s para lectura más análisis. Son medidas del núcleo, no del navegador;
  el PR detalla entorno y muestras ([PR #30](https://github.com/pdromer0/edsim/pull/30)).
- Las cachés de la app suponen artefactos inmutables después de publicarse:
  borrar y recrear una ejecución cambia la huella de `run.json`, pero editar
  externamente solo su log no invalida resultados ya cacheados
  ([PR #35](https://github.com/pdromer0/edsim/pull/35)).

## Nota de actualización (2026-11-07)

Desde la tarea 4.5b, `run.json` está en la versión 2 del formato: la versión 1 más `model` (`"provisional"` o `"clinico"`) y, solo con el modelo clínico, `clinical_profiles_path` y `clinical_profiles_fingerprint`. Una ejecución clínica guarda además la copia de `perfiles.toml`, carga los perfiles desde ella y calcula su huella sobre ella ([especificación del hito 4, «Ejecuciones clínicas en disco»](../specs/hito-4.md#ejecuciones-clínicas-en-disco)). Se escribe solo la versión 2; las ejecuciones de la versión 1 se siguen leyendo, como provisionales, y la lectura exige las claves exactas de cada versión. Desde la tarea 4.9, `config/centro.toml` no tiene el bloque provisional (`[triaje]`, `[duraciones]` y `[pruebas]`; [ADR 0036](0036-perfiles-clinicos-aparte-del-centro.md)): las copias de `centro.toml` de las ejecuciones guardadas se leen como antes, y una ejecución provisional nueva necesita un centro con el bloque. La decisión no cambia.
