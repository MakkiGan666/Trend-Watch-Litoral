PERMISOS_USUARIO = frozenset({'core.view_publicacion'})
MODELOS_ADMIN = (
    'publicacion', 'sentimiento', 'locacion', 'registrodatos',
    'tematrend', 'publicaciontema', 'userauditoria', 'votopublicacion',
)
PERMISOS_ADMINISTRADOR = PERMISOS_USUARIO | {'core.ejecutar_scraping', 'core.procesar_ia'} | {
    f'core.{accion}_{modelo}'
    for modelo in MODELOS_ADMIN
    for accion in ('view', 'add', 'change', 'delete')
} | {
    f'auth.{accion}_{modelo}'
    for modelo in ('user', 'group')
    for accion in ('view', 'add', 'change', 'delete')
}
PERMISOS_ROLES = {
    'Usuario': PERMISOS_USUARIO,
    'Administrador': PERMISOS_ADMINISTRADOR,
}
