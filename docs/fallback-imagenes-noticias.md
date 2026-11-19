# Fallback visual de imágenes de noticias

Las imágenes de artículos conservan su URL original y se solicitan directamente desde el navegador; TrendWatch no las descarga ni las copia.

Los componentes con imágenes de noticias marcan un contenedor, la imagen y un placeholder con `data-news-image-container`, `data-news-image-fallback` y `data-news-image-placeholder`. El script compartido `news-image-fallback.js` escucha errores de carga, oculta la imagen fallida, muestra el placeholder y oculta su crédito fotográfico. También detecta imágenes que ya habían fallado al inicializarse. Nunca cambia ni vuelve a asignar `src`, así que no provoca ciclos de reintento.

Cuando no existe URL, la plantilla muestra directamente el fallback sin crear un elemento `<img>`. Las fichas RSS conservan su presentación de metadatos y no intentan mostrar una fotografía ausente. Una URL que parece válida puede fallar por causas del medio o CDN; el placeholder no determina cuál fue la causa.

La portada dinámica, tarjetas regionales, tendencias, rankings, etiquetas, búsqueda y detalle usan el mismo estado de error. El detalle mantiene además su placeholder con dimensiones responsivas. Los artículos que ya cargan correctamente conservan la misma URL, `object-fit`, crédito y distribución visual. No cambia la extracción, persistencia ni el circuito histórico de El Territorio.

Las pruebas focalizadas renderizan imágenes presentes, ausentes y fichas RSS en una base SQLite efímera. No prueban la disponibilidad de imágenes remotas ni realizan solicitudes HTTP.
