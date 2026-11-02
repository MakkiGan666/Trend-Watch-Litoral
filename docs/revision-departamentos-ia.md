# Revisión de departamentos faltantes

La ingesta normal sigue usando reglas locales y no llama a Gemini para ubicar
noticias. La revisión histórica se ejecuta **por separado**, sólo sobre
`Publicacion.departamento=''` y sin decisión territorial previa. No modifica
publicaciones que ya tienen departamento.

La cifra «Coincidencias» de Publicaciones depende de los filtros activos y no
es necesariamente el total de campos vacíos. El comando informa sus propias
candidatas.

## Decisiones posibles

- `asignado`: uno de los 17 slugs de Misiones. Una decisión IA requiere un
  lugar del catálogo y una cita literal de la noticia que lo mencione.
  «Capital provincial» por sí solo no acredita el departamento Capital.
- `provincial`: Misiones, sin departamento único comprobable.
- `fuera`: el hecho central es nacional o de otra provincia.
- `varios`: el hecho central abarca varios departamentos.
- `sin_evidencia`: el texto no permite determinarlo.

Las decisiones se guardan en `RevisionDepartamento` y se pueden consultar en
Django Admin. Al usar `--revisar`, el resultado previo se conserva en el
historial de la revisión. Las respuestas inválidas o las fallas de Gemini no se guardan y
pueden reintentarse. Una abstención queda registrada para no consumir cuota
otra vez por defecto; `--revisar` la reevalúa. El proceso nunca sobrescribe un
departamento existente. La migración `0017` crea sólo la tabla de auditoría.
Los administradores pueden consultar esa auditoría, sin modificarla desde Admin.
Después de migrar, ejecutar `python manage.py configurar_roles` para actualizar
el permiso de lectura del rol Administrador.

El cliente usa `GEMINI_MODEL` si está configurado en `.env` y, en caso
contrario, `gemini-3.8-flash`. La clave se configura mediante
`GEMINI_API_KEY` en `.env`; nunca debe incluirse en un commit ni en la salida
de un comando compartida con el equipo.

## Piloto local

Desde la raíz del proyecto y luego de respaldar la base:

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py revisar_departamentos --limite=20
```

La simulación es el modo predeterminado: no consulta Gemini ni escribe. Para
ver decisiones de IA **sin escribir**, con consumo de cuota:

```powershell
docker compose exec web python manage.py revisar_departamentos --previsualizar-ia --limite=10
```

Después de revisar la muestra y tener `GEMINI_API_KEY` configurada:

```powershell
docker compose exec web python manage.py revisar_departamentos --aplicar --limite=10
```

Cada lote informa `Cursor: N`. Para continuar, usar `--despues-de-id=N` y el
mismo modo. Si hubo errores, volver al cursor **inicial** de ese lote: las
decisiones ya guardadas se omiten y sólo se reintentan las fallidas. Para
procesar únicamente coincidencias locales sin llamar a IA, agregar `--sin-ia`.
Ese modo deja las demás noticias pendientes para una corrida posterior desde
el comienzo. `--revisar` reevalúa abstenciones previas, pero tampoco cambia
departamentos ya asignados.
Si un lote tiene errores de IA, el comando termina con código de error e indica
el cursor **inicial** para reintentar. Las decisiones guardadas antes del error
no se repiten en el reintento.
Ante fallas HTTP 503, se puede reducir la carga por llamada con
`--tamano-lote-ia=5` y aumentar la espera con `--pausa-ia=5`.

Revisar manualmente una muestra de las decisiones en Admin antes de ampliar
los lotes. Una cita textual prueba que el lugar aparece en la noticia, pero no
garantiza por sí sola que sea la sede del hecho central; la decisión de IA
puede ser errónea. Las noticias que permanezcan sin departamento conservan
esa condición de forma visible en los filtros.
