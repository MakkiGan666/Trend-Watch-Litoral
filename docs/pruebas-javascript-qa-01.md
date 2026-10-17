# QA-01 — Ejecución de pruebas JavaScript existentes

Fecha: 15/10/2026. Responsable: Tomás Gudiño, con asistencia de Codex.
Rama: `test/QA-01`, creada desde `origin/main` en `17bf180` según la preparación de Git informada por el responsable. Relación: TW-18 (QA integral y trazabilidad).

## Resultado

Se encontró un archivo con cuatro casos JavaScript. La ejecución autorizada finalizó con **4 aprobados, 0 fallidos, 0 cancelados, 0 omitidos y 0 pendientes**, código de salida 0. No quedaron casos bloqueados después del reintento.

No se modificaron pruebas, funcionalidades, dependencias, modelos ni datos. El único entregable agregado es este informe.

## Inventario y mecanismo

- Suite: `app/core/test_auth_flow.js`.
- Código probado: `app/static/js/auth-flow.js`.
- Runner: `node:test`, con aserciones de `node:assert/strict`.
- Otros módulos nativos: `node:fs`, `node:path` y `node:vm`.
- El archivo fuente se carga con `readFileSync` y se ejecuta mediante `runInNewContext`.
- El DOM está simulado con una clase `Element` que extiende `EventTarget`; `fetch`, `FormData` y la navegación también están simulados. Las pruebas no crean usuarios ni realizan solicitudes de red reales.
- La búsqueda de archivos JavaScript (`.js`, `.mjs`, `.cjs`), nombres de pruebas y configuración, excluyendo `.git`, `.venv` y `node_modules`, no encontró otras suites JavaScript en la versión revisada.
- No se encontró `package.json`, lockfile de npm ni configuración de Jest, Vitest o Mocha en ese inventario. No se requiere `npm install` para esta suite.

## Entorno y reproducción

Entorno utilizado: Windows, PowerShell, Node.js **v24.21.0** y npm **11.19.0**. npm sólo se consultó para registrar su versión; no interviene en las pruebas. No se establece con esta ejecución la versión mínima compatible de Node.

Desde la raíz del repositorio:

```powershell
node --version
npm --version
node --test app/core/test_auth_flow.js
```

El comando de pruebas también está documentado en la primera línea de `app/core/test_auth_flow.js`. No requiere Django, PostgreSQL, Docker, credenciales ni el entorno virtual Python. Para reproducirlo en otra máquina es necesario tener disponible una versión de Node con los módulos y APIs nativos utilizados; la versión anterior es la efectivamente comprobada.

## Resultados por caso

| Caso existente | Qué comprueba | Resultado |
|---|---|---|
| `el modal inicia en login y cambia al endpoint y campos de registro` | Inicio en `/login/`; cambio a `/registro/`, visibilidad de secciones y desactivación/activación de campos. | Aprobado |
| `el login envía la solicitud AJAX y presenta errores del servidor` | URL y método POST, encabezado `X-Requested-With` y presentación del mensaje de credenciales rechazadas devuelto por el servidor simulado. | Aprobado |
| `el registro publica el formulario y recarga al completarse` | Envío a `/registro/` mediante POST y navegación a `/` tras una respuesta simulada exitosa. | Aprobado |
| `cerrar el modal vuelve al modo login` | El evento `auth:reset` restablece endpoint, visibilidad y estado del formulario de registro. | Aprobado |

Resumen de la ejecución final:

```text
tests 4
suites 0
pass 4
fail 0
cancelled 0
skipped 0
todo 0
duration_ms 260.7121
exit_code 0
```

El valor `suites 0` es el resumen del runner para estos cuatro casos declarados con `test()`, no ausencia de pruebas.

## Incidente del primer intento

El primer `node --test app/core/test_auth_flow.js`, ejecutado dentro del aislamiento de herramientas de Codex, terminó con salida 1 y `Error: spawn EPERM` (`errno: -4048`, `syscall: spawn`). El runner no pudo crear el proceso hijo para ejecutar el archivo.

Ese intento reportó un archivo fallido (`tests 1`, `pass 0`, `fail 1`); **no representa un fallo de uno de los cuatro casos funcionales**, que no llegaron a ejecutarse en ese intento.

Se solicitó y obtuvo autorización para ejecutar el mismo comando fuera del aislamiento. Sin modificar archivos ni instalar paquetes, pasaron los cuatro casos. La evidencia apunta a una restricción de creación de procesos en el primer entorno, no a un defecto del flujo de autenticación. No se garantiza que el error se reproduzca en una terminal PowerShell normal; el contexto de aislamiento forma parte de su reproducción.

Si otro integrante encuentra `spawn EPERM`, registrar el contexto y los permisos de ejecución y repetir el comando en una terminal autorizada. No actualizar paquetes ni cambiar pruebas para ocultar este error.

## Límites y recomendaciones

- Esta suite verifica lógica del flujo de formularios en un DOM simulado. No prueba autenticación real, JWT, CSRF efectivo, contenido real de FormData, cookies, validación del navegador, estilos, accesibilidad o interacción visual completa.
- La fixture devuelve `null` para la búsqueda de la campana; por tanto, el bloque de notificaciones de `auth-flow.js` no se ejecuta en estos casos.
- Los demás scripts de producción encontrados (`trendwatch.js`, `landing-news.js`, `exchange-rates.js`, `notification-prompt.js` y `dashboard.js`) no tienen suites JavaScript propias localizadas en este inventario. Esto es una limitación de cobertura, no evidencia de que fallen.
- No se ejecutó la suite Python: los 176 casos mencionados en la tarjeta corresponden a evidencia previa de la auditoría del equipo y no se presentan aquí como un resultado actual.
- No se detectaron fallos funcionales reproducibles en los cuatro casos existentes. No hace falta abrir una tarea de corrección de producto por el bloqueo de permisos ya resuelto.
- Como posibles tareas independientes de ampliación de QA, acordar cobertura de errores de red, notificaciones y renderizado de noticias/cotizaciones, y una comprobación real de login/registro en navegador con cuentas de prueba autorizadas. No se implementan ni se crean tarjetas de Trello en QA-01; el equipo decide su prioridad.

## Criterios de aceptación

- [x] Localizar los archivos de pruebas JavaScript existentes.
- [x] Identificar el framework y el comando de ejecución.
- [x] Comprobar dependencias sin actualizar paquetes innecesariamente.
- [x] Ejecutar las pruebas disponibles.
- [x] Registrar aprobadas, fallidas y no ejecutadas, distinguiendo el primer bloqueo del resultado final.
- [x] Documentar el incidente y el contexto de reproducción.
- [x] Guardar comandos, resultados y limitaciones en este informe.
- [ ] Compartir el informe mediante PR, mover la tarjeta a En revisión y registrar tareas adicionales si el equipo las acuerda.
