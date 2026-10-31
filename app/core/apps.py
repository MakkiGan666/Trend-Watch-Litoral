from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from django.db.backends.signals import connection_created
        from .busqueda_texto_v1 import registrar_sqlite_v1

        connection_created.connect(
            registrar_sqlite_v1, dispatch_uid='core.busqueda_texto_v1.sqlite', weak=False,
        )
