# H1.1 — Catálogo de medios RSS

`app/core/services/fuentes_rss.py` declara los 18 medios nuevos con feed
confirmado en `auditoria_rss_resultados/rss_resumen.md`, auditoría local del
05/11/2026. No incluye El Territorio ni los medios sin feed confirmado. Conserva
las URLs auditadas, incluidas la query de Oberá Inside y las rutas especiales de
Noticias de la Calle, Stop en Línea y Fracrán Noticias.

Cada `FuenteRSS` tiene identificador estable, nombre, feed HTTPS, tupla de hosts
exactos permitidos, habilitación y límites individuales. Los valores iniciales
son: 30 noticias, 10 segundos, 1.500.000 bytes y 4 redirecciones. Todas las fuentes
están deshabilitadas por defecto. Para configurar una fuente, editar su declaración
Python con argumentos nombrados, por ejemplo `habilitada=True, limite_noticias=5`.
Las configuraciones son inmutables; no existe interfaz de administración ni
configuración en base de datos.

`obtener_fuentes()` devuelve sólo las habilitadas;
`obtener_fuentes(solo_habilitadas=False)` devuelve el catálogo completo.
`validar_catalogo(fuentes)` valida una colección y devuelve una tupla. Las
declaraciones se validan al construirlas, incluso si están deshabilitadas; el
catálogo se valida al importar el módulo. Un error produce `ValueError`.
Se rechazan identificadores o feeds repetidos, límites inválidos, credenciales
en URLs, fragmentos, puertos distintos de HTTPS y hosts ajenos. Los hosts no
admiten comodines ni subdominios implícitos; apex y `www` se enumeran explícitamente.

Este módulo no descarga, no analiza XML, no guarda publicaciones y no está
conectado a comandos, vistas ni al scraper actual. Habilitar una fuente sólo
cambia la selección del catálogo. Los límites son configuración para un futuro
consumidor; H1.1 no los aplica a solicitudes. La validación es local: el futuro
transporte deberá controlar DNS público, cada redirección, bytes y tiempos.
La auditoría acredita el estado observado de los feeds, no su disponibilidad
futura ni la extracción completa de artículos.

Validación desde la raíz del repositorio, sin red ni base de datos:

```sh
python app/manage.py test core.tests.CatalogoFuentesRSSTestCase --verbosity 2
```

Las pruebas usan `SimpleTestCase` y verifican las 18 URLs esperadas, habilitación
independiente, inmutabilidad, límites, hosts y duplicados. La importación fría
se comprueba en un intérprete nuevo con caché de bytecode desactivada y un hook
de auditoría instalado antes de importar `core`. Este bloquea red, escrituras,
mutaciones del sistema de archivos y creación de procesos durante la importación
y la consulta del catálogo; también se comprueba que los bloqueos estén activos.
