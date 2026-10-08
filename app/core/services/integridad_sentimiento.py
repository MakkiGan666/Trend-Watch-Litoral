import math

from core.models import Sentimiento


class ConflictoSentimiento(ValueError):
    pass


def validar_numero(valor, campo, minimo, maximo):
    if (type(valor) not in (int, float)
            or not minimo <= valor <= maximo
            or not math.isfinite(valor)):
        raise ValueError(f"{campo} debe ser un número finito entre {minimo} y {maximo}.")
    return float(valor)


def confianza_desde_porcentaje(analisis):
    if not isinstance(analisis, dict) or 'confidence_score' not in analisis:
        raise ValueError('El análisis local debe incluir confidence_score.')
    return validar_numero(analisis['confidence_score'], 'confidence_score', 0, 100) / 100


def sentimiento_unico(publicacion):
    """Consultar después de bloquear Publicacion dentro de la transacción del escritor."""
    sentimientos = list(Sentimiento.objects.filter(id_publicacion_api=publicacion)[:2])
    if len(sentimientos) > 1:
        raise ConflictoSentimiento('Conflicto: sentimientos_multiples.')
    return sentimientos[0] if sentimientos else None


def guardar_sentimiento_local(publicacion, polaridad, confianza):
    """El llamador mantiene el bloqueo de Publicacion hasta guardar también su estado."""
    sentimiento = sentimiento_unico(publicacion)
    valores = {
        'polaridad': validar_numero(polaridad, 'polaridad', -1, 1),
        'confianza': validar_numero(confianza, 'confianza', 0, 1),
    }
    if sentimiento is None:
        return Sentimiento.objects.create(id_publicacion_api=publicacion, **valores)
    for campo, valor in valores.items():
        setattr(sentimiento, campo, valor)
    sentimiento.save(update_fields=['polaridad', 'confianza'])
    return sentimiento
