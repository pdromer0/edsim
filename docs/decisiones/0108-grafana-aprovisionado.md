# 0108. Grafana 13.3.1 aprovisionado desde el repositorio, con el perfil `analitica`

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

Un cuadro de mando hecho a mano vive solo en esa pantalla: no se revisa en un PR, el CI no lo comprueba y se pierde al borrar un volumen ([pieza 6](../specs/hito-8.md#pieza-6--grafana-y-el-aprovisionamiento)).

## Decisión

- `grafana/grafana:13.3.1` (OSS) en `compose.yaml`, con el perfil `analitica` y en `127.0.0.1:3000`.
- Aprovisionado desde `grafana/`: dos fuentes («Hospital» y «Laboratorio», cada una con su rol) y tres cuadros (Urgencias, Calidad del dato y Laboratorio).
- Sin volumen (su estado es el repositorio) y con acceso anónimo de solo lectura.

## Alternativas consideradas

- **Metabase:** preguntas de usuarios no técnicos, con licencia AGPL.
- **Superset:** BI para equipos técnicos, más pesado.
- **Streamlit:** es la app del laboratorio (decisión 97).
- **Power BI o Tableau:** propietarios.

## Consecuencias

- Los cuadros son revisables y comprobables en el CI.
- La integración que no usa Grafana no lo arranca.

## Qué cambió al implementarla

- **8.6** (#154, `134c6b3`): **sin red al arrancar.** Además de `GF_PLUGINS_PREINSTALL_AUTO_UPDATE: "false"`, hace falta `GF_PLUGINS_PREINSTALL_DISABLED: "true"`: sin volumen, cada `up` es un arranque, y Grafana intentaba instalar desde grafana.com sus apps por defecto. Con las dos variables, no hay ningún acceso a grafana.com.
- **8.6:** `tests-integracion.sh` exporta `COMPOSE_PROFILES=analitica`, y el test de arranque comprueba también la versión del plugin de PostgreSQL (13.0.7).
- **8.6, la revisión** (`b3ecfe2`): **Grafana no es una frontera de permisos.** Cualquier visitante anónimo puede abrir Laboratorio y consultar su fuente, que lee la verdad. Los dos roles separan lo que lee cada cuadro, pero no esconden la verdad a quien usa Grafana. Se acepta en un laboratorio local en `127.0.0.1`, y la especificación lo dice en «Los cuadros».
- **8.6:** la imagen son 506 MB de descarga (2,02 GB en disco), y Grafana ocupa de 280 a 488 MiB.
