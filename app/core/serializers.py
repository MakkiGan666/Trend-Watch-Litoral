from rest_framework import serializers
from django.contrib.auth.models import User

class UserMeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'roles']

    def get_roles(self, obj):
        roles = []
        if obj.is_superuser:
            roles.append('ADMINISTRADOR')
        if obj.is_staff:
            roles.append('STAFF')
        if not roles:
            roles.append('USUARIO_LECTURA')
        return roles