# 0110. `lanzar` y `reemitir` publican lo registrado realista por defecto

- **Estado:** Aceptada
- **Fecha:** 2026-11-16

## Contexto

En el hito 7, `edsim directo lanzar` y `reemitir` publicaban la verdad salvo que se pidiera `--registro`. Con Grafana enseñando lo que dbt construye desde bronce, un olvido llenaría «Urgencias» con la verdad, que ningún hospital ve ([el directo por defecto](../specs/hito-8.md#especificación-el-directo-por-defecto)).

## Decisión

- `lanzar` y `reemitir` publican lo registrado con el perfil realista por defecto.
- La verdad, con `--verdad`, que no admite `--registro`, `--semilla-registro` ni `--registros`.

## Alternativas consideradas

- **Dejar la verdad por defecto:** el valor por defecto del hito 6 y el 7, pero el olvido cuesta caro ahora que hay un cuadro de mando.
- **Exigir siempre `--registro` o `--verdad`:** obliga a escribir lo que casi siempre se quiere.

## Consecuencias

- Las huellas de los hitos 3 a 7 no cambian: el paquete sigue recibiendo el perfil explícito.
- Los tests y los notebooks que publicaban la verdad pasan a llevar `--verdad`.

## Qué cambió al implementarla

- **8.2** (#150, `19b85f2`):
  - **solo cambia `src/edsim/cli.py`**: `prepare_live`, `with_recording` y `prepare_replay` siguen recibiendo el perfil explícito;
  - `--registro` conserva `default=None` para distinguir «no escrito» de «`realista` escrito», y la cabecera avisa «perfil realista (por defecto; la verdad, con --verdad)»;
  - un `--run-id` de más de 49 caracteres falla con el valor por defecto, porque el `run_id` derivado pasa de 64, y el mensaje apunta a `--verdad`.
- **8.2, la revisión** (`d9b5bde`): `reemitir` también sugiere `--verdad` si el `run_id` derivado no cabe.
- **8.2, lo que cuesta:** el arranque de `lanzar` calcula todo el registro, unos 2 s más con 14 días (5,7 s con `--verdad` y 7,7 s por defecto). `--semilla-registro` sin `--registro` ya no es un error.
- **8.2** (`69ea91a`): en el notebook 06, `--verdad` solo en el modo normal, que se leyó a mano.
