"""Ejercita el servicio real con el ORM simulado del arnés de Fase 1.2."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fase1_2'))
import test_unit as arnes


class PersistenciaSinCategoriaTests(unittest.TestCase):
    def setUp(self):
        self.fixture = arnes.ServicioTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_propuesta_no_confirmada_se_guarda_sin_vincular(self):
        s = self.fixture.s
        s.clasificar_lote.side_effect = lambda noticias, **kw: [
            {'categoria': 'Sociedad', 'departamento': '', 'confirmada': False} for _ in noticias]
        resultado = self.fixture.rss([('Título', arnes.URL, 'Resumen')])
        self.assertEqual((resultado['status'], resultado['capturados'], resultado['sin_categoria']), ('EXITO', 1, 1))
        self.assertEqual(resultado['categorias'], {})
        s.vincular_categoria_por_nombre.assert_not_called()

    def test_confirmacion_ausente_no_se_infiere(self):
        s = self.fixture.s
        s.clasificar_lote.side_effect = lambda noticias, **kw: [
            {'categoria': 'Sociedad', 'departamento': ''} for _ in noticias]
        resultado = self.fixture.rss([('Título', arnes.URL, 'Resumen')])
        self.assertEqual(resultado['sin_categoria'], 1)
        s.vincular_categoria_por_nombre.assert_not_called()

    def test_fallo_posterior_conserva_contador_sin_categoria(self):
        s = self.fixture.s
        s.clasificar_lote.side_effect = lambda noticias, **kw: [
            {'categoria': 'Sociedad', 'departamento': '', 'confirmada': False} for _ in noticias]
        s.Publicacion.objects.create.side_effect = [MagicMock(), RuntimeError('fallo simulado')]
        resultado = self.fixture.rss([('Uno', arnes.URL, 'Resumen'), ('Dos', arnes.URL + '2', 'Resumen')])
        self.assertEqual((resultado['estado'], resultado['capturados'], resultado['sin_categoria']), ('PARCIAL', 1, 1))
        self.assertEqual(resultado['categorias'], {})
