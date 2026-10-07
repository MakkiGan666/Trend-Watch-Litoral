from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.roles import PERMISOS_ROLES


class Command(BaseCommand):
    help = 'Configura los permisos exactos de Lector, Analista y Administrador.'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', help='Username existente al que asignar un rol.')
        parser.add_argument('--rol', choices=tuple(PERMISOS_ROLES))

    @transaction.atomic
    def handle(self, *args, **options):
        if bool(options['usuario']) != bool(options['rol']):
            raise CommandError('--usuario y --rol deben indicarse juntos.')
        permisos = {
            f'{p.content_type.app_label}.{p.codename}': p
            for p in Permission.objects.select_related('content_type')
        }
        faltantes = set().union(*PERMISOS_ROLES.values()) - permisos.keys()
        if faltantes:
            raise CommandError('Ejecute migrate primero. Faltan permisos: ' + ', '.join(sorted(faltantes)))
        for nombre, definidos in PERMISOS_ROLES.items():
            grupo, _ = Group.objects.get_or_create(name=nombre)
            grupo.permissions.set([permisos[p] for p in sorted(definidos)])
        if options['usuario']:
            try:
                usuario = get_user_model().objects.get(username=options['usuario'])
            except get_user_model().DoesNotExist as exc:
                raise CommandError('El usuario indicado no existe.') from exc
            if usuario.is_superuser:
                raise CommandError('No se reasignan superusuarios con este comando.')
            usuario.groups.set([Group.objects.get(name=options['rol'])])
            usuario.user_permissions.clear()
            usuario.is_staff = options['rol'] == 'Administrador'
            usuario.save(update_fields=['is_staff'])
        self.stdout.write(self.style.SUCCESS('Roles configurados.'))
