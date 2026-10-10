# Usa una imagen oficial de Python como base
FROM python:3.11-slim

# Evita que Python escriba archivos .pyc y fuerza el output de logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia e instala los requerimientos primero (para aprovechar la caché)
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código de la aplicación (mismo layout que el volumen ./app:/app de Compose).
# .env y otros archivos locales quedan fuera por .dockerignore.
COPY app/ /app/
