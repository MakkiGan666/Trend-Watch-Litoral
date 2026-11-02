from django import template
from core.roles import puede_gestionar_administradores

register = template.Library()
register.simple_tag(puede_gestionar_administradores, name='puede_gestionar_administradores')
