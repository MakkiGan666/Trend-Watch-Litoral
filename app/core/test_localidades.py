import unittest

from core.localidades import departamento_de_ubicacion


class DepartamentoDeUbicacionTests(unittest.TestCase):
    def test_municipio_se_asocia_al_departamento(self):
        self.assertEqual(departamento_de_ubicacion('Posadas'), 'capital')
        self.assertEqual(departamento_de_ubicacion('Puerto Iguazú'), 'iguazu')
        self.assertEqual(departamento_de_ubicacion('Puerto Rico'), 'libertador')

    def test_tildes_mayusculas_y_provincia(self):
        self.assertEqual(departamento_de_ubicacion('  GARUPA, Misiones '), 'capital')
        self.assertEqual(departamento_de_ubicacion('OBERA'), 'obera')

    def test_recorte_existente_de_la_ia(self):
        self.assertEqual(departamento_de_ubicacion('Aristóbulo del Valle'[:18]), 'cainguas')
        self.assertEqual(departamento_de_ubicacion('Bernardo de Irigoyen'[:18]), 'belgrano')

    def test_nombre_ambiguo_no_se_asigna(self):
        # Guaraní es municipio de Oberá y también nombre de otro departamento.
        self.assertIsNone(departamento_de_ubicacion('Guaraní'))
        self.assertEqual(departamento_de_ubicacion('Departamento Guaraní'), 'guarani')
        self.assertEqual(departamento_de_ubicacion('El Soberbio'), 'guarani')

    def test_no_se_infiere_por_fragmentos(self):
        for nombre in ['', None, 'Misiones', 'Buenos Aires', 'Noticias de Posadas']:
            with self.subTest(nombre=nombre):
                self.assertIsNone(departamento_de_ubicacion(nombre))


if __name__ == '__main__':
    unittest.main()
