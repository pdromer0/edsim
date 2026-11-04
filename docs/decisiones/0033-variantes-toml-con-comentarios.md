# 0033. Variantes TOML con comentarios

- **Estado:** Aceptada
- **Fecha:** 2026-11-04

## Contexto

Los comentarios de `centro.toml` explican cada parámetro. El editor necesita
guardar valores en bruto sin perder esas explicaciones ni confundirlos con los
valores normalizados del modelo. La escritura pertenece al núcleo para que no
dependa de Streamlit ([anexo A.3a](../../app/docs/specs/fase-1.md#tarea-a3a-núcleo-de-simular)).

## Decisión

`write_variant` usa tomlkit para modificar solo los valores que cambian y conserva
la representación de los demás. Las variantes experimentales se guardan en
`resultados/variantes/`; `config/` contiene lo que se conserva y versiona a mano.

## Alternativas consideradas

- Reasignar todas las claves al escribir: aunque sus valores sean iguales,
  cambia representaciones como `0.70`. La versión incorrecta perdió esa igualdad
  de bytes, incluidos los casos de saltos de línea y final sin salto.
- Comprobar si existe el destino y después publicar con `os.replace`: deja una
  carrera en la que se sobrescribe un fichero ajeno sin autorización.
- Publicar directamente el temporal de `mkstemp`: transmite sus permisos 0600;
  darle extensión `.toml` también lo hace visible como variante antes de acabar.

Estas alternativas se probaron en A.3a y sus fallos constan en
[PR #32](https://github.com/pdromer0/edsim/pull/32).

## Consecuencias

- tomlkit pasa a ser dependencia del núcleo; tomllib sigue leyendo. Sin cambios,
  se devuelven los bytes originales. `center_diff` compara centros normalizados,
  mientras el editor conserva los valores en bruto
  ([PR #32](https://github.com/pdromer0/edsim/pull/32)).
- La publicación sin sobrescritura usa `os.link`, que falla si ya existe el
  destino. La sobrescritura explícita usa `os.replace`. Se escribe un temporal
  oculto sin extensión `.toml`, se le dan permisos normales observados sin tocar
  la umask global y se limpia con `finally`
  ([PR #32](https://github.com/pdromer0/edsim/pull/32)).
- La plantilla de escritura es la variante de origen, para conservar también
  sus comentarios propios; la app cancela una confirmación de sobrescritura si
  cambian valores, nombre u origen
  ([PR #33](https://github.com/pdromer0/edsim/pull/33)).
- Una variante que merezca conservarse exige copiarla y versionarla a mano en
  `config/`. Los experimentos quedan fuera de los ficheros versionados
  ([formato de ejecución](../../app/docs/specs/fase-1.md#una-ejecución-en-disco)).
