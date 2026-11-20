# Fase 3B — Agrupación editorial automática conservadora

## Alcance y seguridad por defecto

La agrupación automática sólo puede ejecutarse sobre candidatos ya registrados
por la cola de detección en sombra. No consulta medios, no descarga contenido y
no cambia publicaciones, comentarios, etiquetas ni relaciones originales. La
configuración `AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA` permanece en `False`
si no se configura explícitamente. El comando exige indicar exactamente uno de
`--dry-run` o `--aplicar`; la segunda opción falla cerrada cuando el gate está
desactivado.

## Regla `auto-editorial-exacto-v1`

La política no interpreta similitud como prueba suficiente. Para resultar
elegible, un candidato debe estar pendiente, no bloqueado por una revocación,
tener versión de detector vigente y no tener publicaciones ya incorporadas a
otro grupo vigente. La evidencia almacenada debe coincidir con huellas
recalculadas desde ambas publicaciones actuales. Además exige:

1. La misma fuente editorial normalizada (incluidos alias configurados del
   mismo medio), con fuente y evidencia coherentes.
2. Títulos iguales tras la normalización determinista del detector.
3. La misma fecha editorial; no se sustituye por fecha de captura ni `lastmod`.
4. Ambos contenidos marcados completos, con al menos 300 caracteres.
5. Igualdad exacta del cuerpo después de retirar etiquetas HTML, normalizar
   Unicode, caja y espacios. Se conserva la puntuación.
6. Confirmación directa del detector para ese par. No se usa transitividad.

Se evalúan candidatos `PROBABLE` y `EXACTO`; ambos deben superar cada criterio
anterior. `AMBIGUO`, fichas incompletas, revisiones editoriales y coberturas de
distintos medios no se agrupan automáticamente. El informe explica la decisión
con códigos de motivo, IDs, huellas y métricas, sin volcar cuerpos periodísticos.

## Persistencia, auditoría y concurrencia

La aplicación de cada candidato se ejecuta en una transacción individual. Se
bloquean las publicaciones por ID ascendente, luego el candidato, y se vuelve a
validar toda la evidencia y el par de IDs. Las restricciones únicas de
membresía vigente, candidato por grupo e idempotencia del evento actúan como
última barrera de integridad. Cualquier error revierte conjuntamente grupo,
membresías, evento y estado del candidato.

Los grupos, miembros y eventos distinguen origen humano y automático. Las
decisiones automáticas dejan `actor`/revisor humano nulos y registran la versión
de regla, del detector, el candidato, huellas, criterios y clave idempotente.
No se atribuye ninguna acción a AdminSeba ni a otra cuenta humana. El servicio
de revocación mantiene la auditoría humana y bloquea la automatización de los
candidatos que involucren cualquiera de las publicaciones liberadas; así una
pareja alternativa no puede eludir la revocación del grupo.

## Comandos

Consultar todos los candidatos (máximo 1000 por invocación) sin escribir:

```sh
python manage.py agrupar_duplicados_editoriales --dry-run
python manage.py agrupar_duplicados_editoriales --dry-run --limite 200 --fuente "El Territorio"
```

El dry-run se ejecuta dentro de una transacción PostgreSQL `READ ONLY`. Incluye
estados terminales para que el reporte abarque la cola, mientras sólo los
pendientes pueden ser elegibles.

La aplicación está implementada, pero no debe habilitarse en la instalación
habitual hasta una autorización operativa específica y revisión de los
resultados. En un entorno habilitado, el comando sería:

```sh
python manage.py agrupar_duplicados_editoriales --aplicar --limite 20
```

Cada ejecución de aplicación vuelve a obtener el preview y revalida cada par
transaccionalmente; las modificaciones concurrentes vuelven no elegible al
candidato en vez de agrupar evidencia antigua. No se configura tarea periódica
ni arranque automático.

## Migración 0032 y reversión

La migración amplía los campos de decisión/origen, auditoría y estado de
revocación, relaja `creado_por` sólo para decisiones automáticas y reemplaza las
restricciones de validación para distinguir ambos orígenes. Los registros
anteriores reciben los valores por defecto HUMANOS y conservan sus autores y
revisiones. No altera publicaciones ni crea grupos.

La migración es reversible a nivel de esquema antes de crear grupos
automáticos. Una reversión después de aplicar agrupaciones automáticas requiere
primero exportar y resolver esos grupos: el esquema anterior exige un creador
humano y no puede representar fielmente decisiones automáticas sin
inventar una identidad. No se ofrece una reversión que falsee esa auditoría.

## Límites

- La igualdad normalizada del cuerpo es deliberadamente estricta: descarta
  actualizaciones legítimas, aunque el detector las clasifique como probables.
- Aun con esta regla, no se afirma identidad semántica ni autorización de uso;
  la política sólo determina equivalencia editorial mecánica sobre datos ya
  persistidos.
- Este cambio no activa el gate, no aprueba los candidatos históricos, no
  ejecuta la fase 3C y no cambia la búsqueda.

## Validación de implementación (2026-11-20)

- PostgreSQL/PostGIS temporal aislado: 59 pruebas focalizadas aprobadas,
  incluyendo integración de búsqueda/API/autocompletado, concurrencia de pares
  solapados, repetición idempotente, revocación, fallo de auditoría con
  rollback, evidencia obsoleta, alias de fuente y migraciones.
- `manage.py check`: correcto.
- `makemigrations core --check --dry-run`: sin cambios pendientes.
- La migración 0032 se aplicó durante las pruebas únicamente en las bases
  temporales de test. Su SQL añade campos/restricciones e índices y reemplaza
  dos restricciones; no toca filas de publicaciones.
- La cola habitual se evaluó bajo una transacción PostgreSQL `READ ONLY`,
  ejecutando `previsualizar_candidatos` desde este worktree. Como 0032 no está
  aplicada allí, la sesión de diagnóstico representó el nuevo booleano
  `automatizacion_bloqueada` con su valor por defecto `false`; no emitió DML.
  Resultado: 93/93 candidatos PENDIENTES evaluados, 0 elegibles: 86 por cuerpo
  no equivalente, 5 por clasificación no elegible y 2 por fecha editorial
  distinta. Los 4 grupos activos, 8 membresías vigentes, 16 eventos y 3.249
  publicaciones se conservaron; no se creó ni aprobó grupo alguno.

## Auditoría de equivalencia de los 86 rechazos

La revisión de los cuerpos se ejecutó en memoria dentro de una transacción
`READ ONLY`; no se imprimieron ni persistieron textos. Los resultados son
indicadores agregados, no confirmaciones editoriales individuales:

- 0/86 se volvieron iguales con NFKC o al unificar las comillas tipográficas
  evaluadas; la regla actual ya normaliza Unicode NFC y espacios.
- 32/86 tenían algún párrafo distinto con un marcador de navegación/publicidad;
  ninguno quedó igual al excluir esos bloques detectables.
- 34/86 tenían algún párrafo distinto que parecía línea de metadatos; ninguno
  quedó igual al excluir esas líneas heurísticas.
- 76/86 diferían en tokens numéricos; 3/86, en tokens de negación. En 35/86
  coincidía el multiconjunto de palabras ignorando números, lo cual no
  demuestra igualdad de orden, cifras ni significado.
- La similitud mediana fue 0,9987 por caracteres y 0,9977 por palabras; pese a
  ello, 0/86 tuvo equivalencia exacta con las normalizaciones ensayadas.

Conclusión: los marcadores de extracción aparecen en parte de los pares, pero
no explican por sí solos sus diferencias. Las variaciones de cifras y
negaciones pueden ser semánticas. Por eso `auto-editorial-exacto-v1` permanece
sin cambios; no se ajustó el umbral ni se declararon candidatos elegibles por
similitud. Ninguno de los 93 candidatos históricos superó la regla automática.
