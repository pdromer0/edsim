# Registro de calibración

Cada cambio de un parámetro calibrado, con su valor de antes y de después, el KPI que lo
decide, el motivo y el comando que reproduce cada tabla (regla 1 de la calibración,
[docs/specs/hito-4.md](../specs/hito-4.md), «Calibración»). Los CSV que escriben los
comandos van a `resultados/`, que no se sube.

## Tarea 4.6b: enfermería de triaje y médicos (6 de noviembre de 2026)

Rama `feat/h4-calibracion`. Modelo clínico con `config/llegadas.toml`,
`config/perfiles.toml` y `config/objetivos.toml`; boxes (30), duraciones y
`espera_resultados_fuera` (`[4, 5]`) fijos.

> **Desde la tarea 4.6c**, la calibración usa la ventana anual y la plantilla de `config/`
> es otra (ver «Tarea 4.6c» abajo). Las tablas de esta sección se reproducen con
> `--ventana inicio` y el centro de entonces, fijado en `tests/data/centro_4_6b.toml`, por
> ejemplo `uv run edsim calibracion evaluar --ventana inicio --centro
> tests/data/centro_4_6b.toml`. El cumplidor de entonces ([15, 15, 6]) sale igual con la
> regla de días enteros de la 4.6c (12 de 120 días fuera en los niveles 4 y 5, justo el
> 10 %).

### Cambios

| Parámetro | Antes | Después | KPI | Motivo |
| --- | --- | --- | --- | --- |
| `recursos.enfermeria_triaje` | [3, 3, 2] | [3, 2, 1] (u de 0,795 a 0,8325) | Pretriaje medio, niveles 2 a 5: 1,37 → 10,65 min (horquilla 6–15; SAS 12,4) | Con [3, 3, 2] el pretriaje quedaba muy por debajo de la horquilla; [3, 2, 1] es la única plantilla de la regla que la cumple |
| `recursos.medicos` | [12, 12, 7] | [12, 11, 5] (u de 0,81 a 0,8475) | Reloj A, niveles 2 a 5: 25,0 → 54,5 min (horquilla 35–70) | Con la enfermería ya fija, la que pasa y queda más cerca del centro de la horquilla (52,5), porque el objetivo no tiene referencia única |
| `objetivos.tiempo_medico_nivel_3.uso` | ajuste | comprobación | Reloj A del nivel 3: como mucho 22,9 min con cualquier plantilla de la regla (horquilla 45–75) | Discrepancia estructural (ver «El nivel 3, de ajuste a comprobación»); el cambio se decidió después de medir la sensibilidad |
| Centro cumplidor (`config/centro_cumplidor.toml`) | — | médicos [15, 15, 6] (u de 0,625 a 0,635) | Días fuera de Manchester con el reloj C, niveles 2 a 5: 0,8 / 0 / 10,0 / 10,0 % | El u más alto con todos los niveles 2 a 5 a un máximo del 10 % de días fuera, de media entre réplicas |

### Método

- **Regla de la plantilla equivalente.** Personal del turno = ⌈carga del turno / u⌉, con
  un u por mando. Carga de enfermería = llegadas por hora × (1 − p₁) × media del triaje
  / 60 (p₁ = 0,40 %, media 5,79 min); carga de médicos = llegadas por hora × 32,37 min /
  60. Llegadas por hora del día medio: 17,36 / 16,5 / 6,3 (turnos de 8, 15 y 22 h).
  Cargas: enfermería 1,668 / 1,585 / 0,605; médicos 9,365 / 8,903 / 3,399. Con u de 0,55
  a 0,99 en pasos de 0,0025 salen 5 plantillas de enfermería y 20 de médicos.
- **Réplicas.** 10 réplicas con números aleatorios comunes (el hijo i de la semilla es
  la réplica i para todas las plantillas), 14 días con 2 de calentamiento.
- **Día de vaciado.** Cada réplica simula un día más, con llegadas (horizonte de 15
  días), y solo se mide a los llegados en la ventana [2, 14). Así, los que llegan al
  final de la ventana y más esperan no quedan fuera de las medias. Los llegados en la
  ventana sin salida al final del horizonte (censurados) se cuentan por réplica: 0 en
  todas las plantillas que pasan, como mucho un 0,23 % hasta u = 0,935, y un 1,9 % y un
  8,6 % en las dos de médicos más apretadas.
- **Regla 4.** Un objetivo pasa si la media entre réplicas cae dentro de la horquilla y
  la anchura de su IC al 95 % (t de Student, t₉ = 2,262) no supera la de la horquilla.
- **Semillas.** Ajuste con 2026; comprobación con 2027, sin reajustar.
- **Orden (decisión 41 revisada).** Primero la enfermería contra el pretriaje; con ella
  fija, los médicos contra el reloj A.

### Sensibilidad de la enfermería (médicos [12, 12, 7])

`git show 341ec2f:config/centro.toml > centro_antes.toml` y
`uv run edsim calibracion sensibilidad --mando enfermeria_triaje --centro centro_antes.toml`
(5 min 44 s, en paralelo con otras seis ejecuciones). ✓ pasa, ✗ no pasa. Medias entre
réplicas, en minutos o en %.

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [4, 3, 2] | 0,5500–0,5550 | 0,78 ✗ | 24,35 ✗ | 9,74 ✗ | 8,29 ✗ | 4,75 ✗ | 0,00 % |
| [3, 3, 2] | 0,5575–0,6050 | 1,37 ✗ | 24,99 ✗ | 10,29 ✗ | 9,02 ✗ | 9,34 ✗ | 0,00 % |
| [3, 3, 1] | 0,6075–0,7925 | 5,04 ✗ | 26,65 ✗ | 13,53 ✗ | 10,54 ✓ | 20,51 ✗ | 0,00 % |
| [3, 2, 1] **(elegida)** | 0,7950–0,8325 | 10,65 ✓ | 28,73 ✗ | 18,99 ✗ | 12,67 ✓ | 39,98 ✓ | 0,00 % |
| [2, 2, 1] | 0,8350–0,9900 | 26,83 ✗ | 40,40 ✓ | 35,00 ✗ | 19,76 ✓ | 67,51 ✗ | 0,00 % |

La enfermería mueve el pretriaje y, a través de él, el reloj A; los médicos de esta
tabla no cambian. Con el centro calibrado,
`uv run edsim calibracion sensibilidad --mando enfermeria_triaje` (3 min 32 s) da la
misma columna de pretriaje, bit a bit: el pretriaje no depende de los médicos mientras
no haya censurados.

Frente a un anticipo independiente (una cola de triaje sola, 8 semanas, 5 réplicas:
1,3 / 4,4 / 10,4 / 19,8 min con [3, 3, 2], [3, 3, 1], [3, 2, 1] y [2, 2, 1]), el motor se
aparta un +5 %, +15 %, +2 % y +36 %. La última fila es la más cargada (dos enfermeras de
mañana con una carga de 1,67), y la ventana es de enero, cuyo factor mensual (1,10)
eleva la ocupación de 0,83 a 0,92: cerca de la saturación, la espera crece como
ρ/(1 − ρ).

### Sensibilidad de los médicos (enfermería [3, 3, 2])

`uv run edsim calibracion sensibilidad --mando medicos --centro centro_antes.toml`
(15 min 20 s, en paralelo).

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) | Días fuera de Manchester (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500–0,5500 | 1,37 ✗ | 13,00 ✗ | 8,58 ✗ | 4,70 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 6,7 |
| [17, 17, 7] | 0,5525–0,5550 | 1,37 ✗ | 13,04 ✗ | 8,58 ✗ | 4,69 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 6,7 |
| [17, 16, 7] (cumplidor) | 0,5575–0,5650 | 1,37 ✗ | 13,18 ✗ | 8,60 ✗ | 4,72 ✗ | 9,34 ✗ | 0,00 % | 0,0 / 0,0 / 4,2 / 7,5 |
| [17, 16, 6] | 0,5675–0,5850 | 1,37 ✗ | 16,94 ✗ | 9,72 ✗ | 6,41 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [16, 16, 6] | 0,5875–0,5925 | 1,37 ✗ | 17,00 ✗ | 9,74 ✗ | 6,42 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [16, 15, 6] | 0,5950–0,6225 | 1,37 ✗ | 17,38 ✗ | 9,81 ✗ | 6,49 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [15, 15, 6] | 0,6250–0,6350 | 1,37 ✗ | 17,60 ✗ | 9,88 ✗ | 6,61 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 0,8 / 10,0 / 13,3 |
| [15, 14, 6] | 0,6375–0,6675 | 1,37 ✗ | 18,24 ✗ | 9,98 ✗ | 6,82 ✗ | 9,34 ✗ | 0,00 % | 1,7 / 1,7 / 12,5 / 14,2 |
| [14, 14, 6] | 0,6700–0,6775 | 1,37 ✗ | 18,82 ✗ | 10,10 ✗ | 6,88 ✗ | 9,34 ✗ | 0,00 % | 2,5 / 1,7 / 11,7 / 14,2 |
| [14, 14, 5] | 0,6800–0,6825 | 1,37 ✗ | 26,73 ✗ | 12,63 ✗ | 10,71 ✓ | 9,34 ✗ | 0,00 % | 11,7 / 3,3 / 43,3 / 29,2 |
| [14, 13, 5] | 0,6850–0,7200 | 1,37 ✗ | 28,45 ✗ | 12,91 ✗ | 11,21 ✓ | 9,34 ✗ | 0,00 % | 11,7 / 5,0 / 45,0 / 30,0 |
| [13, 13, 5] | 0,7225–0,7400 | 1,37 ✗ | 30,21 ✗ | 13,16 ✗ | 11,73 ✓ | 9,34 ✗ | 0,00 % | 12,5 / 4,2 / 47,5 / 31,7 |
| [13, 12, 5] | 0,7425–0,7800 | 1,37 ✗ | 34,81 ✗ | 13,67 ✗ | 13,09 ✓ | 9,34 ✗ | 0,00 % | 16,7 / 5,8 / 50,0 / 35,0 |
| [12, 12, 5] | 0,7825–0,8075 | 1,37 ✗ | 40,76 ✓ | 14,20 ✗ | 14,95 ✓ | 9,34 ✗ | 0,00 % | 19,2 / 5,8 / 52,5 / 38,3 |
| [12, 11, 5] **(elegida)** | 0,8100–0,8475 | 1,37 ✗ | 52,83 ✓ | 15,05 ✗ | 17,76 ✓ | 9,34 ✗ | 0,00 % | 20,8 / 8,3 / 60,0 / 50,0 |
| [12, 11, 4] | 0,8500–0,8500 | 1,37 ✗ | 84,86 ✗ | 21,55 ✗ | 26,00 ✓ | 9,34 ✗ | 0,15 % | 45,8 / 24,2 / 86,7 / 65,0 |
| [11, 11, 4] | 0,8525–0,8900 | 1,37 ✗ | 135,53 ✗ | 22,97 ✗ | 33,84 ✗ | 9,33 ✗ | 0,23 % | 55,8 / 22,5 / 89,2 / 73,3 |
| [11, 10, 4] | 0,8925–0,9350 | 1,37 ✗ | 253,92 ✗ | 25,43 ✗ | 44,88 ✗ | 9,33 ✗ | 0,23 % | 68,3 / 28,3 / 95,8 / 87,5 |
| [10, 10, 4] | 0,9375–0,9875 | 1,37 ✗ | 541,66 ✗ | 26,82 ✗ | 57,84 ✗ | 9,35 ✗ | 1,92 % | 83,3 / 31,7 / 99,2 / — |
| [10, 9, 4] | 0,9900–0,9900 | 1,38 ✗ | 998,20 ✗ | 29,72 ✗ | 62,53 ✗ | 9,37 ✗ | 8,61 % | 87,5 / 37,5 / 100,0 / — |

Los médicos no mueven el pretriaje (1,37 en todas las filas sin censurados). Con la
enfermería de antes, ninguna plantilla pasa los objetivos de ajuste: hacía falta mover
primero la enfermería.

### Ajuste de los médicos (enfermería [3, 2, 1])

`uv run edsim calibracion sensibilidad --mando medicos` con el centro calibrado (15 min 20
s, en paralelo): la plantilla de médicos del centro no cuenta, porque cada fila la
sustituye, así que reproduce esta tabla.

| Plantilla | u | Pretriaje | A 2–5 | A nivel 3 | % sobre Manchester (A) | % pretriaje > 5 | Censurados (máx.) | Días fuera de Manchester (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500–0,5500 | 10,65 ✓ | 19,61 ✗ | 17,52 ✗ | 9,66 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 3,3 |
| [17, 17, 7] | 0,5525–0,5550 | 10,65 ✓ | 19,64 ✗ | 17,53 ✗ | 9,66 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 3,3 |
| [17, 16, 7] | 0,5575–0,5650 | 10,65 ✓ | 19,73 ✗ | 17,54 ✗ | 9,69 ✗ | 39,98 ✓ | 0,00 % | 0,0 / 0,0 / 2,5 / 4,2 |
| [17, 16, 6] | 0,5675–0,5850 | 10,65 ✓ | 23,05 ✗ | 18,44 ✗ | 11,10 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 7,5 / 9,2 |
| [16, 16, 6] | 0,5875–0,5925 | 10,65 ✓ | 23,13 ✗ | 18,47 ✗ | 11,13 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 7,5 / 9,2 |
| [16, 15, 6] | 0,5950–0,6225 | 10,65 ✓ | 23,34 ✗ | 18,49 ✗ | 11,19 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,0 / 10,0 |
| [15, 15, 6] (cumplidor) | 0,6250–0,6350 | 10,65 ✓ | 23,54 ✗ | 18,57 ✗ | 11,30 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,0 / 10,0 |
| [15, 14, 6] | 0,6375–0,6675 | 10,65 ✓ | 23,95 ✗ | 18,63 ✗ | 11,36 ✓ | 39,98 ✓ | 0,00 % | 1,7 / 0,0 / 10,8 / 10,0 |
| [14, 14, 6] | 0,6700–0,6775 | 10,65 ✓ | 24,46 ✗ | 18,77 ✗ | 11,47 ✓ | 39,98 ✓ | 0,00 % | 0,8 / 0,0 / 10,8 / 10,0 |
| [14, 14, 5] | 0,6800–0,6825 | 10,65 ✓ | 32,62 ✗ | 20,97 ✗ | 15,04 ✓ | 39,98 ✓ | 0,00 % | 10,0 / 3,3 / 36,7 / 27,5 |
| [14, 13, 5] | 0,6850–0,7200 | 10,65 ✓ | 33,70 ✗ | 21,17 ✗ | 15,34 ✓ | 39,98 ✓ | 0,00 % | 13,3 / 2,5 / 37,5 / 26,7 |
| [13, 13, 5] | 0,7225–0,7400 | 10,65 ✓ | 35,04 ✓ | 21,46 ✗ | 15,66 ✓ | 39,98 ✓ | 0,00 % | 11,7 / 2,5 / 40,0 / 29,2 |
| [13, 12, 5] | 0,7425–0,7800 | 10,65 ✓ | 38,65 ✓ | 21,85 ✗ | 16,64 ✓ | 39,98 ✓ | 0,00 % | 16,7 / 3,3 / 40,8 / 33,3 |
| [12, 12, 5] | 0,7825–0,8075 | 10,65 ✓ | 43,79 ✓ | 22,25 ✗ | 18,08 ✓ | 39,98 ✓ | 0,00 % | 16,7 / 2,5 / 45,0 / 35,8 |
| [12, 11, 5] **(elegida)** | 0,8100–0,8475 | 10,65 ✓ | 54,51 ✓ | 22,91 ✗ | 21,08 ✓ | 39,98 ✓ | 0,00 % | 17,5 / 2,5 / 52,5 / 43,3 |
| [12, 11, 4] | 0,8500–0,8500 | 10,64 ✓ | 88,44 ✗ | 29,22 ✗ | 29,16 ✓ | 39,96 ✓ | 0,20 % | 46,7 / 22,5 / 86,7 / 63,3 |
| [11, 11, 4] | 0,8525–0,8900 | 10,64 ✓ | 136,82 ✗ | 30,35 ✗ | 37,04 ✗ | 39,96 ✓ | 0,23 % | 54,2 / 25,0 / 88,3 / 73,3 |
| [11, 10, 4] | 0,8925–0,9350 | 10,64 ✓ | 253,07 ✗ | 32,45 ✗ | 47,67 ✗ | 39,96 ✓ | 0,23 % | 65,0 / 25,0 / 94,2 / 86,7 |
| [10, 10, 4] | 0,9375–0,9875 | 10,65 ✓ | 534,32 ✗ | 33,85 ✗ | 60,70 ✗ | 39,98 ✓ | 1,78 % | 83,3 / 27,5 / 99,2 / — |
| [10, 9, 4] | 0,9900–0,9900 | 10,77 ✓ | 994,18 ✗ | 36,85 ✗ | 65,24 ✗ | 39,94 ✓ | 8,07 % | 86,7 / 30,8 / 100,0 / — |

Pasan el reloj A de los niveles 2 a 5 las plantillas de [13, 13, 5] a [12, 11, 5]; la
elegida es la más cercana a 52,5 (54,5, a 2,0). Con un médico menos de noche
([12, 11, 4]) el reloj A salta a 88 min: la noche, con 4 médicos y una carga de 3,4
(más en enero), se acerca a la saturación.

### El nivel 3, de ajuste a comprobación

Ninguna plantilla de la regla lleva el reloj A del nivel 3 por encima de 22,9 min, y los
dos objetivos del reloj A no se pueden cumplir a la vez: cuando los niveles 2 a 5 suben
hasta su horquilla, el nivel 3 sigue en 22–23 min. Es una discrepancia estructural: con
prioridad estricta en un solo grupo de médicos, el nivel 3 casi no espera box ni médico
(reloj C de 4,4 min en el centro calibrado) y las esperas recaen en los niveles 4 y 5.
En los hospitales reales, los niveles 4 y 5 suelen tener circuito propio (consultas o vía
rápida) y el nivel 3 compite con el 2. Por eso `tiempo_medico_nivel_3` pasó a
comprobación el 6 de noviembre de 2026, después de medir la sensibilidad (regla 5) y no
antes, con la nota en `config/objetivos.toml`. Una comprobación no decide el ajuste:
los médicos se eligen solo con los niveles 2 a 5. Calibrar el nivel 3 pide circuitos
separados para los niveles 4 y 5 (ver «Para versiones posteriores» de la especificación).

### Ajuste (2026) y comprobación (2027) del centro calibrado

`uv run edsim calibracion evaluar` y `uv run edsim calibracion evaluar --semilla 2027`
(1 min 50 s cada una, en paralelo; 48 s sola).

| Objetivo | Uso | Horquilla | ajuste-2026: media [IC 95 %], días fuera | comprobacion-2027: media [IC 95 %], días fuera |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 10,65 [8,92; 12,37], 39,2 % ✓ | 11,99 [9,71; 14,26], 43,3 % ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 54,51 [46,95; 62,07], 69,2 % ✓ | 49,91 [41,91; 57,92], 63,3 % ✓ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 22,91 [20,69; 25,13], 97,5 % ✗ | 24,21 [21,05; 27,37], 93,3 % ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 21,08 [18,52; 23,65], 40,0 % ✓ | 19,97 [17,25; 22,70], 28,3 % ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 39,98 [38,03; 41,92], 30,8 % ✓ | 39,36 [36,81; 41,91], 24,2 % ✓ |

Con la semilla de comprobación, los dos objetivos de ajuste siguen dentro y la
comprobación del porcentaje sobre Manchester y del pretriaje de más de 5 minutos también;
solo falla el nivel 3, por la discrepancia de arriba. Sin censurados en ninguna réplica.

**Porcentaje sobre Manchester (reloj A) por nivel.** El nivel 2 tiene un máximo de 10 min
y el pretriaje y el triaje ya suman más: queda por encima en más de la mitad de sus
pacientes. La contribución es la parte de la cifra global que aporta cada nivel.

| Nivel | ajuste-2026: % del nivel / contribución | comprobacion-2027: % del nivel / contribución |
| --- | --- | --- |
| 2 | 57,4 % / 7,46 puntos | 56,7 % / 7,53 puntos |
| 3 | 8,3 % / 2,82 puntos | 9,2 % / 3,15 puntos |
| 4 | 20,4 % / 10,47 puntos | 17,5 % / 8,97 puntos |
| 5 | 23,9 % / 0,33 puntos | 24,4 % / 0,33 puntos |

### Centro cumplidor

`uv run edsim calibracion evaluar --centro config/centro_cumplidor.toml` (y con
`--semilla 2027`). No es un centro calibrado: el reloj A de los niveles 2 a 5 queda por
debajo de la horquilla, como se espera de un centro que cumple Manchester.

| Objetivo | Uso | Horquilla | cumplidor-2026: media [IC 95 %], días fuera | cumplidor-2027: media [IC 95 %], días fuera |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 10,65 [8,92; 12,37], 39,2 % ✓ | 11,99 [9,71; 14,26], 43,3 % ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 23,54 [20,71; 26,37], 88,3 % ✗ | 24,32 [21,39; 27,24], 89,2 % ✗ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 18,57 [16,60; 20,54], 99,2 % ✗ | 19,77 [17,21; 22,33], 95,8 % ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 11,30 [9,57; 13,03], 55,0 % ✓ | 11,31 [10,02; 12,59], 58,3 % ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 39,98 [38,03; 41,92], 30,8 % ✓ | 39,36 [36,81; 41,91], 24,2 % ✓ |

| Nivel | cumplidor-2026: % del nivel / contribución | cumplidor-2027: % del nivel / contribución |
| --- | --- | --- |
| 2 | 49,8 % / 6,48 puntos | 48,8 % / 6,49 puntos |
| 3 | 6,0 % / 2,06 puntos | 6,5 % / 2,25 puntos |
| 4 | 5,2 % / 2,69 puntos | 4,9 % / 2,50 puntos |
| 5 | 5,2 % / 0,08 puntos | 4,9 % / 0,07 puntos |

### Fila reproducible

`uv run edsim calibracion evaluar --replicas 3 --dias 5 --calentamiento 1` con el centro
calibrado (8,6 s; código 1, porque con 3 réplicas el IC de los niveles 2 a 5 es más ancho
que la horquilla). Medias: pretriaje 10,94; reloj A de los niveles 2 a 5, 94,56; nivel
3, 24,58; sobre Manchester, 29,98 %; pretriaje de más de 5 minutos, 41,78 %; sin
censurados. El test slow `test_reproduce_la_fila_corta_del_registro` la comprueba.

### Observaciones

- **El pretriaje de noche.** En el centro calibrado (una ejecución, semilla 2026), el
  pretriaje de la noche es de 18,6 min de media, con p90 de 58,9, con una sola enfermera.
  La regla reparte con la carga media del turno (0,605), pero las primeras horas de la
  noche tienen casi la carga de la tarde: a las 22 h llegan 12,6 pacientes por hora (una
  carga de enfermería de 1,21, más de lo que una enfermera puede absorber) y a las 23 h,
  10,2 (0,98), frente a 16,5 de media de la tarde. La cola se forma entre las 22 y las
  24 h y no se vacía hasta las 3 h: los llegados a las 0 h esperan 35,3 min de media
  (p90 79,8), y los de las 4 h, 4,5. Una regla por horas, o un turno de noche partido,
  lo evitaría; queda fuera de esta tarea, que no amplía la regla.
- **Las esperas de los niveles 4 y 5.** Con prioridad estricta, cargan con las colas:
  reloj A de 57,7 y 107,3 min en el centro calibrado, y cumplimiento Manchester con el
  reloj C del 86 % y el 83 %, con 6 días fuera de 12 en cada uno. Es el centro «realista»
  de la decisión 41, que incumple a veces.
- **Sin colas que crezcan de un día a otro.** A las 8:00, la cola de box solo tiene
  pacientes el primer día después del calentamiento (14); el resto de días está vacía.

### El reloj A según el horizonte (tarea 4.7, revisión del PR #49)

El reloj A de los niveles 2 a 5 del centro calibrado parecía crecer con el horizonte: 54,5
min en la calibración (10 réplicas, días 2 a 13), 57,1 en la sección 9 del notebook 04 (5
réplicas), 73,5 en una ejecución de 28 días de la sección 12 y, en el nivel 5, de 107 min
a 229 en la ejecución de 91 días. Se midió si era sesgo de inicialización (cada réplica
empieza vacía) o acumulación en días malos, sin tocar la calibración ni `config/`. Todo con
las funciones del paquete (`clinical_run`, `replica_values`, `step_curves` y
`summarize`); el script está en la descripción del PR #49.

**(a) Ejecución principal del notebook 04: 91 días, semilla 2026, centro calibrado.** Por semana de calendario (lunes a domingo; la primera, sin los 2 días de calentamiento). Medias por paciente llegado en la semana; censo y cola de box a las 8:00, media de los días de la semana (y máximo de la cola).

| Semana | Días | Reloj A, niveles 2 a 5 | Reloj A, nivel 4 | Reloj A, nivel 5 (pacientes) | Espera de box, nivel 5 | Censo a las 8:00 | Cola de box a las 8:00 (máx.) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 7/1–11/1 | 41,7 | 59,4 | 71,7 (22) | 31,7 | 20,6 | 2,8 (14) |
| 2 | 12/1–18/1 | 38,6 | 56,5 | 131,8 (32) | 49,5 | 11,0 | 0,0 (0) |
| 3 | 19/1–25/1 | 131,8 | 183,3 | 984,5 (46) | 1060,3 | 43,1 | 14,3 (51) |
| 4 | 26/1–1/2 | 62,8 | 86,8 | 284,9 (33) | 227,2 | 25,0 | 4,1 (29) |
| 5 | 2/2–8/2 | 34,7 | 44,0 | 83,3 (35) | 15,2 | 13,0 | 0,0 (0) |
| 6 | 9/2–15/2 | 36,4 | 50,9 | 130,6 (32) | 45,0 | 15,0 | 0,0 (0) |
| 7 | 16/2–22/2 | 50,5 | 69,1 | 57,0 (31) | 23,1 | 22,1 | 3,9 (27) |
| 8 | 23/2–1/3 | 37,3 | 52,6 | 73,7 (29) | 14,6 | 16,1 | 0,4 (3) |
| 9 | 2/3–8/3 | 32,5 | 42,4 | 70,0 (31) | 14,2 | 11,6 | 0,0 (0) |
| 10 | 9/3–15/3 | 28,7 | 36,8 | 95,4 (34) | 38,7 | 11,4 | 0,0 (0) |
| 11 | 16/3–22/3 | 46,7 | 68,5 | 189,6 (35) | 123,8 | 19,1 | 1,4 (10) |
| 12 | 23/3–29/3 | 47,2 | 61,4 | 306,2 (35) | 291,5 | 17,1 | 3,7 (26) |
| 13 | 30/3–5/4 | 35,7 | 49,0 | 84,0 (25) | 51,5 | 12,3 | 0,0 (0) |
| Total | 7/1–5/4 | 49,3 | | 229,4 | | | |

**(b) 5 semillas × 56 días, centro calibrado, `config/llegadas.toml`.** Semillas: los hijos 0 a 4 de `child_streams(2026, 5)`, las 5 primeras réplicas de la calibración; 2 días de calentamiento y uno de vaciado; sin censurados. Media entre semillas e IC al 95 % (t₄ = 2,776).

| Bloque (días medidos) | Fechas | Reloj A, niveles 2 a 5 | Reloj A, nivel 5 | Por semilla (niveles 2 a 5) |
| --- | --- | --- | --- | --- |
| 2–13 | 7/1–18/1 | 57,1 [46,2; 68,0] | 236,4 [189,9; 282,9] | 65,4 / 49,4 / 58,4 / 46,9 / 65,7 |
| 14–27 | 19/1–1/2 | 61,8 [33,9; 89,7] | 265,1 [45,9; 484,3] | 67,9 / 53,5 / 97,3 / 52,3 / 38,1 |
| 28–41 | 2/2–15/2 | 34,3 [30,2; 38,3] | 87,7 [69,9; 105,5] | 34,5 / 33,5 / 35,4 / 38,5 / 29,5 |
| 42–55 | 16/2–1/3 | 43,4 [26,1; 60,8] | 189,3 [18,4; 360,1] | 40,6 / 31,9 / 38,4 / 67,7 / 38,6 |

**(c) Lo mismo con el factor mensual neutro** (todos los meses a 1, con `dataclasses.replace` en memoria; la media de los doce factores reales es 1,0008). Semillas: los hijos 0 a 4 de `child_streams(2026, 5)`, las 5 primeras réplicas de la calibración; 2 días de calentamiento y uno de vaciado; sin censurados. Media entre semillas e IC al 95 % (t₄ = 2,776).

| Bloque (días medidos) | Fechas | Reloj A, niveles 2 a 5 | Reloj A, nivel 5 | Por semilla (niveles 2 a 5) |
| --- | --- | --- | --- | --- |
| 2–13 | 7/1–18/1 | 28,3 [25,6; 30,9] | 56,7 [41,8; 71,5] | 26,6 / 31,2 / 28,2 / 29,3 / 25,9 |
| 14–27 | 19/1–1/2 | 33,9 [23,1; 44,7] | 129,2 [67,7; 190,8] | 35,3 / 45,0 / 36,6 / 31,3 / 21,1 |
| 28–41 | 2/2–15/2 | 28,4 [21,7; 35,1] | 75,1 [36,7; 113,6] | 21,8 / 28,0 / 27,3 / 36,9 / 27,8 |
| 42–55 | 16/2–1/3 | 26,8 [22,2; 31,4] | 58,8 [35,4; 82,2] | 26,3 / 21,8 / 31,4 / 25,2 / 29,4 |

**Conclusión.** No es sesgo de inicialización: con el factor mensual neutro, los cuatro
bloques de 14 días quedan entre 26,8 y 33,9 min y el primero (28,3) no queda por debajo de
los demás, así que los 2 días de calentamiento bastan; la primera semana medida (días 2 a
6) da 25,2 min frente a 26,3–35,1 de las siguientes, dentro del ruido. Lo que mueve las
cifras es el mes (con los factores reales, enero da 57,1 y 61,8 min y febrero, 34,3 y 43,4)
y la acumulación en días malos: en la semilla 2026, del 19 al 22 de enero llegan cuatro
días seguidos más pacientes de lo esperado (efecto diario de 1,03 a 1,18; 390, 369, 404 y
363 llegadas frente a unas 320), la cola de box de la noche pasa al día siguiente (19, 51,
15 y 15 pacientes a las 8:00) y no se vacía hasta el viernes 23. Esa semana sola da 131,8
min de reloj A a los niveles 2 a 5 y 985 al nivel 5, el 47 % de los minutos de espera del
nivel 5 en los 89 días (sin ella, 137 min).

**Resuelto en la tarea 4.6c.** La ventana de la calibración pasa a cubrir el año: una
réplica por mes, desde el primer lunes de cada mes. Con ella, el centro de la 4.6b da 27,75
min de reloj A (fuera de 35–70 por abajo) y la plantilla se recalibra: médicos [12, 11, 4]
(ver «Tarea 4.6c»).

## Tarea 4.6c: recalibración con la ventana anual (6 de noviembre de 2026)

Rama `feat/h4-recalibracion-anual`. Mismo modelo clínico, mismos `config/llegadas.toml`,
`config/perfiles.toml` y `config/objetivos.toml`, boxes, duraciones y
`espera_resultados_fuera` que en la 4.6b. Solo cambian la ventana de la calibración, la
regla del cumplidor (días enteros) y la de elección (veto de la semilla de comprobación).

### Cambios

| Parámetro | Antes (4.6b) | Después (4.6c) | KPI | Motivo |
| --- | --- | --- | --- | --- |
| Ventana de la calibración | 10 réplicas, todas desde el 5/1/2026 (primera quincena de enero) | 12 réplicas, la m desde el primer lunes del mes m+1 | Reloj A de los niveles 2 a 5 del centro de la 4.6b: 54,51 → 27,75 min | Los objetivos del SAS son medias anuales; enero es el mes de más carga (factor 1,10) |
| `recursos.enfermeria_triaje` | [3, 2, 1] | [3, 2, 1] (u de 0,795 a 0,8325) | Pretriaje medio: 6,78 min [5,49; 8,06] (horquilla 6–15; SAS 12,4) | La regla elige [2, 2, 1] (13,21), pero la semilla 2027 la veta (15,16) y se toma la siguiente |
| `recursos.medicos` | [12, 11, 5] | [12, 11, 4] (u de 0,85) | Reloj A, niveles 2 a 5: 27,75 → 42,10 min [28,02; 56,18] (horquilla 35–70) | La única plantilla de la regla que pasa con la ventana anual |
| Centro cumplidor (`config/centro_cumplidor.toml`) | médicos [15, 15, 6] | médicos [14, 14, 6] (u de 0,67 a 0,6775) | Días fuera de Manchester con el reloj C, niveles 2 a 5: 1/144, 0/144, 2/144, 6/142 | El u más alto con como mucho un 10 % de días fuera, con los días sumados |
| Regla del cumplidor | media de los % de días fuera por réplica ≤ 10 % | días fuera sumados ≤ 10 % de los días medidos sumados, con enteros | — | Exacta, sin decimales; ver «Método» |
| Regla de elección (decisión 41) | la semilla 2027 solo comprueba | la semilla 2027 puede vetar, no elegir; después de un veto, la comprobación independiente es 2028 | — | Ver «El veto de la semilla 2027» |

### Método

- **Ventana anual.** 12 réplicas: la m (m = 0…11) empieza a las 00:00 del primer lunes
  del mes m+1 del año de `fecha_inicio` (en 2026: 5/1, 2/2, 2/3, 6/4, 4/5, 1/6, 6/7, 3/8,
  7/9, 5/10, 2/11 y 7/12) y usa el hijo m de `child_streams(semilla, 12)`. Cada réplica
  tiene el factor mensual, los días de la semana y el contexto clínico (mes y estación)
  de su mes. Igual que antes: 14 días con 2 de calentamiento, un día de vaciado, la
  ventana [2, 14) y números aleatorios comunes entre candidatos. La réplica de enero es,
  bit a bit, la réplica 0 de la 4.6b (test slow `test_la_replica_de_enero_reproduce_la_replica_0_de_la_ventana_de_la_4_6b`).
  Las cargas de la regla son las del día medio y no dependen de la fecha: las plantillas
  candidatas no cambian.
- **Regla 4.** Igual, con t₁₁ = 2,201. El IC entre réplicas incluye la variación entre
  meses, así que es conservador: la regla pide que la media del año caiga en la horquilla
  y que los meses no se separen más que su anchura.
- **Media por paciente del año.** `edsim calibracion evaluar` informa también de la media
  de todos los pacientes de las 12 réplicas, que pondera cada mes por sus pacientes. No
  decide: la regla 4 usa la media entre réplicas. La diferencia es pequeña (reloj A de los
  niveles 2 a 5 del centro elegido: 42,10 entre réplicas y 42,99 por paciente).
- **Cumplidor con días enteros.** Pasa si en cada nivel de 2 a 5 los días fuera de
  Manchester con el reloj C, sumados en las réplicas, no superan el 10 % de los días con
  pacientes de ese nivel, también sumados: fuera × 10 ≤ medidos, con enteros. Con 12
  réplicas de 12 días medidos (144), pasan 14 días fuera y no 15. **Cambia la definición**
  cuando las réplicas tienen distinto número de días con pacientes de un nivel (el nivel 5,
  con 1,4 % de los pacientes, tiene días sin ninguno): antes, una réplica con 6 días
  medidos pesaba lo mismo que una con 12; ahora pesa cada día. Con `--ventana inicio` y la
  semilla 2026, la regla con enteros sigue eligiendo [15, 15, 6], como en la 4.6b: 12 de
  120 días fuera en los niveles 4 y 5, justo el 10 %, pasa; [15, 14, 6] tiene 13 de 120 en
  el nivel 4 y no pasa (`uv run edsim calibracion sensibilidad --mando medicos --ventana
  inicio`, 11 min 36 s).
- **Veto de la semilla de comprobación (decisión 41, revisada).** La semilla de
  comprobación puede vetar, no elegir: si la plantilla elegida con 2026 falla un objetivo
  de ajuste con 2027 (regla 4), se descarta y se toma la siguiente candidata de la regla
  de elección (la siguiente más cercana a la referencia o al centro de la horquilla) que
  pase los objetivos de ajuste con 2026 y con 2027. Si ninguna pasa con las dos, no se
  elige. Como 2027 ha intervenido en la elección, la comprobación independiente pasa a la
  semilla 2028. En el paquete, `choose_staffing(filas, mando, check=…)`; en la CLI,
  `calibracion sensibilidad --comprobacion 2027`, que evalúa con 2027, con la misma ventana
  y el resto de opciones, solo las candidatas que hagan falta, en el orden de la elección
  (revisión del PR #50).
- **Orden.** Como en la 4.6b: la enfermería contra el pretriaje, con los médicos del
  centro; con ella fija, los médicos contra el reloj A.

### El centro de la 4.6b con la ventana anual

`uv run edsim calibracion evaluar --centro tests/data/centro_4_6b.toml` (36 s). Con la
carga del año, el reloj A de los niveles 2 a 5 queda por debajo de la horquilla.

| Objetivo | Uso | Horquilla | Media [IC 95 %] | Por paciente |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 6,87 |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 27,75 [19,12; 36,38] ✗ | 28,31 |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 15,65 [13,87; 17,44] ✗ | 15,80 |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 11,16 [8,05; 14,28] ✓ | 11,37 |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,39 [28,47; 34,30] ✓ | 31,58 |

Por mes, el reloj A de los niveles 2 a 5 va de 65,39 en enero a 16,58 en agosto (ver
«Enero con una plantilla anual»). Sin censurados.

### Sensibilidad de la enfermería (médicos [12, 11, 5])

`uv run edsim calibracion sensibilidad --mando enfermeria_triaje` (3 min 13 s) y lo mismo
con `--semilla 2027` (2 min 14 s). La enfermería no cambia el reloj de los médicos de forma
apreciable, ni los médicos el pretriaje: con los médicos de la 4.6b o con [12, 11, 4], el
pretriaje es el mismo salvo por los pacientes censurados, que no se miden (13,21 y 13,20
con [2, 2, 1]). La tabla de 2027 se ejecutó con el `config/` final (médicos [12, 11, 4]).

| Plantilla | u | 2026: pretriaje medio [IC 95 %] | 2026: % pretriaje > 5 min | 2027: pretriaje medio [IC 95 %] | 2027: % pretriaje > 5 min |
| --- | --- | --- | --- | --- | --- |
| [4, 3, 2] | 0,5500–0,5550 | 0,60 [0,52; 0,67] ✗ | 3,72 | 0,60 [0,52; 0,68] ✗ | 3,62 |
| [3, 3, 2] | 0,5575–0,6050 | 0,95 [0,82; 1,08] ✗ | 6,22 | 1,03 [0,85; 1,21] ✗ | 6,81 |
| [3, 3, 1] | 0,6075–0,7925 | 3,54 [2,85; 4,23] ✗ | 16,23 | 3,92 [3,30; 4,54] ✗ | 16,57 |
| [3, 2, 1] | 0,7950–0,8325 | 6,78 [5,49; 8,06] ✓ | 31,39 | 7,86 [6,31; 9,41] ✓ | 32,91 |
| [2, 2, 1] | 0,8350–0,9900 | 13,21 [8,98; 17,44] ✓ | 51,44 | 15,16 [10,61; 19,71] ✗ | 53,02 |

Sin censurados en ninguna. Con 2026 pasan [3, 2, 1] y [2, 2, 1], y la regla elige
[2, 2, 1], la más cercana a la referencia (12,4). Con 2027 [2, 2, 1] no pasa: el veto la
descarta y queda [3, 2, 1] (ver «El veto de la semilla 2027»). La tabla de 2027 es la
sensibilidad entera con `--semilla 2027`, que aplica la regla a esa semilla; la elección
con el veto la da `uv run edsim calibracion sensibilidad --mando enfermeria_triaje
--comprobacion 2027`, que con 2027 evalúa solo [2, 2, 1] (vetada) y [3, 2, 1] (elegida).

### Sensibilidad de los médicos (enfermería [3, 2, 1])

`uv run edsim calibracion sensibilidad --mando medicos` (15 min 37 s). Días fuera de
Manchester con el reloj C / días medidos, sumados en las 12 réplicas.

| Plantilla | u | Reloj A, niveles 2 a 5 [IC 95 %] | Nivel 3 | % sobre Manchester | Censurados (máx.) | Días fuera (C), niveles 2 / 3 / 4 / 5 |
| --- | --- | --- | --- | --- | --- | --- |
| [18, 17, 7] | 0,5500 | 13,65 [11,95; 15,36] ✗ | 12,90 | 5,79 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 17, 7] | 0,5525–0,5550 | 13,67 [11,95; 15,38] ✗ | 12,91 | 5,79 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 16, 7] | 0,5575–0,5650 | 13,68 [11,95; 15,40] ✗ | 12,91 | 5,80 | 0,00 % | 0/144 / 0/144 / 1/144 / 1/142 |
| [17, 16, 6] | 0,5675–0,5850 | 15,21 [13,27; 17,14] ✗ | 13,38 | 6,48 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [16, 16, 6] | 0,5875–0,5925 | 15,24 [13,28; 17,20] ✗ | 13,40 | 6,49 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [16, 15, 6] | 0,5950–0,6225 | 15,27 [13,28; 17,25] ✗ | 13,41 | 6,50 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [15, 15, 6] | 0,6250–0,6350 | 15,35 [13,32; 17,37] ✗ | 13,44 | 6,53 | 0,00 % | 1/144 / 0/144 / 2/144 / 5/142 |
| [15, 14, 6] | 0,6375–0,6675 | 15,43 [13,38; 17,48] ✗ | 13,47 | 6,53 | 0,00 % | 1/144 / 0/144 / 2/144 / 6/142 |
| [14, 14, 6] | 0,6700–0,6775 | 15,65 [13,48; 17,81] ✗ | 13,53 | 6,59 | 0,00 % | 1/144 / 0/144 / 2/144 / 6/142 |
| [14, 14, 5] | 0,6800–0,6825 | 20,41 [17,32; 23,49] ✗ | 14,70 | 9,07 | 0,00 % | 4/144 / 0/144 / 9/144 / 22/142 |
| [14, 13, 5] | 0,6850–0,7200 | 20,66 [17,50; 23,82] ✗ | 14,78 | 9,18 | 0,00 % | 4/144 / 0/144 / 10/144 / 22/142 |
| [13, 13, 5] | 0,7225–0,7400 | 21,16 [17,76; 24,55] ✗ | 14,92 | 9,27 | 0,00 % | 3/144 / 0/144 / 11/144 / 22/142 |
| [13, 12, 5] | 0,7425–0,7800 | 22,09 [18,25; 25,92] ✗ | 15,07 | 9,60 | 0,00 % | 5/144 / 0/144 / 15/144 / 28/142 |
| [12, 12, 5] | 0,7825–0,8075 | 23,89 [18,60; 29,19] ✗ | 15,31 | 10,16 | 0,00 % | 6/144 / 0/144 / 20/144 / 30/142 |
| [12, 11, 5] | 0,8100–0,8475 | 27,75 [19,12; 36,38] ✗ | 15,65 | 11,16 | 0,00 % | 6/144 / 0/144 / 28/144 / 32/142 |
| **[12, 11, 4]** | 0,8500 | 42,10 [28,02; 56,18] ✓ | 18,76 | 16,13 | 0,20 % | 28/144 / 7/144 / 88/144 / 54/142 |
| [11, 11, 4] | 0,8525–0,8900 | 50,23 [27,79; 72,66] ✗ | 19,35 | 18,03 | 0,23 % | 37/144 / 6/144 / 89/144 / 55/142 |
| [11, 10, 4] | 0,8925–0,9350 | 76,47 [24,53; 128,42] ✗ | 20,44 | 22,52 | 0,23 % | 55/144 / 11/144 / 95/144 / 67/142 |
| [10, 10, 4] | 0,9375–0,9875 | 129,66 [7,41; 251,90] ✗ | 21,56 | 27,90 | 1,12 % | 53/144 / 11/144 / 101/144 / 81/137 |
| [10, 9, 4] | 0,9900 | 240,52 [11,66; 469,37] ✗ | 23,31 | 34,49 | 7,31 % | 75/144 / 15/144 / 113/143 / 74/118 |

Solo pasa [12, 11, 4], con un único punto de la rejilla de u (0,85). [11, 11, 4] tiene la
media dentro (50,23), pero su IC (44,87 de ancho) es más ancho que la horquilla (35): los
meses se separan demasiado. Con 2027, [12, 11, 4] pasa (43,29): no hay veto de médicos.
Con la enfermería [2, 2, 1] (antes del veto) la sensibilidad de los médicos elegía también
[12, 11, 4] (48,69) y el cumplidor [14, 14, 6] (16 min 17 s).

### El veto de la semilla 2027

`uv run edsim calibracion evaluar --semilla 2027` con cada enfermería (24 s cada una). Los
dos objetivos de ajuste, con médicos [12, 11, 4]:

| Enfermería | Semilla | Pretriaje medio [IC 95 %] (6–15) | Reloj A, niveles 2 a 5 [IC 95 %] (35–70) | Censurados |
| --- | --- | --- | --- | --- |
| [2, 2, 1] | 2026 | 13,20 [8,99; 17,41] ✓ | 48,69 [31,80; 65,58] ✓ | 3, en enero (0,08 %) |
| [2, 2, 1] | 2027 | **15,16 [10,61; 19,71] ✗** | 50,07 [37,45; 62,69] ✓ | 0 |
| [3, 2, 1] | 2026 | 6,78 [5,49; 8,06] ✓ | 42,10 [28,02; 56,18] ✓ | 8, en enero (0,20 %) |
| [3, 2, 1] | 2027 | 7,86 [6,31; 9,41] ✓ | 43,29 [33,11; 53,47] ✓ | 0 |

Con 2027 el pretriaje de [2, 2, 1] sale de la horquilla por la media (15,16 > 15) y por el
IC (9,10 de ancho frente a 9). Con dos enfermeras de mañana el pretriaje depende de unos
pocos días de muchas llegadas: con 2027, la quincena de noviembre da 32,58 min y la de
enero 25,23. [3, 2, 1] queda cerca del borde inferior (6,78 y 7,86) y pasa con las dos.

### Ajuste (2026), comprobación (2027) y confirmación (2028) del centro calibrado

`uv run edsim calibracion evaluar`, con `--semilla 2027` y con `--semilla 2028` (24 s cada
una).

| Objetivo | Uso | Horquilla | ajuste-2026 | comprobacion-2027 | confirmacion-2028 |
| --- | --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 7,86 [6,31; 9,41] ✓ | 7,76 [6,48; 9,03] ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 42,10 [28,02; 56,18] ✓ | 43,29 [33,11; 53,47] ✓ | 41,20 [33,57; 48,84] ✓ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 18,76 [16,60; 20,93] ✗ | 20,13 [17,36; 22,90] ✗ | 20,60 [17,86; 23,34] ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 16,13 [12,33; 19,93] ✓ | 16,79 [13,31; 20,27] ✓ | 16,64 [13,95; 19,32] ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,38 [28,47; 34,28] ✓ | 32,91 [29,31; 36,50] ✓ | 32,36 [29,54; 35,17] ✓ |
| Censurados | | | 8, en enero (0,20 %) | 0 | 0 |

Media por paciente del año del reloj A de los niveles 2 a 5: 42,99, 43,87 y 41,57. Con las
tres semillas pasan los objetivos de ajuste y fallan solo el nivel 3, por la discrepancia
de la 4.6b.

| Nivel | % sobre Manchester: ajuste-2026, % del nivel / contribución | comprobacion-2027 |
| --- | --- | --- |
| 2 | 48,3 % / 5,86 puntos | 48,3 % / 5,92 puntos |
| 3 | 6,4 % / 2,13 puntos | 7,1 % / 2,40 puntos |
| 4 | 15,0 % / 7,89 puntos | 15,7 % / 8,22 puntos |
| 5 | 17,7 % / 0,24 puntos | 18,3 % / 0,25 puntos |

### Enero con una plantilla anual

La plantilla es la misma todo el año, y la regla 4 con la ventana anual pide que la media
del año caiga en la horquilla. Enero, el mes de más carga (factor mensual 1,10), queda cerca
de la saturación. Reloj A de los niveles 2 a 5 por mes (la quincena desde el primer lunes;
médicos [12, 11, 4] salvo la primera fila):

| Centro | Semilla | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4.6b: [3, 2, 1] + [12, 11, 5] | 2026 | 65,4 | 38,7 | 25,8 | 23,6 | 24,1 | 17,8 | 28,9 | 16,6 | 19,6 | 22,7 | 16,9 | 32,9 |
| **[3, 2, 1] + [12, 11, 4]** | 2026 | 105,2 | 58,7 | 36,9 | 37,8 | 36,6 | 28,5 | 41,2 | 24,6 | 28,4 | 34,4 | 25,0 | 47,8 |
| **[3, 2, 1] + [12, 11, 4]** | 2027 | 78,6 | 40,8 | 46,2 | 37,8 | 27,1 | 22,6 | 45,0 | 33,9 | 35,9 | 31,6 | 62,3 | 57,6 |
| **[3, 2, 1] + [12, 11, 4]** | 2028 | 60,5 | 65,2 | 35,7 | 37,5 | 39,3 | 33,9 | 32,7 | 31,7 | 39,6 | 33,8 | 29,7 | 54,9 |
| [2, 2, 1] + [12, 11, 4] | 2026 | 123,9 | 68,8 | 45,5 | 39,1 | 45,6 | 31,2 | 50,2 | 27,9 | 31,8 | 37,5 | 28,4 | 54,6 |
| [2, 2, 1] + [12, 11, 4] | 2027 | 93,7 | 44,9 | 52,9 | 41,9 | 31,0 | 29,0 | 50,1 | 37,1 | 40,8 | 35,5 | 79,0 | 65,0 |

Pretriaje medio por mes:

| Centro | Semilla | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **[3, 2, 1] + [12, 11, 4]** | 2026 | 10,3 | 10,2 | 8,1 | 5,9 | 7,2 | 5,5 | 7,1 | 4,4 | 4,7 | 5,4 | 4,9 | 7,6 |
| **[3, 2, 1] + [12, 11, 4]** | 2027 | 10,0 | 9,7 | 9,5 | 8,2 | 5,0 | 4,5 | 8,2 | 6,1 | 5,2 | 5,9 | 11,6 | 10,5 |
| [2, 2, 1] + [12, 11, 4] | 2026 | 30,0 | 19,9 | 15,0 | 7,6 | 15,6 | 8,8 | 13,2 | 7,7 | 7,9 | 9,6 | 8,3 | 14,7 |
| [2, 2, 1] + [12, 11, 4] | 2027 | 25,2 | 13,5 | 15,0 | 13,1 | 9,2 | 8,5 | 12,7 | 9,9 | 14,9 | 9,5 | 32,6 | 17,8 |

- **El salto de 5 a 4 médicos de noche.** La carga de médicos de la noche es de 3,399
  (día medio). Con 5 médicos, u nominal 0,68; con 4, 0,85, y con el factor de enero
  (1,10), 0,93. Con [12, 11, 5] el reloj A anual se queda en 27,75 (fuera por abajo); con
  [12, 11, 4] sube a 42,10, y en enero a 105,2. Entre las dos no hay plantilla de la
  regla: es el único paso que lleva el año dentro de la horquilla.
- **Censurados de enero.** Con 2026, 8 pacientes de enero (0,20 % de 3924) siguen dentro
  al final del día de vaciado; ninguno en otro mes ni con 2027 o 2028. El aviso de la CLI
  salta por encima del 0,1 % en una réplica.
- **El pretriaje de noche.** Mismo método que el 18,6 de la 4.6b (llegados de 22 a 8 h
  de los niveles 2 a 5 en la ventana [2, 14) de cada réplica, con los médicos de la 4.6b,
  que no mueven el pretriaje); el 18,6 (p90 58,9) se reproduce con una ejecución de la
  semilla 2026 desde `fecha_inicio`. Con la ventana anual y semilla 2026, [3, 2, 1] da 15,6
  min por paciente (p90 44,1; enero 23,8) y [2, 2, 1], 18,4 (p90 50,0; enero 38,7). Por
  turno, mañana / tarde / noche: 1,1 / 8,1 / 15,6 con [3, 2, 1] y 10,9 / 13,5 / 18,4 con
  [2, 2, 1]. La causa del empeoramiento con [2, 2, 1] es la cola de la mañana: con dos
  enfermeras (u nominal 0,83 en el día medio) el pretriaje de los llegados sube de 1,7 min
  a las 8 h a 16,7 a las 13 h (con [3, 2, 1], 0,3 y 1,3), y la cola pasa a la tarde y a
  la noche.
- **La ejecución principal del notebook 04** (91 días desde el 5 de enero, semilla 2026)
  cae en los meses de más carga: reloj A de los niveles 2 a 5 de 82,0 min y del nivel 5 de
  627 (con [12, 11, 5], 49,3 y 229). La semana del 19 al 25 de enero, con cuatro días
  seguidos de más llegadas, da 306 y 3897 min: a las 8:00 llega a haber 129 pacientes
  clasificados esperando médico (el 23) y la cola no se vacía hasta el 30. Sin censurados
  al final, y la semana siguiente vuelve a 84 min. Es el mismo efecto que en la tarea 4.7,
  más fuerte con un médico menos de noche. Los 3897 min (unas 65 horas) del nivel 5 en esa semana no son realistas: el modelo aún no tiene abandono sin ser visto (`patient_left_wbs`, hito 5), y en un hospital real buena parte de esos pacientes se iría. Lo acotan el abandono del hito 5 y el refuerzo de invierno.
- **Refuerzo de invierno, para versiones posteriores.** Con una plantilla anual, enero
  queda cerca de la saturación: reloj A de 105 min con 2026 y 8 censurados. Un refuerzo de
  invierno (por ejemplo, el quinto médico de noche solo en los meses de más carga) es
  para versiones posteriores: pide una plantilla por mes en el motor y en la regla, y
  medir con la ventana anual que el año sigue dentro de la horquilla. Esta tarea mantiene
  la misma plantilla todo el año.

### Centro cumplidor

`uv run edsim calibracion evaluar --centro config/centro_cumplidor.toml` (y con
`--semilla 2027`). No es un centro calibrado: el reloj A de los niveles 2 a 5 queda por
debajo de la horquilla, como se espera de un centro que cumple Manchester.

| Objetivo | Uso | Horquilla | cumplidor-2026 | cumplidor-2027 |
| --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,78 [5,49; 8,06] ✓ | 7,86 [6,31; 9,41] ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 15,65 [13,48; 17,81] ✗ | 17,46 [14,64; 20,29] ✗ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 13,53 [12,13; 14,93] ✗ | 14,54 [12,84; 16,24] ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 6,59 [5,42; 7,75] ✗ | 7,52 [6,09; 8,95] ✗ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 31,39 [28,47; 34,30] ✓ | 32,91 [29,31; 36,50] ✓ |

Sin censurados. Días fuera de Manchester con el reloj C, niveles 2 a 5, con 2026: 1/144,
0/144, 2/144 y 6/142, todos por debajo del 10 % (14 de 144). La siguiente de la regla,
[14, 14, 5], tiene 22/142 en el nivel 5 y no pasa. Porcentaje sobre Manchester por nivel
con 2026: 41,8 / 2,2 / 1,4 / 1,5 % (el nivel 2 sigue por encima por el pretriaje y el
triaje, como en la 4.6b).

### Fila reproducible

`uv run edsim calibracion evaluar --dias 5 --calentamiento 1` (12 réplicas de la ventana
anual; 13 s; código 1, porque con 5 días el IC de los niveles 2 a 5 es más ancho que la
horquilla). Medias: pretriaje 7,08; reloj A de los niveles 2 a 5, 58,58; nivel 3, 20,88;
sobre Manchester, 18,12 %; pretriaje de más de 5 minutos, 31,57 %; 1 censurado, en
septiembre. El test slow `test_reproduce_la_fila_corta_anual_del_registro` la comprueba;
`test_reproduce_la_fila_del_registro_del_centro`, `test_la_semilla_2027_veta_2_2_1_y_queda_3_2_1`,
`test_la_comprobacion_independiente_con_2028` y
`test_el_cumplidor_y_su_siguiente_con_dias_enteros` recalculan las tablas de arriba.

## Tarea 5.6: el abandono, la espera de cama y los boxes del hito 5 (12 de noviembre de 2026)

Rama `feat/h5-calibracion` (issue #73). El modelo del hito 5 (abandono, destinos y espera de
cama; [docs/specs/hito-5.md](../specs/hito-5.md), pieza 5) pasa a `config/` y se calibra en
el orden de H5-9, con la ventana anual, la regla 4 (t₁₁ = 2,201), la semilla 2026 para
elegir, la 2027 que puede vetar y la plantilla de la 4.6c fija mientras sus objetivos
pasen. Mismos `config/llegadas.toml` y duraciones. Los destinos (ingreso, traslado y
exitus) son los derivados de la tarea 5.2, sin simular. El `config/` del hito 4 queda
congelado, byte a byte, en `tests/data/*_h4.toml`, y el registro de la 4.6c se recalcula con
él.

### Cambios

| Parámetro | Antes | Después (5.6) | KPI | Motivo |
| --- | --- | --- | --- | --- |
| `camas.espera` (centro base y cumplidor) | [240, 720] de partida (antes, `[destino]` provisional) | [210, 630] | Estancia de los ingresados: ≥479,90 [466,95; 492,86] (horquilla 360–600; SAS 472,5) | La mediana de la rejilla más cercana a 472,5 de las que pasan, antes y después de la paciencia, sin veto |
| `abandono.paciencia` | [[1440, 4320], [480, 1440], [240, 720], [150, 450], [120, 360]] de partida | × 4: [[5760, 17280], [1920, 5760], [960, 2880], [600, 1800], [480, 1440]] | Abandono: 1,68 % [1,06; 2,30] (1–4 %; SAS 1,82) | El factor de la rejilla más cercano a 1,82 de los que pasan, sin veto; discrepancia estructural (ver «La paciencia: k = 4») |
| `recursos.boxes` (base y cumplidor) | 30 | 36 | Esperando cama, ley de Little: λ · W = 6,44 | Derivado, decisión de Pedro del 12 de noviembre: los 30 del hito 4 más λ · W redondeado (ver «Los boxes») |
| `recursos.enfermeria_triaje`, `recursos.medicos` | [3, 2, 1] y [12, 11, 4] | Sin cambios | Pretriaje 6,73 y reloj A de los niveles 2 a 5 35,31 (2026) | Sus objetivos pasan con el modelo nuevo (paso 3 de H5-9): sin vuelta |
| Cumplidor (`config/centro_cumplidor.toml`) | médicos [14, 14, 6] | [14, 14, 6] | Días fuera (C), niveles 2 a 5: 1/144, 0/144, 7/144, 11/142 | La regla de siempre da la misma plantilla |
| `config/objetivos.toml` | 5 objetivos | 10: `abandono` y `estancia_ingresados` (ajuste); `ingresados_mas_4h`, `estancia_atendidos` e `ingreso_observado` (comprobación) | — | Los objetivos del hito 5 (SAS, CMBD 2013, sin observación) |

### Método

- **Quién cuenta, con el abandono** (reglas de la 5.4, H5-8; sin abandono, todo da lo mismo
  bit a bit, y los slow de la 4.6c pasan a `rel=1e-12` con las copias del hito 4):
  - el pretriaje, de los triados que terminan en la ventana (también quien se va
    después del triaje);
  - las medias de los relojes, de los atendidos;
  - los porcentajes de los relojes, con la censura del cumplimiento: quien se va con su
    reloj en el umbral o por encima, por encima; antes, censurado;
  - la estancia, también de quien sigue dentro al final del vaciado, con su cota (`≥`);
  - el abandono y el ingreso observado, sobre todos los llegados a la ventana.
- **Censurado** es quien sigue dentro al final del día de vaciado, no quien no tiene
  salida (quien se va tampoco la tiene). El día de vaciado sigue siendo uno: con el
  centro calibrado, los ingresados que esperan cama al final no pasan del 0,62 % de una
  réplica (el aviso salta por encima del 1 %): 3 de 4154 en el año con 2026, que entran
  en la media de la estancia con su cota.
- **Los mandos** (`calibracion sensibilidad --mando espera_cama | paciencia`):
  - la cama: la mediana m con p90 = 3 · m y los factores de turno fijos, de 120 a 360 de
    15 en 15;
  - la paciencia: un factor k sobre las medianas y los p90 de partida (σ no cambia), en
    la rejilla 2^(i/4) de 1 a 8, con 3 decimales.
  - Los dos, con números aleatorios comunes y la elección y el veto de siempre.
- **Orden** (H5-9): la cama con la paciencia de partida, la paciencia, la cama otra vez;
  después, los objetivos del hito 4 con el modelo nuevo y el cumplidor.

### Con 30 boxes: la parada del cuello de botella

La cama con la paciencia de partida eligió m = 210 (477,57 con 2026 y 480,96 con 2027),
pero la paciencia no encontró ningún factor que pasara el abandono:

`uv run edsim calibracion sensibilidad --mando espera_cama --comprobacion 2027` (8 min 30 s)
con `config/` de partida:

| m (min) | estancia_ingresados | abandono | tiempo_medico_niveles_2_5 | Box / médico (2 a 5) | Ingr. esperando cama (máx.) |
| --- | --- | --- | --- | --- | --- |
| 120 | 334,92 [327,57; 342,26] ✗ | 6,21 ✗ | 21,60 ✗ | 3,7 / 6,6 | 0,00 % |
| 135 | ≥358,50 [350,17; 366,82] ✗ | 6,55 ✗ | 21,99 ✗ | 4,3 / 6,5 | 0,25 % |
| 150 | ≥382,18 [372,96; 391,39] ✓ | 6,97 ✗ | 22,68 ✗ | 5,0 / 6,5 | 0,25 % |
| 165 | ≥405,25 [395,35; 415,15] ✓ | 7,46 ✗ | 23,34 ✗ | 5,7 / 6,5 | 0,31 % |
| 180 | ≥429,51 [418,50; 440,51] ✓ | 8,14 ✗ | 24,13 ✗ | 6,6 / 6,4 | 0,31 % |
| 195 | ≥453,58 [441,47; 465,69] ✓ | 8,80 ✗ | 24,91 ✗ | 7,4 / 6,4 | 0,31 % |
| 210 | ≥477,57 [464,40; 490,75] ✓ | 9,45 ✗ | 25,62 ✗ | 8,2 / 6,3 | 0,63 % |
| 225 | ≥502,18 [487,98; 516,38] ✓ | 10,19 ✗ | 26,57 ✗ | 9,2 / 6,2 | 0,63 % |
| 240 | ≥526,96 [511,72; 542,20] ✓ | 10,95 ✗ | 27,47 ✗ | 10,1 / 6,3 | 0,63 % |
| 255 | ≥551,24 [534,55; 567,93] ✓ | 11,77 ✗ | 28,21 ✗ | 10,8 / 6,3 | 0,63 % |
| 270 | ≥575,52 [558,41; 592,63] ✓ | 12,51 ✗ | 28,88 ✗ | 11,6 / 6,2 | 0,63 % |
| 285 | ≥597,84 [579,99; 615,69] ✓ | 13,32 ✗ | 29,85 ✗ | 12,6 / 6,2 | 0,64 % |
| 300 | ≥622,14 [602,84; 641,44] ✗ | 14,16 ✗ | 30,83 ✗ | 13,8 / 6,1 | 0,65 % |
| 315 | ≥648,15 [626,47; 669,83] ✗ | 15,11 ✗ | 32,08 ✗ | 15,1 / 6,0 | 0,65 % |
| 330 | ≥671,68 [650,41; 692,96] ✗ | 15,95 ✗ | 33,09 ✗ | 16,1 / 6,0 | 0,66 % |
| 345 | ≥696,33 [674,31; 718,35] ✗ | 16,92 ✗ | 34,18 ✗ | 17,3 / 6,0 | 0,66 % |
| 360 | ≥721,20 [697,19; 745,20] ✗ | 18,13 ✗ | 35,71 ✓ | 18,9 / 5,9 | 0,94 % |

La paciencia con m = 210 (6 min 5 s; ningún k pasa, ni con 2026):

| k | abandono | tiempo_medico_niveles_2_5 | estancia_ingresados | Box / médico (2 a 5) | Ingr. esperando cama (máx.) |
| --- | --- | --- | --- | --- | --- |
| 1 | 9,45 [6,56; 12,35] ✗ | 25,62 ✗ | ≥477,57 ✓ | 8,2 / 6,3 | 0,63 % |
| 1,189 | 9,01 [6,07; 11,95] ✗ | 28,50 ✗ | ≥480,29 ✓ | 10,0 / 7,2 | 0,63 % |
| 1,414 | 8,48 [5,64; 11,31] ✗ | 31,47 ✗ | ≥482,13 ✓ | 11,8 / 8,2 | 0,63 % |
| 1,682 | 7,87 [5,00; 10,74] ✗ | 34,92 ✗ | ≥484,35 ✓ | 14,1 / 9,2 | 0,63 % |
| 2 | 7,44 [4,58; 10,30] ✗ | 38,79 ✓ | ≥487,00 ✓ | 16,7 / 10,4 | 0,63 % |
| 2,378 | 6,78 [4,07; 9,49] ✗ | 42,61 ✓ | ≥487,77 ✓ | 19,3 / 11,5 | 0,62 % |
| 2,828 | 6,19 [3,63; 8,74] ✗ | 47,35 ✓ | ≥489,04 ✓ | 23,0 / 12,4 | 0,62 % |
| 3,364 | 5,42 [3,01; 7,83] ✗ | 52,10 ✓ | ≥491,05 ✓ | 26,6 / 13,4 | 0,62 % |
| 4 | 4,77 [2,51; 7,04] ✗ | 57,13 ✓ | ≥493,87 ✓ | 30,8 / 14,2 | 0,62 % |
| 4,757 | 4,20 [2,10; 6,29] ✗ | 62,42 ✗ | ≥496,28 ✓ | 35,4 / 14,8 | 0,62 % |
| 5,657 | 3,70 [1,77; 5,64] ✗ | 67,69 ✗ | ≥498,55 ✓ | 40,2 / 15,3 | 0,62 % |
| 6,727 | 3,19 [1,41; 4,96] ✗ | 73,47 ✗ | ≥500,86 ✓ | 45,6 / 15,5 | 0,62 % |
| 8 | 2,71 [1,08; 4,33] ✗ | 80,69 ✗ | ≥503,64 ✓ | 52,4 / 15,9 | 0,62 % |

Con 30 boxes, la espera de cama ocupa unos 7 (ley de Little), y los demás se quedan con ~23:
la espera de box supera a la de médico (con k = 8, 52 frente a 16 min), y cuanto más
aguantan los pacientes, más cola de box y más abandono. Es la parada del cuello de botella
de la especificación. Con 37 boxes (30 + 7), medido sin tocar `config/`, k = 3,364 daba 1,99 %
y la espera de box bajaba a 5,4 frente a 14,7.

### Los boxes

Decisión de Pedro del 12 de noviembre de 2026: los boxes pasan a ser un **derivado**, los 30
del hito 4, que se calibró sin boxes ocupados por ingresados, más los que ocupa de media la
espera de cama, por la ley de Little (L = λ · W = Σ esperas / minutos de la ventana),
redondeado al entero más cercano y recalculado con la cama y la paciencia elegidas. Con 37,
λ · W salió 6,44, así que la regla da **36**; se rehízo el orden con 36, y con la cama y la
paciencia finales λ · W es otra vez 6,44 con 2026: 36 es estable con la semilla de ajuste,
que es la que usa la regla. Con la de comprobación, 2027, λ · W = 6,56 daría 37 (30 + 6,56 =
36,56). Las copias
del hito 4 de `tests/data` se quedan en 30. `calibracion evaluar` da la medida en la línea
«Esperando cama (ley de Little …)»; por las curvas de la ejecución, 6,50 (de 4,91 a 8,00 por
réplica).

### Con 36 boxes: la cama, la paciencia y la cama otra vez

La cama con la paciencia de partida (`--centro` con 36 boxes; 8 min 40 s): m = 210 (470,75 con
2026 y 473,32 con 2027).

| m (min) | estancia_ingresados | abandono | tiempo_medico_niveles_2_5 | Box / médico (2 a 5) | Ingr. esperando cama (máx.) |
| --- | --- | --- | --- | --- | --- |
| 120 | 333,27 [326,34; 340,19] ✗ | 5,04 ✗ | 19,64 ✗ | 0,9 / 7,5 | 0,00 % |
| 135 | ≥356,22 [348,67; 363,76] ✗ | 5,05 ✗ | 19,63 ✗ | 1,0 / 7,4 | 0,25 % |
| 150 | ≥379,63 [371,52; 387,73] ✓ | 5,08 ✗ | 19,68 ✗ | 1,1 / 7,3 | 0,25 % |
| 165 | ≥402,30 [393,52; 411,09] ✓ | 5,14 ✗ | 19,82 ✗ | 1,3 / 7,3 | 0,31 % |
| 180 | ≥424,88 [415,65; 434,11] ✓ | 5,26 ✗ | 19,91 ✗ | 1,5 / 7,2 | 0,31 % |
| 195 | ≥447,54 [437,43; 457,65] ✓ | 5,36 ✗ | 20,10 ✗ | 1,8 / 7,1 | 0,31 % |
| 210 | ≥470,75 [459,86; 481,65] ✓ | 5,49 ✗ | 20,33 ✗ | 2,1 / 7,0 | 0,63 % |
| 225 | ≥493,51 [481,90; 505,12] ✓ | 5,65 ✗ | 20,55 ✗ | 2,4 / 6,9 | 0,63 % |
| 240 | ≥516,94 [504,40; 529,48] ✓ | 5,86 ✗ | 20,81 ✗ | 2,7 / 6,9 | 0,63 % |
| 255 | ≥539,69 [526,53; 552,85] ✓ | 6,08 ✗ | 21,11 ✗ | 3,0 / 6,9 | 0,63 % |
| 270 | ≥563,45 [549,29; 577,61] ✓ | 6,32 ✗ | 21,43 ✗ | 3,4 / 6,8 | 0,63 % |
| 285 | ≥587,27 [571,77; 602,77] ✓ | 6,54 ✗ | 21,67 ✗ | 3,7 / 6,8 | 0,63 % |
| 300 | ≥609,86 [593,85; 625,86] ✗ | 6,82 ✗ | 22,08 ✗ | 4,2 / 6,7 | 0,63 % |
| 315 | ≥634,12 [617,03; 651,20] ✗ | 7,17 ✗ | 22,45 ✗ | 4,6 / 6,7 | 0,63 % |
| 330 | ≥657,34 [639,32; 675,37] ✗ | 7,43 ✗ | 22,76 ✗ | 5,0 / 6,5 | 0,63 % |
| 345 | ≥680,28 [661,50; 699,05] ✗ | 7,83 ✗ | 23,35 ✗ | 5,6 / 6,6 | 0,63 % |
| 360 | ≥703,47 [683,48; 723,47] ✗ | 8,22 ✗ | 23,79 ✗ | 6,2 / 6,5 | 0,94 % |

La paciencia con m = 210 (6 min 42 s): k = 4 (1,68 % con 2026 y 2,00 % [1,24; 2,76] con 2027),
el más cercano a 1,82; k = 3,364 da 2,13 %.

| k | abandono | tiempo_medico_niveles_2_5 | estancia_ingresados | pretriaje_medio | Box / médico (2 a 5) | Ingr. esperando cama (máx.) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 5,49 [4,27; 6,70] ✗ | 20,33 ✗ | ≥470,75 ✓ | 6,03 ✓ | 2,1 / 7,0 | 0,63 % |
| 1,189 | 4,97 [3,81; 6,13] ✗ | 21,90 ✗ | ≥472,84 ✓ | 6,21 ✓ | 2,5 / 8,0 | 0,63 % |
| 1,414 | 4,48 [3,33; 5,63] ✗ | 23,67 ✗ | ≥473,96 ✓ | 6,38 ✓ | 3,1 / 9,0 | 0,62 % |
| 1,682 | 4,01 [2,93; 5,09] ✗ | 25,52 ✗ | ≥475,46 ✓ | 6,51 ✓ | 3,7 / 10,0 | 0,62 % |
| 2 | 3,52 [2,53; 4,51] ✓ | 27,31 ✗ | ≥476,39 ✓ | 6,59 ✓ | 4,4 / 11,1 | 0,62 % |
| 2,378 | 3,03 [2,11; 3,94] ✓ | 29,30 ✗ | ≥477,21 ✓ | 6,63 ✓ | 5,2 / 12,1 | 0,62 % |
| 2,828 | 2,60 [1,78; 3,42] ✓ | 31,27 ✗ | ≥478,39 ✓ | 6,68 ✓ | 6,0 / 13,1 | 0,62 % |
| 3,364 | 2,13 [1,39; 2,88] ✓ | 33,21 ✗ | ≥479,44 ✓ | 6,71 ✓ | 6,7 / 14,3 | 0,62 % |
| 4 | 1,68 [1,06; 2,30] ✓ | 35,31 ✓ | ≥479,90 ✓ | 6,73 ✓ | 7,6 / 15,5 | 0,62 % |
| 4,757 | 1,33 [0,79; 1,87] ✓ | 37,02 ✓ | ≥480,58 ✓ | 6,75 ✓ | 8,4 / 16,3 | 0,62 % |
| 5,657 | 1,06 [0,61; 1,51] ✓ | 38,45 ✓ | ≥481,42 ✓ | 6,76 ✓ | 9,3 / 16,8 | 0,62 % |
| 6,727 | 0,84 [0,46; 1,21] ✗ | 39,70 ✓ | ≥481,29 ✓ | 6,77 ✓ | 9,9 / 17,4 | 0,62 % |
| 8 | 0,63 [0,29; 0,97] ✗ | 40,76 ✓ | ≥481,34 ✓ | 6,77 ✓ | 10,6 / 17,7 | 0,62 % |

La cama otra vez, con k = 4 (`--valores 180,195,210,225,240`): m = 210 (479,90 con 2026 y
481,09 con 2027). El abandono apenas depende de la cama.

| m (min) | estancia_ingresados | abandono | tiempo_medico_niveles_2_5 | Box / médico (2 a 5) | Ingr. esperando cama (máx.) |
| --- | --- | --- | --- | --- | --- |
| 180 | ≥433,16 [421,71; 444,60] ✓ | 1,48 ✓ | 33,95 ✗ | 5,9 / 15,8 | 0,31 % |
| 195 | ≥456,47 [444,31; 468,64] ✓ | 1,57 ✓ | 34,48 ✗ | 6,6 / 15,6 | 0,31 % |
| 210 | ≥479,90 [466,95; 492,86] ✓ | 1,68 ✓ | 35,31 ✓ | 7,6 / 15,5 | 0,62 % |
| 225 | ≥503,02 [489,28; 516,76] ✓ | 1,79 ✓ | 36,30 ✓ | 8,6 / 15,5 | 0,62 % |
| 240 | ≥527,15 [512,34; 541,96] ✓ | 1,99 ✓ | 37,53 ✓ | 9,8 / 15,5 | 0,62 % |

### La paciencia: k = 4, discrepancia estructural

k = 4 llegó a la parada de k ≥ 4 del plan. Pedro la aceptó como discrepancia estructural,
igual que el reloj A del nivel 3 en la 4.6c, después de un diagnóstico:

1. **El valor y su efecto.** La mediana de la paciencia del nivel 4 es de 600 min (10 h) y
   la del nivel 5, de 480 (8 h), frente a las 2 h que declara la mitad de los pacientes de
   los niveles 3 a 5 en la encuesta de Shaikh.
2. **Por qué se acepta.** El abandono (1,68 %) y el reloj A de los niveles 2 a 5 (35,31 con
   2026 y 36,63 con 2027) piden los dos una paciencia larga: con k = 2 el abandono ya pasa
   (3,52 % [2,53; 4,51]), pero el reloj A cae a 27,31, fuera de su horquilla. Shaikh es una
   encuesta de lo que se declara, en EE. UU., no de lo que se observa, y el 1,82 % del SAS de
   2013 mezcla fugas, abandonos y altas voluntarias.
3. **El diagnóstico de la forma**, para que no se repita
   ([tablas](tarea-5-6/diagnostico_paciencia.txt) y
   [script](tarea-5-6/diagnostico_paciencia.py), semilla 2026, protocolo de la rejilla):
   - Con 36 boxes y k = 1, 3,364 y 4, los que se van no son la cola izquierda de la
     paciencia sino esperas largas. El tiempo desde la llegada hasta irse:
     - k = 1: p10 27, p50 70 y p90 163 min, con un 12,7 % en 30 min o menos;
     - k = 3,364: 74, 172 y 336, con un 0,9 %;
     - k = 4: 84, 191 y 360, con un 0,8 %.
   - Por nivel real, con k = 4, se va un 0,31 % del nivel 3, un 3,04 % del 4 y un 9,03 %
     del 5; ningún nivel 1 o 2.
   - Con p90 = 2 × mediana (σ = 0,541) y k = 1, el abandono es 5,11 % frente a 5,49 % con
     σ = 0,857, y el reloj A, 20,8. Quita las salidas tempranas (0,7 % en 30 min), pero no
     el grueso del abandono: **la forma no explica la discrepancia**.
   - Con 30 boxes, el mismo patrón con esperas más largas: con k = 4, 4,77 % de abandono y
     p50 de 248 min hasta irse.
4. **La dependencia.** k = 4 compensa las esperas de invierno de una plantilla anual. El
   abandono de cada mes sigue a su reloj A (semilla 2026):

   | | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
   | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
   | Abandono (%) | 3,62 | 2,81 | 1,65 | 1,41 | 1,12 | 0,72 | 1,56 | 0,71 | 0,92 | 2,19 | 0,65 | 2,78 |
   | Reloj A, niveles 2 a 5 (min) | 56,2 | 50,7 | 32,6 | 32,7 | 35,7 | 25,9 | 37,5 | 21,7 | 25,4 | 33,5 | 23,1 | 48,8 |

   Si se añade el refuerzo de invierno, hay que recalibrar k (issue en el Backlog, redactado
   en el PR de la tarea).
5. **El nivel 1.** Con k = 4, su mediana pasa a 5760 min (96 h). No tiene efecto, porque el
   nivel 1 no espera (se clasifica en la puerta y desaloja), pero consta.

### Ajuste (2026), comprobación (2027) y confirmación (2028) del centro calibrado

`uv run edsim calibracion evaluar` con `--semilla 2027` y `--semilla 2028` (30 s cada una). La
partida es `config/` antes de calibrar (30 boxes, m = 240, k = 1). No hubo veto: la 2028 es una
comprobación informativa.

| Objetivo | Uso | Horquilla | partida (2026) | ajuste-2026 | comprobacion-2027 | confirmacion-2028 |
| --- | --- | --- | --- | --- | --- | --- |
| pretriaje_medio | ajuste | 6–15 | 6,03 [5,07; 6,99] ✓ | 6,73 [5,46; 8,00] ✓ | 7,77 [6,23; 9,31] ✓ | 7,67 [6,45; 8,89] ✓ |
| tiempo_medico_niveles_2_5 | ajuste | 35–70 | 27,47 [22,57; 32,36] ✗ | 35,31 [28,14; 42,48] ✓ | 36,63 [29,16; 44,11] ✓ | 35,73 [29,43; 42,03] ✓ |
| tiempo_medico_nivel_3 | comprobacion | 45–75 | 20,14 [17,32; 22,97] ✗ | 18,79 [16,59; 20,99] ✗ | 19,83 [17,19; 22,48] ✗ | 20,77 [17,69; 23,86] ✗ |
| porcentaje_sobre_manchester | comprobacion | 10–30 | 17,12 [12,52; 21,71] ✓ | 16,08 [12,64; 19,53] ✓ | 16,48 [13,06; 19,90] ✓ | 16,54 [13,49; 19,58] ✓ |
| porcentaje_pretriaje_mas_5 | comprobacion | 30–60 | 30,60 [27,86; 33,34] ✓ | 31,35 [28,45; 34,26] ✓ | 32,87 [29,26; 36,47] ✓ | 32,28 [29,49; 35,06] ✓ |
| abandono | ajuste | 1–4 | 10,95 [7,45; 14,45] ✗ | 1,68 [1,06; 2,30] ✓ | 2,00 [1,24; 2,76] ✓ | 1,91 [1,24; 2,59] ✓ |
| estancia_ingresados | ajuste | 360–600 | ≥526,96 [511,72; 542,20] ✓ | ≥479,90 [466,95; 492,86] ✓ | ≥481,09 [468,39; 493,78] ✓ | ≥489,44 [476,45; 502,43] ✓ |
| ingresados_mas_4h | comprobacion | 35–65 | 82,09 [80,40; 83,78] ✗ | 78,70 [76,74; 80,66] ✗ | 78,51 [76,81; 80,21] ✗ | 79,07 [77,45; 80,69] ✗ |
| estancia_atendidos | comprobacion | 120–210 | ≥167,46 [155,69; 179,23] ✓ | ≥164,43 [153,50; 175,36] ✓ | ≥166,80 [157,09; 176,52] ✓ | ≥167,18 [157,43; 176,93] ✓ |
| ingreso_observado | comprobacion | 8–13 | 9,27 [8,96; 9,59] ✓ | 9,75 [9,28; 10,22] ✓ | 9,85 [9,37; 10,33] ✓ | 9,91 [9,41; 10,41] ✓ |

- **Los objetivos de ajuste pasan con las tres semillas.** Fallan dos comprobaciones:
  - el reloj A del nivel 3, la discrepancia de la 4.6b;
  - los ingresados de más de 4 h: 78,7 % frente al 49,69 % del SAS. Con 170 min de
    atención y una espera de cama lognormal de mediana 210 por el factor de turno, casi
    todos pasan de 4 h. Que el SAS dé una media de 472,5 min con solo la mitad por encima
    de 240 pide una cola mucho más larga que p90 = 3 · m; la forma de la espera de cama es
    por criterio. Se informa y no decide.
- **El ingreso observado** (9,75 %) queda por debajo del 9,90 % derivado, como se esperaba:
  23 de los 729 que se fueron con 2026 habrían ingresado.
- **La media por paciente del año:** abandono 1,72 % y reloj A de los niveles 2 a 5 35,67.

### Enero y el perfil por mes

Por mes, con 2026, 2027 y 2028: `calibracion evaluar` da el valor de cada objetivo en cada
réplica. Con 2026:

| | ene | feb | mar | abr | may | jun | jul | ago | sep | oct | nov | dic |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pretriaje medio | 10,29 | 10,15 | 8,01 | 5,88 | 7,17 | 5,54 | 6,93 | 4,37 | 4,70 | 5,36 | 4,88 | 7,51 |
| Reloj A, niveles 2 a 5 | 56,23 | 50,69 | 32,57 | 32,66 | 35,68 | 25,85 | 37,49 | 21,72 | 25,39 | 33,52 | 23,08 | 48,82 |
| Abandono (%) | 3,62 | 2,81 | 1,65 | 1,41 | 1,12 | 0,72 | 1,56 | 0,71 | 0,92 | 2,19 | 0,65 | 2,78 |
| Estancia de los ingresados | 500,78 | 499,09 | 488,03 | 465,33 | 486,07 | 436,65 | 480,29 | 450,41 | 478,10 | 478,36 | 492,37 | 503,39 |
| Ingreso observado (%) | 10,58 | 10,23 | 9,53 | 10,14 | 9,98 | 8,49 | 9,46 | 8,73 | 9,37 | 9,73 | 9,62 | 11,16 |

**La semana del 19 al 25 de enero de 2026** (la ejecución principal del notebook 04: 91 días
desde el 5 de enero, 2 de calentamiento, semilla 2026; los llegados de los días 14 a 20). En la
4.6c, con el modelo del hito 4, el reloj A de los niveles 2 a 5 fue de 306 min y el del nivel
5, de 3897 (unas 65 horas), «no realistas: el modelo aún no tiene abandono». Con el hito 5
calibrado:

| | Hito 4 (4.6c) | Hito 5 (5.6) |
| --- | --- | --- |
| Reloj A, niveles 2 a 5 | 306,0 min | 101,0 min |
| Reloj A, nivel 5 | 3897,3 min | 434,7 min |
| Abandonos | — | 240 de 2549 (9,42 %): 0 / 0 / 4 / 202 / 20 por nivel asignado 1 a 5 |
| Boxes con ingresados | — | 7,65 de media, máximo 16; 1 paciente en el pasillo como máximo |

El abandono acota la cola de enero: se van sobre todo los niveles 4 y 5 en los días de
saturación. La plantilla sigue siendo anual; el refuerzo de
invierno queda para versiones posteriores.

### Abandono, cuello de botella y censurados

- **Abandono del año (ventana anual, 2026):**
  - por nivel asignado: 0 / 0 / 0,08 / 2,87 / 10,92 %;
  - por nivel real: 0 / 0 / 0,31 / 3,04 / 9,03 %.
  - Ningún grave de verdad (niveles reales 1 y 2) se fue.
- **Cuello de botella:** con el centro calibrado lo son los médicos. Espera de box de los
  niveles 2 a 5 de 8,69 min frente a 14,89 de médico con 2026 (7,55 y 15,48 con 2027).
- **Censurados al final del día de vaciado** (2026):
  - 3 pacientes en total (máximo 2 de 3359 en una réplica, 0,06 %);
  - de ellos, 3 atendidos dentro, fuera de los relojes y del cumplimiento (en la 5.4, sin
    vaciado, eran 28);
  - y 3 ingresados esperando cama (máximo 0,62 % de los ingresados de una réplica).

### Centro cumplidor

`uv run edsim calibracion sensibilidad --mando medicos` (12 min 26 s) con `config/`. La regla
da la misma plantilla, [14, 14, 6], con días fuera / medidos de los niveles 2 a 5 de 1/144,
0/144, 7/144 y 11/142; [14, 14, 5] tiene 22/142 en el nivel 5. Con la plantilla base, [12, 11,
4], el reloj A de los niveles 2 a 5 pasa (35,31); la elección de la sensibilidad, la más
cercana al centro de la horquilla, sería [10, 10, 4] (50,63), pero la plantilla solo cambia si
sus objetivos se salen (H5-9), y no se salen.

### Fila reproducible

`uv run edsim calibracion evaluar --dias 5 --calentamiento 1` (12 réplicas de la ventana
anual; 12 s; código 0). Medias:
- abandono 2,11 %, estancia de los ingresados ≥476,42 y reloj A de los niveles 2 a 5, 37,70;
- 313 se van, y un ingresado sigue esperando cama al final.

`test_reproduce_la_fila_corta_del_registro` la comprueba y
`test_reproduce_la_fila_anual_del_registro_y_los_boxes_por_little` recalcula la evaluación
anual de 2026 y la regla de los boxes (`tests/test_calibrated_h5.py`).
