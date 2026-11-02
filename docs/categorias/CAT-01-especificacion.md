# TrendWatch Litoral — CAT-01
## Especificación del catálogo y contrato de categorías
**Estado:** Diseño acordado; listo para revisión del equipo e implementación posterior.  
**Fecha:** 16 de octubre de 2026.  
**Alcance:** Diseño y documentación. No modifica código, migraciones ni datos.

### 1. Objetivo
Definir un catálogo temático ampliable, independiente de las secciones RSS de origen y de la clasificación geográfica, que permita a Django almacenar y exponer categorías de publicaciones y a un futuro clasificador automático seleccionarlas de forma validada.

### 2. Decisiones aprobadas D-01 a D-18
- **D-01:** Conservar `Categoria`, `Tema` y `PublicacionTema` como estructura base.
- **D-02:** Separar clasificación temática y ubicación geográfica (`Locacion`).
- **D-03:** Catálogo inicial de cuatro categorías: Salud, Policiales, Turismo, Festividades.
- **D-04:** Diseñar el catálogo para permitir ampliaciones posteriores.
- **D-05:** La clasificación temática debe ser automática para la entrega del 29/10/2026; Sebastián asume su desarrollo.
- **D-06:** Conservar publicaciones sin coincidencia temática; distinguirlas de pendientes y errores.
- **D-07:** Admitir múltiples categorías relevantes, sin duplicados ni categorías inventadas.
- **D-08:** Permitir reclasificar publicaciones históricas bajo demanda, sin duplicar publicaciones.
- **D-09:** Cada categoría tendrá ID numérico, `codigo` textual estable y único, y `nombre_categoria` visible.
- **D-10:** `GET /api/categorias/` devuelve `status`, `total`, `data`, con `id`, `codigo`, `nombre` por categoría.
- **D-11:** Respuestas de publicaciones incluyen `categorias` como objetos `{id,codigo,nombre}` y `estado_clasificacion` en `pendiente`, `clasificada`, `sin_categoria`, `error`.
- **D-12:** El clasificador devuelve `{"categorias": ["codigo", ...]}`; Django valida catálogo, estructura y duplicados; errores no destruyen resultados válidos.
- **D-13:** Si falla una reclasificación, conservar el último resultado válido y registrar el fallo del intento por separado, permitiendo reintentos.
- **D-14:** Persistir categorías automáticas mediante un tema general identificado expresamente para cada categoría; conservar temas específicos.
- **D-15:** Incorporar `es_general` a `Tema`; restringir a lo sumo un tema general por categoría y asegurar al menos uno por inicialización/validación.
- **D-16:** Reclasificación exitosa reemplaza solo asociaciones bajo control del clasificador y de forma atómica, sin tocar otras.
- **D-17:** `PublicacionTema` registra `origen`: `automatica`, `manual`, `legado`; proteger manuales e históricas.
- **D-18:** Ante coincidencia con relación `manual` o `legado`, preservarla sin duplicar ni cambiar origen.

### 3. Catálogo inicial
| Código estable | Nombre visible | Criterio temático inicial |
|---|---|---|
| `salud` | Salud | Hospitales, servicios médicos, enfermedades, campañas sanitarias, vacunación y prevención. |
| `policiales` | Policiales | Delitos, detenciones, operativos, investigaciones criminales y seguridad pública. |
| `turismo` | Turismo | Destinos, visitantes, alojamiento, servicios y actividad turística regional. |
| `festividades` | Festividades | Fiestas populares, celebraciones, festivales y eventos culturales festivos regionales. |

Los nombres y criterios son la propuesta operativa inicial; las secciones RSS (`misiones`, `tecnologia`, `policiales`, `cultura`, `actualidad`) no son el catálogo canónico. Noticias fuera de alcance pueden quedar sin categoría.

### 4. Contrato REST propuesto
**GET `/api/categorias/`**
```json
{
  "status": "success",
  "total": 2,
  "data": [
    {"id": 2, "codigo": "salud", "nombre": "Salud"},
    {"id": 3, "codigo": "policiales", "nombre": "Policiales"}
  ]
}
```
*IDs ilustrativos. En el entorno real devolver las cuatro categorías iniciales.*

**GET `/api/publicaciones/` y GET `/api/publicaciones/{id}/`**: conservar campos actuales y añadir:
```json
{
  "categorias": [
    {"id": 3, "codigo": "policiales", "nombre": "Policiales"}
  ],
  "estado_clasificacion": "clasificada"
}
```
Una lista vacía puede corresponder a `pendiente`, `sin_categoria` o `error`; el estado los distingue. **Matiz:** cuando hay relaciones manuales/históricas protegidas, el estado presentado debe ser consistente con las asociaciones visibles; la definición exacta de estado agregado será formalizada en CAT-02.

**Contrato interno del clasificador** (no es endpoint REST público):
```json
{"categorias": ["policiales", "festividades"]}
```
`[]` es válido para ninguna coincidencia. Los códigos deben existir, ser únicos y pertenecer al catálogo vigente; JSON inválido y códigos desconocidos se rechazan sin escritura parcial.

### 5. Integridad y comportamiento
- Guardar asociaciones mediante `Publicacion → PublicacionTema → Tema → Categoria`.
- Crear e identificar un tema `es_general=True` por categoría; no usar el primer `Tema` arbitrariamente.
- No permitir más de un tema general por categoría; prever inicialización y migración de datos existentes.
- En `PublicacionTema`, `origen` distingue relaciones controladas por el clasificador de manuales e históricas; al migrar asociaciones sin procedencia comprobable, tratarlas conservadoramente como `legado`.
- Si IA propone categoría ya asociada por origen `manual` o `legado`, conservar la relación sin cambiar su origen ni insertar duplicados.
- Una reclasificación válida reemplaza solo vínculos propios (`automatica`) y se guarda en transacción junto con su estado.
- Si falla la validación, la IA o la persistencia, conservar el resultado válido anterior y registrar el intento fallido separadamente.
- `procesado_ia` ya se usa en procesamiento de sentimientos y no debe reutilizarse como único indicador de clasificación temática.
- Distinguir **resultado de clasificación** de **estado del último intento**. Prever reintento de errores y reclasificación histórica bajo demanda.

### 6. Pruebas y criterios de aceptación
1. El catálogo ofrece cuatro categorías con ID/código/nombre estables.
2. Se rechazan códigos duplicados y nombres vacíos; la normalización de nombres evita duplicados triviales.
3. La API de publicaciones conserva los campos existentes y devuelve objetos de categorías y estado.
4. Una publicación pendiente, una sin coincidencias y una con error se distinguen correctamente.
5. La clasificación múltiple válida crea relaciones sin duplicados.
6. Códigos desconocidos, JSON inválido o repetidos se rechazan sin alterar asociaciones.
7. Una respuesta válida `[]` representa ausencia de coincidencias en la clasificación automática; no borra relaciones protegidas.
8. Ante error de reclasificación se conservan categorías y estado válido previos.
9. Una reclasificación válida reemplaza sus asociaciones automáticas, sin modificar `manual` o `legado`.
10. Nuevas categorías se agregan al catálogo sin alterar el esquema del contrato JSON.
11. Cada categoría operativa tiene un solo tema general, sin reclasificar accidentalmente temas específicos históricos.
12. Los cambios de persistencia son atómicos.

### 7. Traspaso de implementación
**CAT-02 (implementación):** migración `Categoria.codigo` único; `Tema.es_general` con unicidad condicional; `PublicacionTema.origen` con migración conservadora; persistencia del estado temático y registro separado de fallos/reintentos; bootstrap de catálogo y temas generales; serializadores, API de categorías, enriquecimiento de respuestas de publicaciones; servicio de asociación y pruebas. Verificar explícitamente la semántica de estado ante relaciones protegidas y la interacción con formularios web. **No** eliminar registros históricos ni rehacer migraciones pasadas.

**Tarea posterior de clasificación automática:** uso del catálogo vigente por Gemini u otro clasificador, manejo de errores/reintentos, clasificación al ingresar nuevas noticias y reclasificación histórica bajo demanda. Debe estar operativa antes del 29/10/2026.

**Integración frontend posterior:** reemplazar categorías de demostración por datos de API; filtrar noticias reales; contemplar estados vacíos y noticias sin coincidencia.

**Fuera de CAT-01:** ampliar volumen RSS, ingesta histórica septiembre/octubre, imágenes, segmentación geográfica y cambios directos al scraper.

### 8. Aspectos pendientes de concreción técnica en CAT-02
- Modelo concreto para `estado_clasificacion` y registro separado del último intento (campos o entidad auxiliar), incluidas relaciones protegidas.
- Política precisa para cuando un resultado automático vacío coexiste con relaciones manuales o históricas.
- Mecanismo de migración y unicidad de `codigo` y de `es_general`, sin eliminar la categoría histórica `Misiones` por accidente.
- Adaptación de los formularios existentes, que actualmente pueden vincular categorías utilizando un tema arbitrario.
- Pruebas end-to-end con ingesta nueva; estas dependen de integrar el clasificador, no solo de CAT-02.

### 9. Relación con roadmap de estabilización
La implementación debe respetar las reparaciones pendientes sobre la ingesta, validación CRUD, atomicidad/idempotencia Gemini, autenticación y configuración. Evitar PRs de refactorización masiva o cambios destructivos que mezclen alcances.
