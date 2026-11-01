PERMISOS_USUARIO = frozenset({'core.view_publicacion'})
MODELOS_ADMIN = (
    'publicacion', 'sentimiento', 'locacion', 'registrodatos',
    'tematrend', 'publicaciontema', 'userauditoria', 'votopublicacion', 'comentario',
)
PERMISOS_ADMINISTRADOR = PERMISOS_USUARIO | {'core.ejecutar_scraping', 'core.procesar_ia'} | {
    f'core.{accion}_{modelo}'
    for modelo in MODELOS_ADMIN
    for accion in ('view', 'add', 'change', 'delete')
} | {'auth.view_user', 'auth.add_user', 'auth.view_group'}

PERMISOS_ROLES = {
    'Usuario': PERMISOS_USUARIO,
    'Administrador': PERMISOS_ADMINISTRADOR,
}

# Publicaciones es el panel de gestión de noticias: sólo para quien tiene el CRUD completo.
PERMISOS_PANEL = (
    'core.view_publicacion', 'core.add_publicacion',
    'core.change_publicacion', 'core.delete_publicacion',
)


def puede_gestionar_administradores(usuario):
    """El permiso de alta no sustituye la pertenencia al rol de TrendWatch."""
    return bool(
        usuario.is_authenticated and usuario.is_active and (
            usuario.is_superuser or (
                usuario.groups.filter(name='Administrador').exists()
                and usuario.has_perms((*PERMISOS_PANEL, 'auth.add_user'))
            )
        )
    )
