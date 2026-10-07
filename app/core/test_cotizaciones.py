import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from core.services import cotizaciones


class CotizacionesTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.cache = MagicMock()
        self.cache.get.side_effect = lambda key: self.values.get(key)
        self.cache.set.side_effect = lambda key, value, timeout: self.values.update({key: value})

    def sample(self, moneda='USD', casa='oficial'):
        return {'moneda': moneda, 'casa': casa, 'compra': 100, 'venta': 110,
                'fechaActualizacion': '2026-10-07T13:00:00Z'}

    def response(self, request, timeout):
        moneda, casa = next((m, c) for url, m, c in cotizaciones.FUENTES.values() if url == request.full_url)
        result = MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps(self.sample(moneda, casa)).encode()
        return result

    def test_cache_evita_repetir_consultas(self):
        with patch.object(cotizaciones, 'cache', self.cache), patch.object(cotizaciones, 'urlopen', side_effect=self.response) as fetch:
            first = cotizaciones.obtener_cotizaciones()
            second = cotizaciones.obtener_cotizaciones()
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(first['status'], 'success')
        self.cache.set.assert_any_call(cotizaciones.CACHE_KEY, first, 300)

    def test_falla_una_moneda_conserva_las_otras(self):
        def fetch(request, timeout):
            if '/blue' in request.full_url:
                raise URLError('Unavailable')
            return self.response(request, timeout)
        with patch.object(cotizaciones, 'cache', self.cache), patch.object(cotizaciones, 'urlopen', side_effect=fetch):
            result = cotizaciones.obtener_cotizaciones()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['data'][0]['compra'], 100)
        self.assertIsNone(result['data'][1]['compra'])
        self.assertEqual(result['data'][2]['moneda'], 'BRL')

    def test_respaldo_conserva_fecha_y_se_marca_desactualizado(self):
        original = cotizaciones.validar_cotizacion(self.sample(), 'USD', 'oficial')
        self.values[cotizaciones.CACHE_KEY + ':oficial'] = original
        with patch.object(cotizaciones, 'cache', self.cache), patch.object(cotizaciones, 'urlopen', side_effect=URLError('Offline')):
            result = cotizaciones._consultar(('oficial', cotizaciones.FUENTES['oficial']))
        self.assertTrue(result['stale'])
        self.assertEqual(result['fechaActualizacion'], original['fechaActualizacion'])

    def test_rechaza_valores_invalidos(self):
        for value in [True, None, 0, -1, float('nan'), float('inf'), '100']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                cotizaciones.validar_cotizacion({**self.sample(), 'compra': value}, 'USD', 'oficial')

    def test_rechaza_moneda_o_fecha_incorrecta(self):
        for changes in [{'moneda': 'BRL'}, {'casa': 'blue'}, {'fechaActualizacion': 'invalid'}, {'fechaActualizacion': '2026-10-07T13:00:00'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                cotizaciones.validar_cotizacion({**self.sample(), **changes}, 'USD', 'oficial')
