"""Crea actividad de demostración identificable para publicaciones existentes."""

import random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import ClicPublicacion, Comentario, Publicacion, ValoracionPublicacion


PREFIJO_USUARIO = 'demo_sim_'
PREFIJO_COMENTARIO = '[Simulación]'
SENTIMIENTOS = tuple(ValoracionPublicacion.Sentimiento.values)
PLANTILLAS_COMENTARIO = (
    'Leí la nota sobre «{titulo}». ¿Cómo sigue este tema?',
    'Che, ¿alguien leyó lo de «{titulo}»? Me interesa ver qué novedades aparecen.',
    'Sobre «{titulo}», prefiero esperar un poco más de información. ¿Ustedes qué opinan?',
    'Me quedé pensando en la noticia sobre «{titulo}». Si alguien tiene más contexto, lo leo.',
)


def texto_comentario_simulado(titulo, indice):
    titular = ' '.join((titulo or '').split())
    return f'{PREFIJO_COMENTARIO} {PLANTILLAS_COMENTARIO[indice % len(PLANTILLAS_COMENTARIO)].format(titulo=titular)}'


class Command(BaseCommand):
    help = 'Puebla noticias locales con cuentas, votos, comentarios y clics sintéticos.'

    def add_arguments(self, parser):
        parser.add_argument('--usuarios', type=int, default=10000)
        parser.add_argument('--votos-por-publicacion', type=int, default=4)
        parser.add_argument('--comentarios-por-publicacion', type=int, default=1)
        parser.add_argument('--clics-por-publicacion', type=int, default=6)
        parser.add_argument('--limite', type=int, default=0, help='Máximo de noticias; 0 incluye todas.')
        parser.add_argument('--desde-id', type=int, default=0)
        parser.add_argument('--tamano-lote', type=int, default=100)
        parser.add_argument('--semilla', type=int, default=20261106)
        parser.add_argument('--aplicar', action='store_true')

    def handle(self, *args, **options):
        usuarios_objetivo = options['usuarios']
        votos_objetivo = options['votos_por_publicacion']
        comentarios_objetivo = options['comentarios_por_publicacion']
        clics_objetivo = options['clics_por_publicacion']
        limite = options['limite']
        cursor = options['desde_id']
        tamano_lote = options['tamano_lote']

        if not 1 <= usuarios_objetivo <= 10000:
            raise CommandError('--usuarios debe estar entre 1 y 10000.')
        if not 1 <= votos_objetivo <= 100 or not 0 <= comentarios_objetivo <= 20:
            raise CommandError('Usá 1..100 votos y 0..20 comentarios por publicación.')
        if not 0 <= clics_objetivo <= 100:
            raise CommandError('--clics-por-publicacion debe estar entre 0 y 100.')
        if limite < 0 or cursor < 0 or not 1 <= tamano_lote <= 500:
            raise CommandError('Usá --limite >= 0, --desde-id >= 0 y --tamano-lote entre 1 y 500.')

        if get_user_model().USERNAME_FIELD != 'username':
            raise CommandError('El comando requiere un modelo de usuario con campo username.')

        publicaciones = Publicacion.objects.filter(pk__gt=cursor).order_by('pk')
        if limite:
            publicaciones = publicaciones[:limite]
        publicaciones_ids = list(publicaciones.values_list('pk', flat=True))
        if not publicaciones_ids:
            self.stdout.write('No hay publicaciones para procesar.')
            return

        nombres = [f'{PREFIJO_USUARIO}{numero:05d}' for numero in range(1, usuarios_objetivo + 1)]
        usuarios_existentes = {
            usuario.username: usuario
            for usuario in get_user_model().objects.filter(username__in=nombres).only(
                'pk', 'username', 'is_active', 'is_staff', 'is_superuser', 'password',
            )
        }
        for nombre, usuario in usuarios_existentes.items():
            if usuario.is_active or usuario.is_staff or usuario.is_superuser:
                raise CommandError(f'La cuenta reservada {nombre} existe y no es una cuenta sintética inactiva.')
            if usuario.has_usable_password():
                raise CommandError(f'La cuenta reservada {nombre} ya tiene una contraseña utilizable.')

        cantidad_actual = len(usuarios_existentes)
        eventos_maximos = {
            'votos': len(publicaciones_ids) * votos_objetivo,
            'comentarios': len(publicaciones_ids) * comentarios_objetivo,
            'clics': len(publicaciones_ids) * clics_objetivo,
        }
        self.stdout.write(
            f'Publicaciones: {len(publicaciones_ids)} (último ID {publicaciones_ids[-1]}). '
            f'Cuentas demo: {cantidad_actual}/{usuarios_objetivo}; '
            f'objetivo de interacciones por noticia: votos={votos_objetivo}, '
            f'comentarios={comentarios_objetivo}, clics={clics_objetivo}.'
        )
        self.stdout.write(
            'Máximo a completar si faltan registros: ' +
            ', '.join(f'{nombre}={cantidad}' for nombre, cantidad in eventos_maximos.items())
        )
        self.stdout.write(
            'Los comentarios y votos se identificarán como sintéticos; las cuentas no podrán iniciar sesión.'
        )
        if not options['aplicar']:
            self.stdout.write('Previsualización: no se escribió nada. Añadí --aplicar para ejecutar en desarrollo.')
            return
        if not settings.DEBUG:
            raise CommandError('Por seguridad, --aplicar solo está permitido con DEBUG=True.')

        faltantes = [nombre for nombre in nombres if nombre not in usuarios_existentes]
        modelo_usuario = get_user_model()
        nuevas_cuentas = []
        for nombre in faltantes:
            usuario = modelo_usuario(
                username=nombre, is_active=False, is_staff=False, is_superuser=False,
            )
            usuario.set_unusable_password()
            nuevas_cuentas.append(usuario)
        if nuevas_cuentas:
            with transaction.atomic():
                modelo_usuario.objects.bulk_create(nuevas_cuentas, batch_size=500)

        usuarios = list(
            modelo_usuario.objects.filter(username__in=nombres).order_by('username')
        )
        if len(usuarios) != usuarios_objetivo:
            raise CommandError(
                f'Se esperaban {usuarios_objetivo} cuentas sintéticas y se encontraron {len(usuarios)}.'
            )
        ids_usuarios = [usuario.pk for usuario in usuarios]
        creados = {'cuentas': len(nuevas_cuentas), 'votos': 0, 'comentarios': 0, 'clics': 0}
        ahora = timezone.now()

        for inicio in range(0, len(publicaciones_ids), tamano_lote):
            ids_lote = publicaciones_ids[inicio:inicio + tamano_lote]
            noticias = list(Publicacion.objects.filter(pk__in=ids_lote).only('pk', 'titulo').order_by('pk'))
            votos_existentes = {}
            for noticia_id, usuario_id in ValoracionPublicacion.objects.filter(
                publicacion_id__in=ids_lote,
                usuario__username__startswith=PREFIJO_USUARIO,
            ).values_list('publicacion_id', 'usuario_id'):
                votos_existentes.setdefault(noticia_id, set()).add(usuario_id)
            comentarios_existentes = {}
            for noticia_id, usuario_id in Comentario.objects.filter(
                publicacion_id__in=ids_lote,
                autor__username__startswith=PREFIJO_USUARIO,
            ).values_list('publicacion_id', 'autor_id'):
                comentarios_existentes.setdefault(noticia_id, set()).add(usuario_id)
            clics_existentes = {}
            for noticia_id, usuario_id in ClicPublicacion.objects.filter(
                publicacion_id__in=ids_lote,
                usuario__username__startswith=PREFIJO_USUARIO,
            ).values_list('publicacion_id', 'usuario_id'):
                clics_existentes.setdefault(noticia_id, set()).add(usuario_id)

            nuevos_votos = []
            nuevos_comentarios = []
            nuevos_clics = []
            for noticia in noticias:
                noticia_id = noticia.pk
                votos = votos_existentes.setdefault(noticia_id, set())
                comentarios = comentarios_existentes.setdefault(noticia_id, set())
                clics = clics_existentes.setdefault(noticia_id, set())

                faltan_votos = max(0, votos_objetivo - len(votos))
                faltan_comentarios = max(0, comentarios_objetivo - len(comentarios))
                faltan_clics = max(0, clics_objetivo - len(clics))

                def seleccionar(cantidad, existentes, desplazamiento):
                    disponibles = [usuario_id for usuario_id in ids_usuarios if usuario_id not in existentes]
                    rng = random.Random(options['semilla'] + noticia_id * 1009 + desplazamiento)
                    if len(disponibles) < cantidad:
                        raise CommandError(
                            f'No hay suficientes cuentas sintéticas para la publicación #{noticia_id}.'
                        )
                    return rng.sample(disponibles, cantidad)

                elegidos_voto = seleccionar(faltan_votos, votos, 1)
                for indice, usuario_id in enumerate(elegidos_voto, start=len(votos)):
                    sentimiento = SENTIMIENTOS[
                        (indice + noticia_id + options['semilla']) % len(SENTIMIENTOS)
                    ]
                    nuevos_votos.append(ValoracionPublicacion(
                        publicacion_id=noticia_id,
                        usuario_id=usuario_id,
                        sentimiento=sentimiento,
                    ))
                    votos.add(usuario_id)

                elegidos_comentario = seleccionar(faltan_comentarios, comentarios, 2)
                for indice, usuario_id in enumerate(elegidos_comentario, start=len(comentarios)):
                    nuevos_comentarios.append(Comentario(
                        publicacion_id=noticia_id,
                        autor_id=usuario_id,
                        texto=texto_comentario_simulado(
                            noticia.titulo,
                            indice + noticia_id + options['semilla'],
                        ),
                        estado=Comentario.Estado.PUBLICADO,
                    ))
                    comentarios.add(usuario_id)

                elegidos_clic = seleccionar(faltan_clics, clics, 3)
                nuevos_clics.extend(
                    ClicPublicacion(
                        publicacion_id=noticia_id,
                        usuario_id=usuario_id,
                        ultima_visita=ahora,
                    )
                    for usuario_id in elegidos_clic
                )
                clics.update(elegidos_clic)

            with transaction.atomic():
                ValoracionPublicacion.objects.bulk_create(nuevos_votos, batch_size=500)
                Comentario.objects.bulk_create(nuevos_comentarios, batch_size=500)
                ClicPublicacion.objects.bulk_create(nuevos_clics, batch_size=500)
            creados['votos'] += len(nuevos_votos)
            creados['comentarios'] += len(nuevos_comentarios)
            creados['clics'] += len(nuevos_clics)
            self.stdout.write(
                f'Lote hasta #{ids_lote[-1]}: votos={len(nuevos_votos)}, '
                f'comentarios={len(nuevos_comentarios)}, clics={len(nuevos_clics)}.'
            )

        self.stdout.write(self.style.SUCCESS(
            'Datos de demostración agregados: ' +
            ', '.join(f'{nombre}={cantidad}' for nombre, cantidad in creados.items())
        ))
