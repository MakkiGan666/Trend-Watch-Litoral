# Procesamiento con IA de las noticias del 03/11/2026 al 07/11/2026

Estado al 07/11/2026: **pendiente**. Las 293 noticias del período están ingestadas
(El Territorio, `ingestar_historico --sin-ia`) y siguen con `procesado_ia=False`. No se
guardó ningún análisis parcial ni de prueba, y no se modificaron datos existentes.

## Por qué no se procesaron

1. **Gemini devolvía 503/504 de forma sostenida** (`gemini-3.8-flash`: «high demand» /
   `DEADLINE_EXCEEDED`), también después de los 3 reintentos. «Probar conexión» del panel
   consulta metadatos del modelo y puede decir *Conectado* aunque la generación falle por
   sobrecarga: no sustituye a una prueba de generación.
2. **Llama 3.1 (respaldo) no es equivalente a Gemini para este análisis:**
   - Latitudes con el signo equivocado (Posadas `26.3` en vez de ≈ `-27.4`; Oberá `26.5`
     en vez de ≈ `-27.5`): los puntos del dashboard quedarían mal ubicados.
   - Polaridad y confianza extremas (`1`, `-1.0` con confianza alta) sin matices.
3. Por eso **ningún análisis de publicaciones generado por Ollama se guarda**, ni como
   respaldo automático ni como motor principal (la capacidad de persistir es una propiedad
   del proveedor: `persiste_analisis_publicaciones`, sólo verdadera en Gemini):
   - Motor principal = Llama: `procesar_pendientes` ni siquiera consulta al modelo; devuelve
     `NO_DISPONIBLE` y marca cada publicación con `motor_no_persistente`.
   - Respaldo automático: el respaldo se intenta y se registra, pero su resultado se descarta
     (`respaldo_no_persistido`).
   - Guardia final: tras generar, cualquier respuesta de un proveedor no persistible se descarta.
   En todos los casos la noticia queda con `procesado_ia=False`. La clasificación de categorías
   y la revisión de departamentos **sí** pueden usar Ollama (sus validadores aceptan sólo listas
   cerradas y citas verificables).
4. El panel distingue **«Conexión al servicio»** (metadatos; «Conectado» no garantiza que pueda
   generar) de **«Capacidad de generación»** (pedido mínimo fijo, sin datos de noticias, una llamada).

## Noticia 4329 (07/11/2026): por qué no superó la validación

Reproducido 3 de 3 veces con Llama 3.1: devuelve `localidades` con las claves `nombre` y
`latitud` pero **sin `longitud`** (Posadas, Oberá). `validar_respuesta_gemini` exige
exactamente `nombre`, `latitud` y `longitud`, y rechaza la respuesta con
`validacion_respuesta` antes de escribir nada. Es el comportamiento correcto: no se
relajó el validador. No es un defecto de la noticia (5.005 caracteres) ni del validador;
es una limitación del modelo local con este esquema.

## Procedimiento acordado

1. Esperar a que Gemini **genere** correctamente (no basta «Probar conexión»).
2. **Prueba controlada de 3–5 noticias** del período, con el rango incorporado a
   `procesar_pendientes(batch_size, desde, hasta)`:
   ```bash
   docker compose exec web python manage.py shell -c "
   import datetime
   from core.services.gemini_cliente import gemini_cliente
   print(gemini_cliente.procesar_pendientes(
       batch_size=3, desde=datetime.date(2026, 11, 3), hasta=datetime.date(2026, 11, 7)))"
   ```
3. Verificar en PostgreSQL: respuestas válidas, signos de latitud (negativa) y longitud
   (negativa) para Misiones/Litoral, polaridad y confianza razonables, un único
   `Sentimiento` por noticia, sin `Locacion` duplicadas y sin cambios fuera del
   03–07/11.
4. Sólo con esos resultados y con autorización expresa, procesar las 293 restantes
   (con pausa de 12 s por noticia, ~1 h).

Sin la migración `0021_configuracionia` aplicada rige la configuración por defecto
(Gemini principal, respaldo activo) y el panel no puede guardar cambios.
