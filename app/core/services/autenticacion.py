from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q


ERROR_CREDENCIALES = 'Usuario o contraseña incorrectos.'


def autenticar_identificador(request, identificador, password):
    """Autentica únicamente una identidad inequívoca, sin alterar la contraseña."""
    if not isinstance(identificador, str) or not isinstance(password, str):
        return None
    identificador = identificador.strip()
    if not identificador or not password:
        return None
    modelo = get_user_model()
    candidatos = list(modelo.objects.filter(
        Q(username=identificador) | Q(email__iexact=identificador)
    ).distinct()[:2])
    if len(candidatos) != 1:
        # Trabajo de hash sin persistencia, como el backend para usuarios inexistentes.
        modelo().set_password(password)
        return None
    candidato = candidatos[0]
    usuario = authenticate(request, username=candidato.username, password=password)
    if usuario is None or usuario.pk != candidato.pk:
        return None
    return usuario
