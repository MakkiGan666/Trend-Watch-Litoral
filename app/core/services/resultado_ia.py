ESTADOS_HTTP = {
    'EXITO': ('success', 200),
    'PARCIAL': ('partial', 200),
    'FALLO': ('error', 500),
    'NO_DISPONIBLE': ('error', 503),
    'SIN_PENDIENTES': ('success', 200),
}


def respuesta_resultado_ia(resultado, campo_mensaje='mensaje', mensaje_ingesta=None):
    """Mantiene los campos textuales y comparte la interpretación entre disparadores."""
    estado_http, codigo_http = ESTADOS_HTTP[resultado['estado']]
    data = {
        'status': estado_http,
        campo_mensaje: resultado['mensaje'],
        'resultado_ia': resultado,
    }
    if mensaje_ingesta is not None:
        data['mensaje_ingesta'] = mensaje_ingesta
    return data, codigo_http
