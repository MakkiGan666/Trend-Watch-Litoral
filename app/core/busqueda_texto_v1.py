"""Contrato V1 persistido y usado por migraciones: no cambiar su semántica.

Una nueva normalización requiere otra versión y una migración de recálculo.
Este módulo no importa modelos ni lógica de negocio.
"""
import unicodedata

from django.db.models import Func, TextField

VOCALES_V1 = 'áàâäãåéèêëíìîïóòôöõúùûü'
BASES_V1 = 'aaaaaaeeeeiiiiooooouuuu'


def plegar_v1(texto):
    return unicodedata.normalize('NFC', texto).lower().translate(str.maketrans(VOCALES_V1, BASES_V1))


def registrar_sqlite_v1(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        connection.connection.create_function('tw_plegar_v1', 1, plegar_v1, deterministic=True)


class TextoComparableV1(Func):
    output_field = TextField()

    def as_postgresql(self, compiler, connection, **extra_context):
        campo, params = compiler.compile(self.source_expressions[0])
        nfc = f'CASE WHEN {campo} IS NFC NORMALIZED THEN {campo} ELSE normalize({campo}, NFC) END'
        return f'translate(lower({nfc}), %s, %s)', [*params, *params, *params, VOCALES_V1, BASES_V1]

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, function='tw_plegar_v1', **extra_context)
