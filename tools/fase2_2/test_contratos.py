"""Contratos reales de clasificación/lectura, sin Django, red ni base de datos."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))
from core.categorias import datos_categorias


def cargar_clasificador():
    modelo = ModuleType('core.models')
    for nombre in ('Categoria', 'Tema', 'PublicacionTema'):
        setattr(modelo, nombre, MagicMock())
    spec = importlib.util.spec_from_file_location('clasificacion_real_test', ROOT / 'app/core/services/clasificacion.py')
    modulo = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'core.models': modelo}):
        spec.loader.exec_module(modulo)
    return modulo


class ClasificacionTests(unittest.TestCase):
    def setUp(self):
        for objetivo in ('socket.socket.connect', 'socket.getaddrinfo'):
            p = patch(objetivo, side_effect=AssertionError('Red prohibida'))
            p.start()
            self.addCleanup(p.stop)
        self.c = cargar_clasificador()

    def test_fallback_sociedad_no_es_confirmacion(self):
        resultado = self.c.clasificar_lote([{'titulo': 'Lorem ipsum', 'contenido': 'dolor sit amet'}], usar_ia=False)[0]
        self.assertEqual(resultado['categoria'], 'Sociedad')  # compatibilidad interna
        self.assertFalse(resultado['confirmada'])

    def test_sociedad_con_evidencia_se_confirma(self):
        resultado = self.c.clasificar_lote([{'titulo': 'Vecinos del barrio ayudan a la comunidad'}], usar_ia=False)[0]
        self.assertEqual(resultado['categoria'], 'Sociedad')
        self.assertTrue(resultado['confirmada'])

    def test_empate_no_confirma_ninguna_categoria(self):
        resultado = self.c.clasificar_lote([{'titulo': 'Hospital y escuela'}], usar_ia=False)[0]
        self.assertFalse(resultado['confirmada'])

    def test_seccion_especifica_confirma_sin_ia(self):
        with patch.object(self.c, '_clasificar_con_ia', side_effect=AssertionError('No llamar IA')):
            dato = self.c.clasificar_lote([{'titulo': 'Nota', 'seccion': 'agro'}], usar_ia=False)[0]
        self.assertEqual(dato['categoria'], 'Economía')
        self.assertTrue(dato['confirmada'])

    def test_seccion_general_no_es_categoria(self):
        for seccion in ('misiones', 'actualidad', 'la-region', 'pais-y-mundo', 'desconocida'):
            with self.subTest(seccion=seccion):
                dato = self.c.clasificar_lote([{'titulo': 'Lorem ipsum', 'seccion': seccion}], usar_ia=False)[0]
                self.assertFalse(dato['confirmada'])

    def test_ia_parcial_deja_pendientes_las_no_resueltas(self):
        with patch.object(self.c, '_clasificar_con_ia', return_value={0: 'Salud'}):
            datos = self.c.clasificar_lote([{'titulo': 'Lorem ipsum'}, {'titulo': 'Dolor sit amet'}])
        self.assertEqual([d['confirmada'] for d in datos], [True, False])
        self.assertEqual(datos[0]['metodo'], 'ia')

    def test_json_rechaza_claves_duplicadas(self):
        for raw in ('[{"indice":0,"categoria":"Salud","categoria":"Sociedad"}]',
                    '[{"indice":0,"indice":1,"categoria":"Salud"}]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.c._validar_respuesta(raw, {0, 1})

    def test_respuesta_invalida_no_es_confirmacion(self):
        for datos in ([{'indice': True, 'categoria': 'Salud'}], [{'indice': 3, 'categoria': 'Salud'}],
                      [{'indice': 0, 'categoria': 'Agro'}], [{'indice': 0, 'categoria': ['Salud']}],
                      [{'indice': 0, 'categoria': 'Salud'}, {'indice': 0, 'categoria': 'Turismo'}],
                      {'categorias': ['salud']}, [{'indice': 0, 'categoria': 'Salud', 'confianza': 1}]):
            with self.subTest(datos=datos), self.assertRaises(ValueError):
                self.c._validar_respuesta(json.dumps(datos), {0})

    def test_respuesta_valida_y_vacia(self):
        self.assertEqual(self.c._validar_respuesta('[{"indice":0,"categoria":"Salud"}]', {0}), {0: 'Salud'})
        self.assertEqual(self.c._validar_respuesta('[]', {0}), {})


class LecturaTests(unittest.TestCase):
    def publicacion(self, fuente, *categorias):
        temas = [SimpleNamespace(id_categoria=SimpleNamespace(pk=pk, nombre_categoria=nombre))
                 for pk, nombre in categorias]
        return SimpleNamespace(fuente=fuente, temas=SimpleNamespace(all=lambda: temas))

    def test_multiples_relaciones_se_conservan_y_deduplican(self):
        p = self.publicacion('El Territorio (Archivo)', (2, 'Salud'), (1, 'Turismo'), (2, 'Salud'))
        dato = datos_categorias(p)
        self.assertEqual(dato['categorias'], ['Turismo', 'Salud'])
        self.assertEqual(dato['categorias_detalle'], [{'id': 1, 'nombre': 'Turismo'}, {'id': 2, 'nombre': 'Salud'}])
        self.assertEqual(dato['categorias_origen'], 'asociaciones')
        self.assertEqual(dato['seccion_origen'], 'Archivo')

    def test_seccion_legacy_no_es_asociacion(self):
        dato = datos_categorias(self.publicacion('El Territorio (Misiones)'))
        self.assertEqual(dato['categorias'], ['Misiones'])
        self.assertEqual(dato['categorias_detalle'], [])
        self.assertEqual(dato['categorias_origen'], 'seccion')

    def test_sin_datos_no_inventa_sociedad(self):
        dato = datos_categorias(self.publicacion('Manual'))
        self.assertEqual(dato['categorias'], [])
        self.assertEqual(dato['categorias_origen'], 'sin_datos')

    def test_categoria_ajena_y_ids_duplicados_por_nombre_no_se_reescriben(self):
        dato = datos_categorias(self.publicacion('Manual', (7, 'Misiones'), (8, 'Misiones')))
        self.assertEqual(dato['categorias'], ['Misiones'])
        self.assertEqual(len(dato['categorias_detalle']), 2)
        self.assertNotIn('codigo', dato['categorias_detalle'][0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
