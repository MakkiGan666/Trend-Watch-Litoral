"""Catalogo territorial de lectura. No modifica las ubicaciones almacenadas.
Municipios: https://www.digestomisiones.gob.ar/municipios.php
Los nombres ambiguos se excluyen hasta que se identifique su departamento.
"""
import re
import unicodedata

DEPARTAMENTOS = [{'slug': 'capital',
  'nombre': 'Capital',
  'imagen': 'mockup/Capital_fondo.png',
  'municipios': ['Posadas', 'Garupá', 'Fachinal']},
 {'slug': 'obera',
  'nombre': 'Oberá',
  'imagen': 'mockup/Obera_fonod.png',
  'municipios': ['Oberá',
                 'Campo Ramón',
                 'Campo Viera',
                 'Guaraní',
                 'Los Helechos',
                 'Colonia Alberdi',
                 'Panambí',
                 'San Martín',
                 'General Alvear']},
 {'slug': 'iguazu',
  'nombre': 'Iguazú',
  'imagen': 'mockup/Iguazu_fondo.png',
  'municipios': ['Puerto Esperanza', 'Puerto Iguazú', 'Colonia Wanda', 'Wanda', 'Puerto Libertad']},
 {'slug': 'eldorado',
  'nombre': 'Eldorado',
  'imagen': 'mockup/El_Dorado_fondo.png',
  'municipios': ['Eldorado',
                 'Colonia Delicia',
                 '9 de Julio',
                 'Santiago de Liniers',
                 'Colonia Victoria']},
 {'slug': 'sanignacio',
  'nombre': 'San Ignacio',
  'imagen': 'mockup/San_Ignacio_fondo.png',
  'municipios': ['San Ignacio',
                 'Jardín América',
                 'Santo Pipó',
                 'Corpus',
                 'Hipólito Yrigoyen',
                 'General Urquiza',
                 'Colonia Polana']},
 {'slug': 'cainguas',
  'nombre': 'Cainguás',
  'imagen': 'mockup/Cainguas_fondo.png',
  'municipios': ['Campo Grande', 'Aristóbulo del Valle', 'Salto Encantado', 'Dos de Mayo']},
 {'slug': 'libertador',
  'nombre': 'Libertador Gral. San Martín',
  'imagen': 'mockup/Libertador_SanMartin_fondo.png',
  'municipios': ['Puerto Rico',
                 'Garuhapé',
                 'Capioví',
                 'El Alcázar',
                 'Puerto Leoni',
                 'Ruiz de Montoya']},
 {'slug': 'apostoles',
  'nombre': 'Apóstoles',
  'imagen': 'mockup/Apostoles_fondo.png',
  'municipios': ['Apóstoles', 'Azara', 'San José', 'Tres Capones']},
 {'slug': 'belgrano',
  'nombre': 'Gral. Manuel Belgrano',
  'imagen': 'mockup/Gral.Manuel_Belgrano_fondo.png',
  'municipios': ['Bernardo de Irigoyen', 'Comandante Andrés Guacurarí', 'San Antonio']},
 {'slug': 'montecarlo',
  'nombre': 'Montecarlo',
  'imagen': 'mockup/Montecarlo_fondo.png',
  'municipios': ['Montecarlo', 'Puerto Piray', 'Caraguatay']},
 {'slug': 'candelaria',
  'nombre': 'Candelaria',
  'imagen': 'mockup/Candelaria_fondo.png',
  'municipios': ['Santa Ana',
                 'Candelaria',
                 'Bonpland',
                 'Loreto',
                 'Cerro Corá',
                 'Mártires',
                 'Profundidad']},
 {'slug': 'sanpedro',
  'nombre': 'San Pedro',
  'imagen': 'mockup/San_Pedro_fondo.png',
  'municipios': ['San Pedro']},
 {'slug': 'sanjavier',
  'nombre': 'San Javier',
  'imagen': 'mockup/San_Javier_fondo.png',
  'municipios': ['San Javier', 'Itacaruaré', 'Mojón Grande', 'Florentino Ameghino']},
 {'slug': 'concepcion',
  'nombre': 'Concepción',
  'imagen': 'mockup/Concepcion_fondo.png',
  'municipios': ['Concepción de la Sierra', 'Santa María']},
 {'slug': '25mayo',
  'nombre': '25 de Mayo',
  'imagen': 'mockup/25_mayo_fondo.png',
  'municipios': ['25 de Mayo', 'Alba Posse', 'Colonia Aurora']},
 {'slug': 'leandro',
  'nombre': 'Leandro N. Alem',
  'imagen': 'mockup/LeandroN.Alem_fondo.png',
  'municipios': ['Leandro N. Alem',
                 'Cerro Azul',
                 'Dos Arroyos',
                 'Gobernador López',
                 'Arroyo del Medio',
                 'Olegario Víctor Andrade',
                 'Caá Yarí',
                 'Almafuerte']},
 {'slug': 'guarani',
  'nombre': 'Guaraní',
  'imagen': 'mockup/Guarani_fondo.png',
  'municipios': ['El Soberbio', 'San Vicente', 'Fracran']}]

def normalizar_nombre(nombre):
    texto = unicodedata.normalize('NFD', str(nombre or '').strip().lower())
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r',?\s+misiones(?:,?\s+argentina)?$', '', texto)
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


def departamento_de_ubicacion(nombre):
    valor = normalizar_nombre(nombre)
    if not valor:
        return None
    candidatos = set()
    for departamento in DEPARTAMENTOS:
        # El servicio de IA actualmente recorta location a 18 caracteres.
        for municipio in departamento['municipios']:
            if valor in {normalizar_nombre(municipio), normalizar_nombre(municipio[:18])}:
                candidatos.add(departamento['slug'])
    for departamento in DEPARTAMENTOS:
        nombres = [departamento['nombre']]
        if departamento['slug'] == 'libertador':
            nombres.append('Libertador General San Martin')
        if departamento['slug'] == 'belgrano':
            nombres.append('General Manuel Belgrano')
        if departamento['slug'] == 'concepcion':
            nombres.append('Concepcion de la Sierra')
        for nombre_departamento in nombres:
            for alias in [nombre_departamento, 'Departamento '+nombre_departamento]:
                if valor in {normalizar_nombre(alias), normalizar_nombre(alias[:18])}:
                    candidatos.add(departamento['slug'])
    return next(iter(candidatos)) if len(candidatos) == 1 else None
