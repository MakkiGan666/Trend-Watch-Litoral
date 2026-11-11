from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm


class PasswordResetFormUnico(PasswordResetForm):
    """Solo envía un enlace si el correo identifica una única cuenta activa.

    Cuentas antiguas sin email siguen siendo compatibles con el login por usuario,
    pero no se puede recuperar una contraseña por correo para ellas. Si hay más de
    una cuenta activa con el mismo email, se falla cerrado para evitar enviar
    enlaces ambiguos.
    """

    def get_users(self, email):
        modelo_usuario = get_user_model()
        candidatos = list(
            modelo_usuario._default_manager.filter(
                email__iexact=email.strip(), is_active=True,
            )[:2]
        )
        if len(candidatos) != 1:
            return
        usuario = candidatos[0]
        if usuario.has_usable_password() and usuario.email:
            yield usuario
