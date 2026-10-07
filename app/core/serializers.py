from rest_framework import serializers
from django.contrib.auth.models import User

class UserMeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'roles']

    def get_roles(self, obj):
        if obj.is_superuser:
            return ['ADMINISTRADOR']
        return [nombre.upper() for nombre in obj.groups.filter(
            name__in=('Lector', 'Analista', 'Administrador')
        ).order_by('name').values_list('name', flat=True)]
