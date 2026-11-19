from django import forms
from django.core.exceptions import ValidationError

from core.models import MiembroGrupoEditorial
from core.services.agrupacion_editorial import MAX_MIEMBROS


class CrearGrupoEditorialForm(forms.Form):
    publicacion_ids = forms.CharField(
        label='IDs de publicaciones',
        help_text=f'IDs separados por coma o espacios; entre 2 y {MAX_MIEMBROS}.',
        max_length=300,
    )
    representante_id = forms.IntegerField(label='ID representante (opcional)', required=False, min_value=1)
    motivo = forms.CharField(label='Motivo de revisión', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def clean_publicacion_ids(self):
        raw = self.cleaned_data['publicacion_ids'].replace(',', ' ').split()
        try:
            ids = [int(item) for item in raw]
        except ValueError as error:
            raise ValidationError('Los IDs deben ser números enteros.') from error
        if len(ids) < 2 or len(ids) > MAX_MIEMBROS or len(set(ids)) != len(ids):
            raise ValidationError(f'Indique entre 2 y {MAX_MIEMBROS} IDs únicos.')
        return ids

    def clean(self):
        data = super().clean()
        representante = data.get('representante_id')
        if representante and representante not in data.get('publicacion_ids', []):
            self.add_error('representante_id', 'La representante debe estar entre los IDs seleccionados.')
        return data


class DecisionMiembroEditorialForm(forms.Form):
    decision = forms.ChoiceField(choices=(
        (MiembroGrupoEditorial.Decision.APROBADO, 'Aprobar este miembro'),
        (MiembroGrupoEditorial.Decision.RECHAZADO, 'Rechazar este miembro'),
    ))
    motivo = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class AccionGrupoEditorialForm(forms.Form):
    motivo = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class ActivarGrupoEditorialForm(AccionGrupoEditorialForm):
    representante_id = forms.ChoiceField(label='Representante definitiva')

    def __init__(self, grupo, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['representante_id'].choices = [
            (str(miembro.publicacion_id), f'#{miembro.publicacion_id} — {miembro.publicacion.titulo}')
            for miembro in grupo.miembros.select_related('publicacion').order_by('publicacion_id')
        ]
        self.fields['representante_id'].initial = str(grupo.representante_id)
