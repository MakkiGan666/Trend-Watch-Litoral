import os
import uuid
import pytest
import requests

BASE_URL = os.getenv("TW_API_URL", "http://localhost:8000").rstrip("/")
USERNAME = os.getenv("TW_TEST_USER")
PASSWORD = os.getenv("TW_TEST_PASSWORD")

pytestmark = pytest.mark.skipif(
    not (USERNAME and PASSWORD),
    reason="Configurá TW_TEST_USER y TW_TEST_PASSWORD",
)

@pytest.fixture(scope="session")
def headers():
    r = requests.post(f"{BASE_URL}/api/auth/login/",
                      json={"username": USERNAME, "password": PASSWORD},
                      timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    token = data.get("access") or data.get("token") or data.get("access_token")
    assert token, f"Sin token en respuesta: {data}"
    return {"Authorization": f"Bearer {token}"}

def nuevo_payload():
    uid = uuid.uuid4().hex
    return {
        "titulo": "Fuerte optimismo por la nueva temporada turística en Misiones",
        "contenido": "Las reservas hoteleras superan las expectativas para los próximos meses.",
        "fuente": "El Territorio",
        "url": f"https://elterritorio.com.ar/noticia/{uid}",
    }

def test_crear_publicacion(headers):
    r = requests.post(f"{BASE_URL}/api/publicaciones/crear/",
                      json=nuevo_payload(), headers=headers, timeout=15)
    assert r.status_code in (201, 202), r.text

def test_duplicado_no_se_crea_dos_veces(headers):
    p = nuevo_payload()
    r1 = requests.post(f"{BASE_URL}/api/publicaciones/crear/", json=p, headers=headers, timeout=15)
    r2 = requests.post(f"{BASE_URL}/api/publicaciones/crear/", json=p, headers=headers, timeout=15)
    assert r1.status_code in (201, 202)
    assert r2.status_code in (200, 409)  # RF-02

def test_sin_token_es_rechazado():
    r = requests.post(f"{BASE_URL}/api/publicaciones/crear/",
                      json=nuevo_payload(), timeout=15)
    assert r.status_code in (401, 403)