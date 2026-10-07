"""Consulta de cotizaciones públicas; nunca modifica la base de datos."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.utils.dateparse import parse_datetime

FUENTES = {
    'oficial': ('https://dolarapi.com/v1/dolares/oficial', 'USD', 'oficial'),
    'blue': ('https://dolarapi.com/v1/dolares/blue', 'USD', 'blue'),
    'real': ('https://dolarapi.com/v1/cotizaciones/brl', 'BRL', 'oficial'),
}
CACHE_KEY = 'trendwatch:cotizaciones:v1'


def validar_cotizacion(data, moneda, casa):
    if not isinstance(data, dict) or data.get('moneda') != moneda or data.get('casa') != casa:
        raise ValueError('Moneda o mercado inesperado')
    for campo in ('compra', 'venta'):
        valor = data.get(campo)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
            raise ValueError('Cotización inválida')
    fecha = data.get('fechaActualizacion')
    if not isinstance(fecha, str) or not parse_datetime(fecha) or parse_datetime(fecha).tzinfo is None:
        raise ValueError('Fecha de actualización inválida')
    return {campo: data[campo] for campo in ('compra', 'venta', 'fechaActualizacion', 'moneda')}


def _consultar(item):
    clave, (url, moneda, casa) = item
    respaldo_key = CACHE_KEY + ':' + clave
    try:
        request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'TrendWatchLitoral/1.0'})
        with urlopen(request, timeout=6) as response:
            valor = validar_cotizacion(json.loads(response.read(65536)), moneda, casa)
        cache.set(respaldo_key, valor, 86400)
        return {'key': clave, **valor, 'stale': False}
    except (URLError, OSError, ValueError, TypeError, OverflowError):
        respaldo = cache.get(respaldo_key)
        if respaldo:
            return {'key': clave, **respaldo, 'stale': True}
        return {'key': clave, 'moneda': moneda, 'compra': None, 'venta': None,
                'fechaActualizacion': None, 'stale': False}


def obtener_cotizaciones():
    guardadas = cache.get(CACHE_KEY)
    if guardadas is not None:
        return guardadas
    with ThreadPoolExecutor(max_workers=3) as executor:
        data = list(executor.map(_consultar, FUENTES.items()))
    completas = all(item['compra'] is not None and not item['stale'] for item in data)
    resultado = {'status': 'success' if completas else 'partial', 'source': 'DolarAPI',
                 'currency': 'ARS', 'data': data}
    # Una respuesta incompleta se reintenta antes; no se inventan valores.
    cache.set(CACHE_KEY, resultado, 300 if completas else 60)
    return resultado
