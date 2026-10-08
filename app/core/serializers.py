from collections.abc import Mapping

from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone


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
