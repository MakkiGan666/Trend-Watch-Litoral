"""Runner del contenedor: entorno vacío y destino comprobado por conexión."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
from unittest.mock import patch

from fase1_1_validation import ejecutar_plan, sin_red_python

from fase1_1_security import (
    authorize_writes, connection_params, database_config, require, runner_environment,
)


def main():
    ip, token = runner_environment(os.environ)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'mi_proyecto.settings'
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    from django.conf import settings
    # Antes de django.setup: no aceptar OPTIONS, servicios, alias o TEST heredados.
    database_config(settings.DATABASES, ip)
    db = settings.DATABASES['default']
    db['TEST'] = {'NAME': 'test_tw_disposable'}
    db['OPTIONS'] = {'hostaddr': ip, 'passfile': '/dev/null',
                     'sslmode': 'disable', 'connect_timeout': 5,
                     'options': '-c default_transaction_read_only=on'}
    settings.MEDIA_ROOT = '/tmp/media'
    settings.FILE_UPLOAD_TEMP_DIR = '/tmp/uploads'
    Path(settings.FILE_UPLOAD_TEMP_DIR).mkdir()
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

    # Se instala antes de setup: toda nueva conexión Django debe pasar el SELECT
    # de identidad antes de devolver el control al consumidor de la conexión.
    from django.db.backends.signals import connection_created

    def verify_connection(sender, connection, **kwargs):
        require(connection.alias == 'default' and connection.vendor == 'postgresql',
                'Conexión no autorizada')
        try:
            # Cursor nativo: no dispara recursivamente ensure_connection.
            authorize_writes(connection.connection, ip, token)
        except BaseException:
            connection.close()
            raise

    connection_created.connect(verify_connection, weak=False)
    from django.db.backends.postgresql.base import DatabaseWrapper
    original_params = DatabaseWrapper.get_connection_params

    def guarded_params(wrapper):
        params = original_params(wrapper)
        connection_params(params, ip)  # Antes de que libpq abra una conexión.
        return params

    @contextmanager
    def guarded_maintenance(wrapper):
        # Django usa normalmente la base postgres para CREATE/DROP DATABASE.
        # Aquí toda conexión administrativa vuelve a nuestra base ya identificada.
        config = deepcopy(wrapper.settings_dict)
        config['NAME'] = 'tw_disposable'
        maintenance = DatabaseWrapper(config, alias='default')
        try:
            with maintenance.cursor() as cursor:
                yield cursor
        finally:
            maintenance.close()

    # Defensa adicional; la frontera de red es el bridge interno en modo isolated.
    with sin_red_python(), patch.object(DatabaseWrapper, 'get_connection_params', guarded_params), patch.object(
        DatabaseWrapper, '_nodb_cursor', guarded_maintenance
    ):
        import django
        django.setup()
        from django.db import connection
        from django.core.management import call_command
        connection.ensure_connection()  # Dispara la verificación de identidad.
        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS postgis')
            cursor.execute('SELECT PostGIS_Version()')
            print('PostGIS:', cursor.fetchone()[0], flush=True)
        ejecutar_plan(call_command)


if __name__ == '__main__':
    main()
