"""Fechas de navegación sin modificar los timestamps históricos ni el alta legacy."""
from zoneinfo import ZoneInfo

ZONA_LOCAL = ZoneInfo('America/Argentina/Buenos_Aires')


def fecha_efectiva(publicacion):
    return publicacion.fecha_publicacion if publicacion.fecha_publicacion is not None else publicacion.fecha_captura


def datos_fecha(publicacion):
    fecha = fecha_efectiva(publicacion)
    origen = 'publicacion' if publicacion.fecha_publicacion is not None else 'captura'
    if fecha is None:
        return {'fecha_efectiva': None, 'fecha_dia': None,
                'fecha_precision': None, 'fecha_origen': None}
    # Django devuelve aware con USE_TZ. Para objetos legacy sin zona, no depender
    # de la zona del sistema operativo: interpretar explícitamente la zona del proyecto.
    local = fecha.replace(tzinfo=ZONA_LOCAL) if fecha.tzinfo is None else fecha.astimezone(ZONA_LOCAL)
    # El archivo almacena históricamente mediodía UTC cuando sólo conoce el día.
    # Sin marcador persistente no se puede asegurar qué horas son reales: degradar
    # conservadoramente la precisión de presentación de TODAS las notas de archivo.
    dia_solo = origen == 'publicacion' and publicacion.fuente == 'El Territorio (Archivo)'
    return {
        'fecha_efectiva': local.date().isoformat() if dia_solo else local.isoformat(),
        'fecha_dia': local.date().isoformat(),
        'fecha_precision': 'dia' if dia_solo else 'instante',
        'fecha_origen': origen,
    }
