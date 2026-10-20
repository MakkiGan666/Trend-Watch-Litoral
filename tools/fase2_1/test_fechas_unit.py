"""Pruebas sin Django ni Docker: presentación temporal y contrato ORM del orden."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from core.fechas import datos_fecha, fecha_efectiva


def publicacion(publicada=None, capturada=None, fuente='Manual'):
    return SimpleNamespace(fecha_publicacion=publicada, fecha_captura=capturada, fuente=fuente)


class FechasTests(unittest.TestCase):
    def test_prefiere_publicacion_a_captura_reciente(self):
        vieja = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)
        p = publicacion(vieja, datetime(2026, 10, 20, tzinfo=timezone.utc))
        self.assertEqual(fecha_efectiva(p), vieja)
        self.assertEqual(datos_fecha(p)['fecha_origen'], 'publicacion')

    def test_sin_fecha_del_medio_utiliza_captura(self):
        p = publicacion(capturada=datetime(2026, 10, 20, 12, tzinfo=timezone.utc))
        self.assertEqual(fecha_efectiva(p), p.fecha_captura)
        self.assertEqual(datos_fecha(p)['fecha_origen'], 'captura')

    def test_ambas_nulas_explicitas(self):
        self.assertIsNone(fecha_efectiva(publicacion()))
        self.assertEqual(datos_fecha(publicacion()), {'fecha_efectiva': None, 'fecha_dia': None,
                                                     'fecha_precision': None, 'fecha_origen': None})

    def test_limites_de_dia_en_buenos_aires(self):
        for hora, esperado in ((2, '2026-10-19'), (3, '2026-10-20'), (23, '2026-10-20')):
            with self.subTest(hora=hora):
                p = publicacion(datetime(2026, 10, 20, hora, tzinfo=timezone.utc))
                self.assertEqual(datos_fecha(p)['fecha_dia'], esperado)

    def test_archivo_no_expone_hora_artificial_en_fecha_efectiva(self):
        p = publicacion(datetime(2026, 9, 1, 12, tzinfo=timezone.utc), fuente='El Territorio (Archivo)')
        self.assertEqual(datos_fecha(p)['fecha_efectiva'], '2026-09-01')
        self.assertEqual(datos_fecha(p)['fecha_precision'], 'dia')
        self.assertEqual(p.fecha_publicacion.hour, 12)

    def test_archivo_sin_fecha_medio_conserva_precision_de_captura(self):
        p = publicacion(capturada=datetime(2026, 10, 20, 12, tzinfo=timezone.utc), fuente='El Territorio (Archivo)')
        self.assertEqual(datos_fecha(p)['fecha_precision'], 'instante')
        self.assertEqual(datos_fecha(p)['fecha_origen'], 'captura')

    def test_rss_con_zona_conserva_instante(self):
        fecha = datetime.fromisoformat('2026-10-20T12:34:56.123456+02:00')
        dato = datos_fecha(publicacion(fecha, fuente='El Territorio (Misiones)'))
        self.assertEqual(datetime.fromisoformat(dato['fecha_efectiva']), fecha)
        self.assertEqual(dato['fecha_precision'], 'instante')

    def test_naive_no_depende_de_zona_del_host(self):
        fecha = datetime(2026, 10, 20, 0)
        self.assertEqual(datos_fecha(publicacion(fecha))['fecha_efectiva'], '2026-10-20T00:00:00-03:00')
        self.assertIsNone(fecha.tzinfo)

    def test_helper_orm_usa_coalesce_y_pk_con_nulls_last(self):
        arbol = ast.parse((ROOT / 'app/core/views.py').read_text())
        funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == '_orden_por_publicacion')
        coalesce = Mock()
        contexto = {'Coalesce': coalesce}
        exec(compile(ast.Module(body=[funcion], type_ignores=[]), '<orden-real>', 'exec'), contexto)
        orden = contexto['_orden_por_publicacion']()
        coalesce.assert_called_once_with('fecha_publicacion', 'fecha_captura')
        coalesce.return_value.desc.assert_called_once_with(nulls_last=True)
        self.assertEqual(orden, (coalesce.return_value.desc.return_value, '-id_publicacion_api'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
