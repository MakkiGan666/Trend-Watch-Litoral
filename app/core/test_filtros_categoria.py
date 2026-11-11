from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Categoria, Publicacion
from core.services.clasificacion import vincular_categoria
from core.fechas import ZONA_LOCAL


class FiltrosCategoriaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categoria = Categoria.objects.create(nombre_categoria='Salud')
        cls.url = reverse('publicaciones_categoria', args=['salud'])
        casos = [
            ('Hospital de Posadas amplía horarios', datetime(2026, 1, 10, 12, tzinfo=dt_timezone.utc), None),
            ('Clínica de Oberá abre consultorios', None, datetime(2026, 3, 20, 12, tzinfo=dt_timezone.utc)),
            ('Jornada de vacunación en Eldorado', datetime(2026, 3, 21, 12, tzinfo=dt_timezone.utc), None),
        ]
        cls.publicaciones = []
        for numero, (titulo, publicada, capturada) in enumerate(casos):
            datos = {
                'hash_origen': f'filtro-categoria-{numero}', 'titulo': titulo,
                'contenido': 'La comunidad recibe atención de salud.',
                'fecha_publicacion': publicada,
            }
            if capturada:
                datos['fecha_captura'] = capturada
            publicacion = Publicacion.objects.create(**datos)
            vincular_categoria(publicacion, cls.categoria)
            cls.publicaciones.append(publicacion)

    def test_orden_y_fecha_se_aplican_antes_de_paginar(self):
        recientes = self.client.get(self.url)
        antiguas = self.client.get(self.url, {'orden': 'antiguas'})
        self.assertEqual([p.pk for p in recientes.context['pagina']], [p.pk for p in reversed(self.publicaciones)])
        self.assertEqual([p.pk for p in antiguas.context['pagina']], [p.pk for p in self.publicaciones])

        captura = self.client.get(self.url, {'fecha': '2026-03-20'})
        self.assertEqual([p.pk for p in captura.context['pagina']], [self.publicaciones[1].pk])
        self.assertContains(captura, 'value="2026-03-20"')

    def test_fecha_invalida_y_limite_de_hoy(self):
        invalida = self.client.get(self.url, {'fecha': '2025-12-31'})
        self.assertEqual(invalida.context['pagina'].paginator.count, 0)
        self.assertContains(invalida, 'La fecha debe ser de 2026 en adelante.')
        manana = timezone.localtime(timezone.now(), ZONA_LOCAL).date() + timedelta(days=1)
        futura = self.client.get(self.url, {'fecha': manana.isoformat()})
        self.assertEqual(futura.context['pagina'].paginator.count, 0)
        self.assertContains(futura, 'La fecha no puede ser posterior a hoy.')
        self.assertContains(futura, f'data-calendar-max-date="{(manana - timedelta(days=1)).isoformat()}"')
        self.assertNotContains(futura, 'id="category-search"')

    def test_paginacion_conserva_filtros(self):
        base = datetime(2026, 4, 1, 12, tzinfo=dt_timezone.utc)
        for numero in range(26):
            publicacion = Publicacion.objects.create(
                hash_origen=f'filtro-pagina-{numero}',
                titulo=f'Salud comunitaria número {numero} en Misiones',
                contenido='Salud comunitaria para toda la provincia.',
                fecha_publicacion=base,
            )
            vincular_categoria(publicacion, self.categoria)
        pagina = self.client.get(self.url, {'fecha': '2026-04-01', 'orden': 'antiguas'})
        self.assertEqual(pagina.context['pagina'].paginator.count, 26)
        self.assertContains(pagina, 'fecha=2026-04-01&amp;orden=antiguas&amp;pagina=2')
        siguiente = self.client.get(self.url, {'fecha': '2026-04-01', 'orden': 'antiguas', 'pagina': 2})
        self.assertEqual(len(siguiente.context['pagina']), 2)
