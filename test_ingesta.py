import requests

# 1. Autenticarse y obtener Token Access
login_url = "http://localhost:8000/api/auth/login/"
auth_payload = {"username": "admin", "password": "TrendWatch123456"}

response_auth = requests.post(login_url, json=auth_payload)

if response_auth.status_code != 200:
    print("❌ Error de Autenticación:", response_auth.text)
    exit()

token = response_auth.json().get("access")
print("✅ Token obtenido exitosamente.")

# 2. Enviar la publicación al endpoint de Ingesta
crear_url = "http://localhost:8000/api/publicaciones/crear/"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}
pub_payload = {
    "titulo": "Fuerte optimismo por la nueva temporada turistica en Misiones",
    "contenido": "Las reservas hoteleras superan las expectativas para los proximos meses.",
    "fuente": "El Territorio",
    "url": "https://elterritorio.com.ar/noticia/8888"
}

response_ingesta = requests.post(crear_url, json=pub_payload, headers=headers)

print("\n--- RESPUESTA DE LA API ---")
print("Status Code:", response_ingesta.status_code)
print("JSON:")
print(response_ingesta.text)
