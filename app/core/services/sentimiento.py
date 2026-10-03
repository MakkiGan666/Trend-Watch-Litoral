import math
import re
from statistics import NormalDist

import numpy as np


def _t_critical_value(df: int, confidence_level: float = 0.95) -> float:
    """
    Aproxima el cuantil crítico t-Student para intervalos de confianza.
    Se evita depender de SciPy para mantener la compatibilidad con entornos
    sin esa librería instalada.
    """
    if df <= 0:
        return 1.0

    z_value = NormalDist().inv_cdf((1 + confidence_level) / 2)
    return float(z_value * (1.0 + 0.5 / max(df, 1)))


def analyze_sentiment_lexicon(text: str) -> float:
    """
    Análisis léxico determinista basado en palabras clave para español/Litoral.
    Devuelve un float entre -1.0 y 1.0.
    """
    if not text:
        return 0.0

    text_lower = text.lower()

    positives = [
        "bueno", "excelente", "genial", "encantó", "encanto", 
        "mejora", "interesante", "impecable", "felicidades"
    ]
    negatives = [
        "malo", "terrible", "horrible", "excesiva", "problemas", "no estoy seguro"
    ]

    score = 0.0
    for pos in positives:
        if pos in text_lower:
            score += 0.7

    for neg in negatives:
        if neg in text_lower:
            score -= 0.7

    if score == 0.0:
        return 0.0

    return float(np.clip(score, -1.0, 1.0))


def compute_probabilistic_sentiment(comments: list) -> dict:
    """
    Calcula media, varianza, intervalo t-Student y Wilson Score 
    para un grupo de comentarios de redes sociales.
    """
    if not comments:
        return {
            "sample_size": 0,
            "mean_polarity": 0.0,
            "confidence_score": 0.0,
            "std_dev": 0.0,
            "t_ci_lower": 0.0,
            "t_ci_upper": 0.0,
            "wilson_lower": 0.0,
            "wilson_upper": 0.0,
            "positive_ratio": 0.0
        }

    # 1. Obtener polaridades individuales usando el lexicon
    polarities = [analyze_sentiment_lexicon(c.get("message", "")) for c in comments]
    n = len(polarities)
    mean_p = float(np.mean(polarities))
    std_p = float(np.std(polarities, ddof=1)) if n > 1 else 0.0

    # 2. Intervalo de Confianza t-Student (95%)
    confidence_level = 0.95
    if n > 1 and std_p > 0:
        sem = std_p / math.sqrt(n)
        t_crit = _t_critical_value(n - 1, confidence_level)
        margin_error = t_crit * sem
        t_ci_lower = float(max(-1.0, mean_p - margin_error))
        t_ci_upper = float(min(1.0, mean_p + margin_error))
    else:
        margin_error = 0.0
        t_ci_lower = float(mean_p)
        t_ci_upper = float(mean_p)

    # 3. Wilson Score Interval para proporción de positivos
    k_pos = sum(1 for p in polarities if p > 0)
    p_hat = float(k_pos / n)
    z = 1.96

    denom = 1 + (z**2 / n)
    center = (p_hat + (z**2 / (2 * n))) / denom
    spread = (z / denom) * math.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))

    wilson_lower = float(max(0.0, center - spread))
    wilson_upper = float(min(1.0, center + spread))

    # 4. Score de Confianza Global
    size_weight = math.sqrt(n) / (math.sqrt(n) + 1.5)
    variance_penalty = 1.0 - (margin_error / 2.0)
    confidence_score = float(np.clip(size_weight * variance_penalty, 0.0, 1.0))

    return {
        "sample_size": n,
        "mean_polarity": round(float(mean_p), 2),
        "std_dev": round(float(std_p), 2),
        "t_ci_lower": round(float(t_ci_lower), 2),
        "t_ci_upper": round(float(t_ci_upper), 2),
        "wilson_lower": round(float(wilson_lower), 2),
        "wilson_upper": round(float(wilson_upper), 2),
        "confidence_score": round(float(confidence_score * 100), 1),
        "positive_ratio": round(float(p_hat * 100), 1)
    }