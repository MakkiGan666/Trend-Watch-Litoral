from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from .services.identidad import errores_identidad
from django.core.validators import URLValidator
from datetime import date
import unicodedata

from .localidades import DEPARTAMENTOS
from .models import Publicacion, Categoria, Comentario


class FiltrosPublicaciones(forms.Form):
    q = forms.CharField(required=False, max_length=150)
    fecha = forms.DateField(required=False)
    fuente = forms.ChoiceField(required=False)
    localidad = forms.ChoiceField(required=False, choices=[
        ('', 'Todas las localidades'),
        *((departamento['slug'], departamento['nombre']) for departamento in DEPARTAMENTOS),
        ('__missing', 'Sin departamento identificado'),
    ])
    categoria = forms.ChoiceField(required=False)

    def __init__(self, *args, fuentes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fuente'].choices = [('', 'Todas las fuentes'), *((nombre, nombre) for nombre in fuentes)]
        self.fields['categoria'].choices = [
            ('', 'Todas las categorías'),
            *((str(pk), nombre) for pk, nombre in Categoria.objects.order_by('nombre_categoria', 'pk').values_list('pk', 'nombre_categoria')),
            ('__missing', 'Sin categoría asignada'),
        ]

    def clean_q(self):
        consulta = ' '.join(unicodedata.normalize('NFC', self.cleaned_data['q']).split())
        if any(unicodedata.category(caracter).startswith('C') for caracter in consulta) or len(consulta.split()) > 10:
            raise forms.ValidationError('La búsqueda admite hasta 10 términos y no puede contener caracteres de control.')
        return consulta

    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha and fecha < date(2026, 1, 1):
            raise forms.ValidationError('La fecha debe ser de 2026 en adelante.')
        return fecha

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
    def clean_texto(self):
        from .services.moderacion_comentarios import contiene_lenguaje_inapropiado

        texto = self.cleaned_data['texto'].strip()
        if contiene_lenguaje_inapropiado(texto):
            raise forms.ValidationError('Revisá el lenguaje del comentario antes de publicarlo.')
        return texto

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
