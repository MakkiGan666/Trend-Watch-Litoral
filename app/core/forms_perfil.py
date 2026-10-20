import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .services.identidad import errores_identidad


class PerfilForm(forms.ModelForm):
    email = forms.EmailField(label='Email', max_length=254)
    fecha_nacimiento = forms.DateField(
        label='Fecha de nacimiento', required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    celular = forms.CharField(label='Celular', max_length=30, required=False,
                              widget=forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel'}))
    confirmar_password = forms.CharField(
        label='Contraseña actual para cambiar tu email', required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )

    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellido'}
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name'}),
        }

    def clean_fecha_nacimiento(self):
        value = self.cleaned_data['fecha_nacimiento']
        if value and value > timezone.localdate():
            raise forms.ValidationError('La fecha de nacimiento no puede estar en el futuro.')
        return value

    def clean_celular(self):
        value = self.cleaned_data['celular'].strip()
        if value and (not re.fullmatch(r'[+\d ()-]+', value) or not 6 <= len(re.sub(r'\D', '', value)) <= 15):
            raise forms.ValidationError('Ingresá un celular válido, con entre 6 y 15 dígitos.')
        return value

    def clean(self):
        data = super().clean()
        email = data.get('email')
        if email:
            cambia_email = email.casefold() != self.instance.email.casefold()
            if cambia_email:
                for campo, mensaje in errores_identidad(email=email, excluir_pk=self.instance.pk).items():
                    self.add_error(campo, mensaje)
            elif get_user_model().objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
                # Conservar el rechazo previo de emails duplicados, sin reclasificar
                # un cruce histórico con username al editar solo nombre/teléfono.
                self.add_error('email', 'Ese email ya está registrado.')
            if cambia_email:
                if not self.instance.check_password(data.get('confirmar_password', '')):
                    self.add_error('confirmar_password', 'Ingresá tu contraseña actual para cambiar el email.')
        return data
