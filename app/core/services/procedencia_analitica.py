from django.utils import timezone

from core.models import ResultadoAnaliticoPublicacion


Metodo = ResultadoAnaliticoPublicacion.Metodo
Evidencia = ResultadoAnaliticoPublicacion.Evidencia


def procedencia(metodo, version, evidencia=Evidencia.CUERPO):
    return {
        'metodo_analisis': metodo,
        'version_analizador': version,
        'fecha_procesamiento': timezone.now(),
        'tipo_evidencia': evidencia,
    }


def procedencia_sentimiento_gemini(modelo):
    return procedencia(Metodo.GEMINI, f'{modelo}/sentimiento-v1')
