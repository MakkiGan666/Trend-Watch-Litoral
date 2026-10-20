"""Validaciones puras de límites operativos: nunca abren servicios."""
import math


def entero_positivo(valor, nombre):
    if type(valor) is not int or valor < 1:
        raise ValueError(f'{nombre} debe ser un entero mayor que cero.')
    return valor


def segundos_validos(valor, nombre, permitir_cero=False):
    try:
        invalido = (type(valor) not in (int, float) or not math.isfinite(valor)
                    or valor < 0 or (valor == 0 and not permitir_cero))
    except OverflowError:
        invalido = True
    if invalido:
        raise ValueError(f'{nombre} debe ser un número finito {"no negativo" if permitir_cero else "positivo"}.')
    return valor
