PERMISOS_LECTOR = frozenset({'core.view_publicacion'})
PERMISOS_ANALISTA = PERMISOS_LECTOR | {
    'core.add_publicacion', 'core.change_publicacion',
    'core.ejecutar_scraping', 'core.procesar_ia',
}
MODELOS_ADMIN = (
    'publicacion', 'sentimiento', 'locacion', 'registrodatos',
    'tematrend', 'publicaciontema', 'userauditoria', 'votopublicacion',
)
PERMISOS_ADMINISTRADOR = PERMISOS_ANALISTA | {
    f'core.{accion}_{modelo}'
    for modelo in MODELOS_ADMIN
    for accion in ('view', 'add', 'change', 'delete')
} | {
    f'auth.{accion}_{modelo}'
    for modelo in ('user', 'group')
    for accion in ('view', 'add', 'change', 'delete')
}
PERMISOS_ROLES = {
    'Lector': PERMISOS_LECTOR,
    'Analista': PERMISOS_ANALISTA,
    'Administrador': PERMISOS_ADMINISTRADOR,
}
