from django import forms
from .models import Publicacion, Categoria

class PublicacionForm(forms.ModelForm):
    # Campo opcional para asignar una categoría al crear
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.all(),
        required=False,
        label="Categoría"
    )

    class Meta:
        model = Publicacion
        fields = ['titulo', 'fuente', 'contenido', 'url']
        widgets = {
            'titulo': forms.TextInput(attrs={'style': 'width: 100%; padding: 8px;'}),
            'fuente': forms.TextInput(attrs={'style': 'width: 100%; padding: 8px;'}),
            'contenido': forms.Textarea(attrs={'style': 'width: 100%; padding: 8px;', 'rows': 5}),
            'url': forms.URLInput(attrs={'style': 'width: 100%; padding: 8px;'}),
        }