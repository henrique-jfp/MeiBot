import re
import unicodedata


APP_ALIASES = {
    "Correios": ("correio", "correios"),
    "Shopee": ("shopee",),
    "Mercado Livre": ("mercado livre", "mercadolivre"),
    "iFood": ("ifood", "i food"),
    "Uber": ("uber",),
    "Loggi": ("loggi",),
    "Lalamove": ("lalamove",),
}

CORRECTION_KEYWORDS = (
    "corrigir",
    "corrige",
    "corrija",
    "correcao",
    "corrigindo",
    "ajustar",
    "ajuste",
    "ajusta",
    "apagar",
    "excluir",
    "deletar",
    "remover",
    "cancelar",
)

PORTEIRO_KEYWORDS = ("porteiro", "porteiros")
REGISTRO_KEYWORDS = (
    "operacao",
    "registro",
    "rota",
    "horario",
    "hora",
    "pacote",
    "pacotes",
    "km",
    "quilometr",
    "valor",
    "ganho",
    "gasto",
    "despesa",
)


def normalize_user_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def has_correction_keyword(text: str) -> bool:
    normalized = normalize_user_text(text)
    return any(keyword in normalized for keyword in CORRECTION_KEYWORDS)


def detect_app_name(text: str):
    normalized = normalize_user_text(text)
    for app_name, aliases in APP_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return app_name
    return None


def infer_correction_intent(text: str):
    normalized = normalize_user_text(text)
    if not has_correction_keyword(normalized):
        return None
    
    # Prioridade para exclusão
    if any(k in normalized for k in ("apagar", "excluir", "deletar", "remover")):
        return "excluir_registro"

    if any(keyword in normalized for keyword in PORTEIRO_KEYWORDS):
        return "corrigir_porteiro"
    if any(keyword in normalized for keyword in REGISTRO_KEYWORDS):
        return "corrigir_registro"
    return None


def _parse_decimal(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def extract_time_value(text: str):
    if not text:
        return None
    # Busca todos os horários no texto
    matches = re.findall(r"\b(\d{1,2})\s*(?:[:h])\s*(\d{2})\b", normalize_user_text(text))
    if not matches:
        return None
    
    results = []
    for hh_str, mm_str in matches:
        hh, mm = int(hh_str), int(mm_str)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            results.append(f"{hh:02d}:{mm:02d}")
    
    return results[0] if results else None


def extract_package_count(text: str):
    normalized = normalize_user_text(text)
    match = re.search(r"\b(\d+)\s+pacotes?\b", normalized)
    if not match:
        return None
    return int(match.group(1))


def extract_km_value(text: str):
    normalized = normalize_user_text(text)
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*km\b", normalized)
    if not match:
        return None
    return _parse_decimal(match.group(1))


def extract_money_value(text: str):
    normalized = normalize_user_text(text)
    patterns = (
        r"r\$\s*(\d+(?:[.,]\d{1,2})?)",
        r"(\d+(?:[.,]\d{1,2})?)\s*reais?\b",
        r"valor(?:\s+correto)?(?:\s+e)?(?:\s+de)?\s*(\d+(?:[.,]\d{1,2})?)",
        r"ganho(?:\s+correto)?(?:\s+e)?(?:\s+de)?\s*(\d+(?:[.,]\d{1,2})?)",
        r"faturamento(?:\s+correto)?(?:\s+e)?(?:\s+de)?\s*(\d+(?:[.,]\d{1,2})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return _parse_decimal(match.group(1))
    return None


def infer_time_field(text: str):
    normalized = normalize_user_text(text)
    start_keywords = ("inicio", "comeco", "comecei", "entrada", "chegada", "cheguei")
    end_keywords = ("fim", "termino", "finalizei", "encerrei", "saida", "saí", "sai")
    if any(keyword in normalized for keyword in start_keywords):
        return "hora_inicio"
    if any(keyword in normalized for keyword in end_keywords):
        return "hora_fim"
    return None


def _merge_ai_event_fields(interpreted: dict, campos: dict):
    eventos = (interpreted or {}).get("eventos") or []
    if not eventos:
        return campos

    evento = eventos[0]
    merged = dict(campos)
    
    # Se a IA já extraiu os campos corretamente (pelo prompt novo), priorizamos o que está em 'evento'
    # mas mantemos a heurística se a IA falhar.
    if "hora_inicio" not in merged and evento.get("hora_inicio_rota"):
        merged["hora_inicio"] = evento["hora_inicio_rota"]
    if "hora_fim" not in merged and evento.get("hora_fim_operacao"):
        merged["hora_fim"] = evento["hora_fim_operacao"]
    if "valor" not in merged and evento.get("valor") not in (None, "", 0, 0.0):
        merged["valor"] = evento.get("valor")
    if "km" not in merged and evento.get("km") not in (None, "", 0, 0.0):
        merged["km"] = evento.get("km")
    if "pacotes" not in merged and evento.get("pacotes") not in (None, "", 0):
        merged["pacotes"] = evento.get("pacotes")
    return merged


def build_correction_info(text: str, interpreted: dict = None):
    intent = infer_correction_intent(text)
    if intent not in ("corrigir_registro", "excluir_registro"):
        return None

    campos = {}
    if intent == "corrigir_registro":
        time_field = infer_time_field(text)
        time_value = extract_time_value(text)
        if time_field and time_value:
            campos[time_field] = time_value

        packages = extract_package_count(text)
        if packages is not None:
            campos["pacotes"] = packages

        km_value = extract_km_value(text)
        if km_value is not None:
            campos["km"] = km_value

        money_value = extract_money_value(text)
        if money_value is not None:
            campos["valor"] = money_value

    interpreted = interpreted or {}
    campos = _merge_ai_event_fields(interpreted, campos)

    app_name = detect_app_name(text)
    eventos = interpreted.get("eventos") or []
    if not app_name and eventos:
        app_name = eventos[0].get("app")

    if intent == "corrigir_registro" and not campos and not app_name:
        return None

    normalized = normalize_user_text(text)
    tipo_alvo = "gasto" if any(keyword in normalized for keyword in ("gasto", "despesa", "combustivel", "gasolina")) else "ganho"
    return {
        "app": app_name,
        "tipo_alvo": tipo_alvo,
        "campos": campos,
        "atualizar_operacao": "operacao" in normalized and any(
            field in campos for field in ("hora_inicio", "hora_fim")
        ),
    }


def build_event_patch_from_correction(correction_info: dict):
    if not correction_info:
        return {}

    campos = correction_info.get("campos") or {}
    event_patch = {}
    if correction_info.get("app"):
        event_patch["app"] = correction_info["app"]
    if "hora_inicio" in campos:
        event_patch["hora_inicio_rota"] = campos["hora_inicio"]
    if "hora_fim" in campos:
        event_patch["hora_fim_operacao"] = campos["hora_fim"]
    if "valor" in campos:
        event_patch["valor"] = campos["valor"]
    if "km" in campos:
        event_patch["km"] = campos["km"]
    if "pacotes" in campos:
        event_patch["pacotes"] = campos["pacotes"]
    return event_patch


def enrich_interpreted_payload(text: str, interpreted: dict):
    payload = dict(interpreted or {})
    payload["_texto_original"] = text

    overridden_intent = infer_correction_intent(text)
    if overridden_intent:
        payload["intencao"] = overridden_intent

    if payload.get("intencao") == "corrigir_registro":
        correction_info = build_correction_info(text, payload)
        if correction_info:
            payload["correcao_info"] = correction_info
            event_patch = build_event_patch_from_correction(correction_info)
            if event_patch:
                existing_events = payload.get("eventos") or []
                if existing_events:
                    merged_event = dict(existing_events[0])
                    merged_event.update(event_patch)
                    payload["eventos"] = [merged_event]
                else:
                    payload["eventos"] = [event_patch]

    return payload
