from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from .services.identidad import errores_identidad
from django.core.validators import URLValidator
from .models import Publicacion, Categoria, Comentario

class PublicacionForm(forms.ModelForm):
    imagen_archivo = forms.ImageField(
        label='Subir imagen desde tu dispositivo', required=False,
        help_text='JPG, PNG o WebP, hasta 5 MB. Si subís un archivo, se muestra en lugar de la URL.',
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
    )
    imagen_url = forms.URLField(
        label='URL de la imagen', required=False, max_length=500,
        validators=[URLValidator(schemes=['http', 'https'])],
        help_text='Opcional. Pegá el enlace directo a una imagen (https://…).',
        widget=forms.URLInput(attrs={'style': 'width: 100%; padding: 8px;', 'placeholder': 'https://sitio.com/imagen.jpg'}),
    )
    # Una publicación puede tener varias categorías (Publicacion ↔ Tema ↔ Categoria)
    categorias = forms.ModelMultipleChoiceField(
        queryset=Categoria.objects.order_by('nombre_categoria'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Categorías"
    )

    class Meta:
        model = Publicacion
        fields = ['titulo', 'fuente', 'contenido', 'url', 'imagen_archivo', 'imagen_url']
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

    def clean_imagen_archivo(self):
        imagen = self.cleaned_data.get('imagen_archivo')
        if imagen and hasattr(imagen, 'image'):
            if imagen.size > 5 * 1024 * 1024:
                raise forms.ValidationError('La imagen no puede superar los 5 MB.')
            formatos = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}
            extension = formatos.get(imagen.image.format)
            if not extension:
                raise forms.ValidationError('Usá una imagen JPG, PNG o WebP.')
            # El nombre se corresponde con el contenido validado, no con la extensión enviada.
            imagen.name = 'imagen.' + extension
        return imagen


class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ['texto']
        labels = {'texto': 'Tu comentario'}
        widgets = {
            'texto': forms.Textarea(attrs={
                'rows': 4, 'maxlength': 2000,
                'placeholder': 'Compartí tu opinión sobre esta noticia…',
            }),
        }


class AdministradorCreationForm(UserCreationForm):
    email = forms.EmailField(label='Correo electrónico', max_length=254)

    class Meta:
        model = get_user_model()
        fields = ('username', 'email')

    def clean_username(self):
        username = super().clean_username()
        if self._meta.model.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya está en uso.')
        return username

    def clean(self):
        data = super().clean()
        for campo, mensaje in errores_identidad(
            username=data.get('username'), email=data.get('email'),
        ).items():
            self.add_error(campo, mensaje)
        return data
