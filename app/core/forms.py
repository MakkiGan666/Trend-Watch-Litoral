from django import forms
from .models import Publicacion, Categoria

class PublicacionForm(forms.ModelForm):
    # Una publicación puede tener varias categorías (Publicacion ↔ Tema ↔ Categoria)
    categorias = forms.ModelMultipleChoiceField(
        queryset=Categoria.objects.order_by('nombre_categoria'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Categorías"
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Igual que la API: sin URL, el título define la identidad de la publicación.
        self.fields['url'].required = False