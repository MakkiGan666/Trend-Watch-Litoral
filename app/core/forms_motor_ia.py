"""Formulario de la configuración del motor de IA (panel de administración)."""
from django import forms

from .services.ia.base import PROVEEDOR_GEMINI, PROVEEDOR_OLLAMA
from .services.ia.gemini import ProveedorGemini


class ConfiguracionIAForm(forms.Form):
    motor_principal = forms.ChoiceField(
        choices=[(PROVEEDOR_GEMINI, 'Gemini'), (PROVEEDOR_OLLAMA, 'Llama 3.1')],
        widget=forms.RadioSelect,
        error_messages={'required': 'Elegí el motor principal.',
                        'invalid_choice': 'El motor elegido no es válido.'},
    )
    respaldo_automatico = forms.BooleanField(required=False)

    def clean_motor_principal(self):
        motor = self.cleaned_data['motor_principal']
        # Un motor sin credenciales no puede ser el principal: todos los análisis fallarían.
        if motor == PROVEEDOR_GEMINI and not ProveedorGemini().configurado():
            raise forms.ValidationError(
                'Gemini no está configurado en el servidor (falta GEMINI_API_KEY). '
                'Elegí Llama 3.1 o configurá la clave.')
        return motor
