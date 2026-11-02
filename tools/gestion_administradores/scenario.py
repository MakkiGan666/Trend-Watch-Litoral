import hashlib
import json
import os
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.admin.models import LogEntry, ADDITION
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection, IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from core.models import Publicacion, RegistroDatos, Comentario, PublicacionGuardada, ValoracionPublicacion

User = get_user_model()
SYNTHETIC_PASSWORD = 'Integration!Synthetic-934Only'

def snapshot():
    result = {}
    for model in apps.get_models():
        if model._meta.app_label not in ('core', 'auth', 'admin'):
            continue
        rows = list(model._base_manager.order_by(model._meta.pk.name).values())
        for row in rows:
            for field in ('password', 'password_hash'):
                if field in row:
                    row[field] = hashlib.sha256(row[field].encode()).hexdigest()
        result[model._meta.label] = rows
    result['memberships'] = list(User.groups.through.objects.order_by('pk').values())
    result['direct_permissions'] = list(User.user_permissions.through.objects.order_by('pk').values())
    result['group_permissions'] = list(Group.permissions.through.objects.order_by('pk').values())
    return json.loads(json.dumps(result, default=str))

def perms(group):
    return {f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')}

def check(condition, description):
    assert condition, description
    print('PASS:', description)

if os.environ.get('TW_SCENARIO') == 'seed':
    assert not User.objects.exists(), 'Only seed a newly created empty database'
    call_command('configurar_roles')
    root = User.objects.create_superuser('synthetic_root', password=SYNTHETIC_PASSWORD)
    admins = [User.objects.create_user(f'synthetic_admin{i}', password=SYNTHETIC_PASSWORD, is_staff=True) for i in (1, 2)]
    normal = User.objects.create_user('synthetic_reader', password=SYNTHETIC_PASSWORD)
    individual = User.objects.create_user('synthetic_individual', password=SYNTHETIC_PASSWORD, is_staff=True)
    for user in admins:
        user.groups.add(Group.objects.get(name='Administrador'))
    normal.groups.add(Group.objects.get(name='Usuario'))
    auth_perms = Permission.objects.filter(content_type__app_label='auth')
    Group.objects.get(name='Administrador').permissions.add(*auth_perms)
    admins[1].user_permissions.add(*auth_perms)
    individual.user_permissions.set(Group.objects.get(name='Administrador').permissions.all())
    extra = Group.objects.create(name='HistoricoAdicional')
    extra.permissions.add(Permission.objects.get(content_type__app_label='auth', codename='change_group'))
    admins[1].groups.add(extra, Group.objects.get(name='Usuario'))
    record = RegistroDatos.objects.create(fuentes_api='Sintetica', fecha_ejecucion=timezone.now(), estado='OK', lenguaje='es')
    for i in range(3):
        pub = Publicacion.objects.create(hash_origen=f'{i:064x}', titulo=f'Noticia sintetica {i}', contenido='Contenido de integracion', fuente='Sintetica', id_registro=record)
        Comentario.objects.create(publicacion=pub, autor=normal, texto='Comentario sintetico')
        PublicacionGuardada.objects.create(publicacion=pub, usuario=normal)
        ValoracionPublicacion.objects.create(publicacion=pub, usuario=normal, sentimiento='neutral')
    LogEntry.objects.log_actions(user_id=root.pk, queryset=User.objects.filter(pk=admins[0].pk), action_flag=ADDITION, change_message='Evento sintetico preexistente')
    print('BASELINE_JSON=' + json.dumps(snapshot(), sort_keys=True))
else:
    from core.roles import PERMISOS_ROLES
    before = json.loads(Path('/evidence/baseline.json').read_text())
    check(snapshot() == before, 'estado previo identico al registrado usando main')
    with connection.cursor() as cursor:
        cursor.execute('SELECT version(), PostGIS_Full_Version(), current_database()')
        print('DATABASE:', cursor.fetchone())
    # A missing target fails after group updates: the transaction must undo them.
    try:
        call_command('configurar_roles', usuario='no_existe', rol='Usuario', stdout=StringIO())
    except Exception as error:
        from django.core.management.base import CommandError
        assert isinstance(error, CommandError)
    else:
        raise AssertionError('Expected CommandError')
    check(snapshot() == before, 'fallo del comando revierte tambien cambios de grupos')
    call_command('configurar_roles')
    after = snapshot()
    for name, expected in PERMISOS_ROLES.items():
        check(perms(Group.objects.get(name=name)) == expected, f'permisos exactos {name}: {len(expected)}')
    for key in before:
        if key != 'group_permissions':
            check(after[key] == before[key], f'integridad exacta {key}')
    call_command('configurar_roles')
    check(snapshot() == after, 'segunda ejecucion sin diferencias')
    for user in User.objects.all():
        check(user.check_password(SYNTHETIC_PASSWORD), f'password sintetica valida {user.username}')
    check(User.objects.get(username='synthetic_admin2').has_perm('auth.change_group'), 'permisos individuales y de otros grupos permanecen efectivos')
    for name in ('synthetic_admin1', 'synthetic_admin2', 'synthetic_root'):
        client = Client()
        check(client.post(reverse('login'), {'username': name, 'password': SYNTHETIC_PASSWORD}).status_code == 302, f'login {name}')
        for view in ('publicaciones', 'landing', 'gestion_administradores'):
            check(client.get(reverse(view)).status_code == 200, f'HTTP {name} {view}')
        esperado_dashboard = 200 if name == 'synthetic_root' else 403
        check(client.get(reverse('dashboard')).status_code == esperado_dashboard, f'HTTP {name} dashboard')
        inicio = client.get(reverse('landing')).content.decode()
        check(('id="inicio-indicadores"' in inicio) == (name == 'synthetic_root'), f'indicadores {name}')
        if name != 'synthetic_root':
            for target in User.objects.all():
                for route, payload in (
                    ('auth_user_change', {'is_superuser': 'on'}),
                    ('auth_user_password_change', {'password1': SYNTHETIC_PASSWORD, 'password2': SYNTHETIC_PASSWORD}),
                    ('auth_user_delete', {'post': 'yes'}),
                ):
                    check(client.post(reverse('admin:' + route, args=[target.pk]), payload).status_code == 403, f'rechazo {name} {route} {target.pk}')
            group = Group.objects.get(name='Administrador')
            for route, args, payload in (
                ('auth_group_change', [group.pk], {'permissions': list(Permission.objects.values_list('pk', flat=True)), 'name': group.name}),
                ('auth_user_changelist', [], {'action': 'delete_selected', '_selected_action': User.objects.first().pk, 'post': 'yes'}),
                ('auth_group_changelist', [], {'action': 'delete_selected', '_selected_action': group.pk, 'post': 'yes'}),
            ):
                check(client.post(reverse('admin:' + route, args=args), payload).status_code == 403, f'rechazo {name} {route}')
            for model in ('outstandingtoken', 'blacklistedtoken'):
                url = reverse(f'admin:token_blacklist_{model}_changelist')
                check(client.get(url).status_code == 403, f'JWT rechazado {name} {model}')
        else:
            for model in ('outstandingtoken', 'blacklistedtoken'):
                check(client.get(reverse(f'admin:token_blacklist_{model}_changelist')).status_code == 200, f'JWT tecnico {model}')
        initial = timezone.now()
        data = {'username': name + '_created', 'email': name + '@example.invalid', 'password1': SYNTHETIC_PASSWORD, 'password2': SYNTHETIC_PASSWORD, 'is_superuser': 'on'}
        check(client.post(reverse('gestion_administradores'), data).status_code == 302, f'alta {name}')
        created = User.objects.get(username=data['username'])
        event = LogEntry.objects.get(object_id=str(created.pk), content_type=ContentType.objects.get_for_model(User))
        check(not created.is_superuser and created.is_staff, 'alta ignora privilegios manipulados')
        check(event.user_id == User.objects.get(username=name).pk and event.action_flag == ADDITION and initial <= event.action_time <= timezone.now() and event.object_repr == str(created), 'auditoria responsable cuenta fecha accion')
        check(SYNTHETIC_PASSWORD not in str(event.__dict__) and created.password not in str(event.__dict__), 'evento sin password ni hash')
        data['username'] += '_rollback'
        data['email'] = 'rollback_' + data['email']
        state = snapshot()
        with patch('core.views_administradores.LogEntry.objects.log_actions', side_effect=IntegrityError('synthetic audit failure')):
            check(client.post(reverse('gestion_administradores'), data).status_code == 200, 'fallo auditoria manejado')
        check(snapshot() == state, 'rollback exacto de alta y relaciones ante fallo auditoria')
    for name in ('synthetic_reader', 'synthetic_individual'):
        client = Client()
        client.force_login(User.objects.get(username=name))
        state = snapshot()
        for method in ('get', 'post'):
            check(getattr(client, method)(reverse('gestion_administradores'), {'username': 'forbidden'}).status_code == 403, f'{name} {method} rechazado')
        check(snapshot() == state, 'rechazos no dejan cambios parciales')
    # Confirm historical account/content state after all HTTP probes (login timestamps may change).
    final = snapshot()
    for key in before:
        if key.startswith('core.') or key in ('memberships', 'direct_permissions'):
            if key == 'memberships':
                check(all(row in final[key] for row in before[key]), 'pertenencias historicas conservadas')
            else:
                check(final[key] == before[key], f'persistencia final {key}')
    check(all(row in final['admin.LogEntry'] for row in before['admin.LogEntry']), 'auditoria preexistente conservada')
    for row in before['auth.User']:
        current = next(u for u in final['auth.User'] if u['id'] == row['id'])
        check(all(current[k] == v for k, v in row.items() if k != 'last_login'), 'cuenta historica preservada excepto login esperado')
    print('INTEGRACION_OK')
