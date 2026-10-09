from collections.abc import Mapping

from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth.models import update_last_login
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from .services.autenticacion import autenticar_identificador, ERROR_CREDENCIALES


class StrictCharField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        value = super().to_internal_value(data)
        if not self.allow_blank and not value.strip():
            self.fail('blank')
        return value


class StrictURLField(serializers.URLField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        return super().to_internal_value(data)


class PasswordLoginField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail('invalid')
        return super().to_internal_value(data)


class LoginTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El padre crea estos campos en __init__; reemplazarlos antes de validar.
        self.fields['username'] = StrictCharField(write_only=True)
        self.fields['password'] = PasswordLoginField(
            write_only=True, trim_whitespace=False, style={'input_type': 'password'},
        )

    def validate(self, attrs):
        self.user = autenticar_identificador(
            self.context.get('request'), attrs['username'], attrs['password'],
        )
        if not api_settings.USER_AUTHENTICATION_RULE(self.user):
            raise AuthenticationFailed(ERROR_CREDENCIALES, code='no_active_account')
        # La identidad ya fue comprobada por el módulo compartido antes de emitir.
        refresh = self.get_token(self.user)
        data = {'refresh': str(refresh), 'access': str(refresh.access_token)}
        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)
        return data


class PublicacionInputSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        # Let DRF report invalid top-level types using non_field_errors.
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({
                field: ['Campo no admitido.'] for field in sorted(unknown)
            })
        return super().to_internal_value(data)


class PublicacionCreateSerializer(PublicacionInputSerializer):
    titulo = StrictCharField(max_length=255, trim_whitespace=False)
    contenido = StrictCharField(trim_whitespace=False)
    fuente = StrictCharField(max_length=100, default='Manual', trim_whitespace=False)
    url = StrictURLField(max_length=200, default='', allow_blank=True, trim_whitespace=True)
    fecha_publicacion = serializers.DateTimeField(
        input_formats=['iso-8601'], default=timezone.now,
    )


class PublicacionUpdateSerializer(PublicacionInputSerializer):
    titulo = StrictCharField(max_length=255, trim_whitespace=False)
    contenido = StrictCharField(trim_whitespace=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Debe proporcionar titulo o contenido.')
        return attrs

class UserMeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'roles']

    def get_roles(self, obj):
        if obj.is_superuser:
            return ['ADMINISTRADOR']
        return [nombre.upper() for nombre in obj.groups.filter(
            name__in=('Usuario', 'Administrador')
        ).order_by('name').values_list('name', flat=True)]
