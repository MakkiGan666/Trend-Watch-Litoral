import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone


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
            if get_user_model().objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
                self.add_error('email', 'Ese email ya está registrado.')
            # El email también permite iniciar sesión: comprobar la contraseña al cambiarlo.
            if email.casefold() != self.instance.email.casefold():
                if not self.instance.check_password(data.get('confirmar_password', '')):
                    self.add_error('confirmar_password', 'Ingresá tu contraseña actual para cambiar el email.')
        return data
