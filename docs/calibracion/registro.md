# Registro de calibración

Cada cambio de un parámetro calibrado, con su valor de antes y de después, el KPI que lo
decide, el motivo y el comando que reproduce cada tabla (regla 1 de la calibración,
[docs/specs/hito-4.md](../specs/hito-4.md), «Calibración»). Los CSV que escriben los
comandos van a `resultados/`, que no se sube.

## Tarea 4.6b: enfermería de triaje y médicos (6 de noviembre de 2026)

Rama `feat/h4-calibracion`. Modelo clínico con `config/llegadas.toml`,
`config/perfiles.toml` y `config/objetivos.toml`; boxes (30), duraciones y
`espera_resultados_fuera` (`[4, 5]`) fijos.

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
