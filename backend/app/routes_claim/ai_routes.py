import io
import json
import os
import re
import unicodedata

import google.generativeai as genai
from dotenv import load_dotenv

try:
    from google.cloud import vision
    from google.oauth2 import service_account
except Exception as exc:
    print(f"[ROUTE-CLAIM] Google Vision imports unavailable: {exc}")
    vision = None
    service_account = None

try:
    from pdf2image import convert_from_bytes
    from PIL import Image
    PDF_SUPPORT_AVAILABLE = True
except ImportError:
    print("[ROUTE-CLAIM] pdf2image or Pillow not installed. PDF support will be disabled.")
    PDF_SUPPORT_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    print("[ROUTE-CLAIM] pdfplumber not installed.")
    PDFPLUMBER_AVAILABLE = False

load_dotenv()

MIN_DETERMINISTIC_CONFIDENCE = 0.75
IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
PARSER_VERSION = "routes-claim-2026-09-19-priorities-v2"
ROUTES_ENABLE_GEMINI_OCR_FALLBACK = os.getenv("ROUTES_ENABLE_GEMINI_OCR_FALLBACK", "false").lower() == "true"
ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK = os.getenv("ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK", "false").lower() == "true"
VISION_STATUS = {
    "available": False,
    "reason": "not_initialized",
}

_genai_key = os.getenv("GEMINI_API_KEY")
if _genai_key:
    genai.configure(api_key=_genai_key)

_gemini_model_names = [
    name.strip()
    for name in os.getenv("ROUTES_GEMINI_MODELS", "gemini-2.5-flash,gemini-2.0-flash").split(",")
    if name.strip() and "1.5" not in name.strip()
]


def _build_vision_client():
    if vision is None or service_account is None:
        VISION_STATUS["reason"] = "google_cloud_vision_import_unavailable"
        return None

    creds_json = os.getenv("GOOGLE_VISION_CREDENTIALS_JSON")
    if not creds_json:
        VISION_STATUS["reason"] = "missing_GOOGLE_VISION_CREDENTIALS_JSON"
        print("[ROUTE-CLAIM] Vision unavailable: missing GOOGLE_VISION_CREDENTIALS_JSON")
        return None

    try:
        creds_dict = json.loads(creds_json)
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        client = vision.ImageAnnotatorClient(credentials=credentials)
        VISION_STATUS["available"] = True
        VISION_STATUS["reason"] = "ok"
        return client
    except Exception as exc:
        VISION_STATUS["reason"] = str(exc)
        print(f"[ROUTE-CLAIM] Vision unavailable: {exc}")
        return None


_vision_client = _build_vision_client()


def _normalize(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFD", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_no_show(value):
    normalized = _normalize(value)
    # "NS" tambem pode vir junto ao identificador (por exemplo, B-41NS).
    # Os limites por letras evitam falsos positivos em palavras comuns.
    return bool(re.search(r"(?<![a-z])(?:ns|noshow|no\s+show)(?![a-z])", normalized))


def _parse_int(value):
    if value is None:
        return None
    match = re.search(r"\d+", str(value).replace(".", ""))
    return int(match.group(0)) if match else None


def _clean_gaiola(value):
    if not value:
        return None
    match = re.search(r"\b([A-Z])\s*[-–]?\s*(\d{1,3})([A-Z]{0,3})\b", value.upper())
    return f"{match.group(1)}-{match.group(2)}{match.group(3) or ''}" if match else None


def _route_lines(ocr_text):
    lines = []
    for raw_line in ocr_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if re.search(r"\b[A-Z]\s*[-–]?\s*\d{1,3}[A-Z]{0,3}\b", line.upper()):
            lines.append(line)
    return lines


def _route_rows_from_vision_response(response):
    words = []
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    text = "".join(symbol.text for symbol in word.symbols).strip()
                    vertices = word.bounding_box.vertices
                    xs = [vertex.x for vertex in vertices]
                    ys = [vertex.y for vertex in vertices]
                    if not text or not xs or not ys:
                        continue
                    words.append(
                        {
                            "text": text,
                            "x": sum(xs) / len(xs),
                            "y": sum(ys) / len(ys),
                            "height": max(ys) - min(ys),
                        }
                    )

    if not words:
        return []

    median_height = sorted(word["height"] for word in words)[len(words) // 2]
    tolerance = max(8, median_height * 0.75)
    rows = []

    for word in sorted(words, key=lambda item: item["y"]):
        for row in rows:
            if abs(row["y"] - word["y"]) <= tolerance:
                row["words"].append(word)
                row["y"] = sum(item["y"] for item in row["words"]) / len(row["words"])
                break
        else:
            rows.append({"y": word["y"], "words": [word]})

    row_texts = []
    for row in sorted(rows, key=lambda item: item["y"]):
        ordered = sorted(row["words"], key=lambda item: item["x"])
        text = " ".join(item["text"] for item in ordered)
        if re.search(r"\b[A-Z]\s*[-–]?\s*\d{1,3}[A-Z]{0,3}\b", text.upper()):
            row_texts.append(text)

    return row_texts


def _extract_total_packages(line):
    normalized = _normalize(line)
    total_patterns = (
        r"(?:total|pacotes|pct|pcts|qtd)\D{0,8}(\d{1,4})",
        r"(\d{1,4})\D{0,8}(?:pacotes|pct|pcts)",
    )
    for pattern in total_patterns:
        match = re.search(pattern, normalized)
        if match:
            return _parse_int(match.group(1))

    numbers = [_parse_int(item) for item in re.findall(r"\b\d{1,4}\b", line)]
    numbers = [item for item in numbers if item is not None]
    return max(numbers) if numbers else None


def _extract_litragem(line):
    """Extrai litragem apenas quando ela estiver identificada na propria linha."""
    normalized = _normalize(line)
    match = re.search(r"\b(?:litragem|litros?|volume)\s*[:=-]?\s*(\d{1,6})\b", normalized)
    return _parse_int(match.group(1)) if match else None


def _extract_cluster(line, gaiola):
    if not gaiola:
        return None

    compact = gaiola.replace("-", r"\s*[-–]?\s*")
    match = re.search(rf"\b{compact}\b", line, flags=re.IGNORECASE)
    if not match:
        return None

    cleaned = line[match.end():]
    cleaned = re.sub(r"^\s*(?:SPR|CLUSTER|BAIRRO|PACOTES|TOTAL|LITRAGEM)?\s*\d{1,4}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.split(r"\b(?:ROTA\s+MISTA|PASSEIO|FIORINO|MOTO|MOTOS|VOLUMOSO)\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]

    known_clusters = (
        "Lins de Vasconcelos", "Engenho da Rainha", "Engenho Novo", "Engenho de Dentro",
        "Del Castilho", "Jardim Botânico", "Copacabana 1", "Copacabana 2", "Botafogo 2",
        "Botafogo 1", "Nova Brasília", "Água de Ouro", "Cinco Bocas", "Cachambi",
        "Mangueira", "Tabajara", "Tabajaras", "Copacabana", "Ipanema", "Leblon",
        "Rocinha", "Vidigal", "Gávea", "Lagoa", "Urca", "Inhaúma", "Jacaré",
        "Méier", "Piedade", "Abolição", "Pilares", "Camarista", "Dendê", "Maré",
        "Penha", "Ramos", "Cruzeiro", "Barra", "Andaraí", "Cacuia", "Grajaú",
        "Taquara", "Marechal Hermes", "Portuguesa", "Jardim Carioca", "Aldeia Campista",
        "Flamengo", "Jockey", "Bonsucesso", "Rocha", "Méier"
    )
    for cluster in sorted(known_clusters, key=len, reverse=True):
        if re.search(rf"\b{re.escape(cluster)}\b", cleaned, flags=re.IGNORECASE):
            return cluster

    first_cell = re.split(r";|\s{2,}", cleaned, maxsplit=1)[0]
    first_cell = re.sub(r"[^A-Za-zÀ-ÿ ]+", " ", first_cell)
    return re.sub(r"\s+", " ", first_cell).strip() or None


def _parse_routes_from_text(ocr_text, source="vision_parser"):
    return _parse_routes_from_lines(_route_lines(ocr_text), source)


def _parse_routes_from_lines(lines, source):
    routes = []
    for line in lines:
        gaiola = _clean_gaiola(line)
        if not gaiola:
            continue

        cluster = _extract_cluster(line, gaiola)

        modal_match = re.search(r"\b(ROTA\s+MISTA|CARRO\s+PASSEIO|PASSEIO|FIORINO|MOTO|MOTOS|VOLUMOSO)\b", line, flags=re.IGNORECASE)
        modal = modal_match.group(1).upper() if modal_match else None

        routes.append(
            {
                "gaiola": gaiola,
                "bairro": cluster,
                "pacotes_total": _extract_total_packages(line),
                "dissecacao": {}, # OCR determinístico raramente pega dissecação bem
                "modal": modal,
                "litragem": _extract_litragem(line),
            }
        )

    named_routes = sum(1 for route in routes if route.get("bairro"))
    if routes and named_routes / len(routes) >= 0.5:
        confidence = 0.8
    elif routes:
        confidence = 0.6 # OCR puro é menos confiável que IA para lógica complexa
    else:
        confidence = 0.0

    return {
        "routes": routes,
        "confidence": confidence,
        "source": source,
    }


def _extract_text_with_pdfplumber(file_bytes):
    if not PDFPLUMBER_AVAILABLE:
        return ""
    
    try:
        text_lines = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(layout=True)
                if page_text:
                    text_lines.append(page_text)
        return "\n".join(text_lines)
    except Exception as exc:
        print(f"[ROUTE-CLAIM] pdfplumber error: {exc}")
        return ""


def _extract_text_with_vision(file_bytes):
    if not _vision_client:
        return "", []

    image = vision.Image(content=file_bytes)
    response = _vision_client.document_text_detection(image=image)
    if response.error.message:
        VISION_STATUS["reason"] = response.error.message
        print(f"[ROUTE-CLAIM] Vision OCR error: {response.error.message}")
        return "", []

    if not response.full_text_annotation:
        return "", []

    return response.full_text_annotation.text, _route_rows_from_vision_response(response)


def _compact_ocr_for_gemini(ocr_text):
    relevant = []
    for line in ocr_text.splitlines():
        normalized = _normalize(line)
        if (
            re.search(r"\b[a-z]\s*[-–]?\s*\d{1,3}[a-z]{0,3}\b", normalized)
            or any(token in normalized for token in ("pacote", "total", "dissec", "bairro", "rota"))
        ):
            relevant.append(line.strip())

    compact = "\n".join(line for line in relevant if line)
    return compact[:6000]


def _parse_json_response(text):
    cleaned = text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _normalize_ai_routes(parsed):
    raw_routes = parsed if isinstance(parsed, list) else parsed.get("routes", [])
    routes = []

    for item in raw_routes if isinstance(raw_routes, list) else []:
        if not isinstance(item, dict):
            continue

        gaiola = _clean_gaiola(item.get("gaiola") or item.get("Gaiola") or item.get("route"))
        if not gaiola:
            continue

        dissecacao = item.get("dissecacao") or item.get("bairros") or {}
        if not isinstance(dissecacao, dict):
            dissecacao = {}

        normalized_dissecacao = {str(k): _parse_int(v) for k, v in dissecacao.items()}

        routes.append(
            {
                "gaiola": gaiola,
                "bairro": item.get("bairro") or item.get("cluster") or item.get("Cluster"),
                "pacotes_total": _parse_int(
                    item.get("pacotes_total")
                    or item.get("spr")
                    or item.get("SPR")
                    or item.get("pacotes")
                ),
                "dissecacao": normalized_dissecacao,
                "modal": str(item.get("modal") or item.get("MODAL") or "").strip(),
                "litragem": _parse_int(item.get("litragem") or item.get("LITRAGEM")),
            }
        )

    return routes


def _confidence_for_routes(routes, source):
    if routes:
        return 0.9 if source.startswith("gemini") else 0.6
    return 0.0


ROUTE_PRIORITY_TIERS = (
    (1, ("urca",)),
    (2, ("tabajara", "tabajaras")),
    (3, ("copacabana 1", "copacabana 2", "copacabana", "copa")),
    (4, ("ipanema",)),
    (5, ("botafogo 2", "botafogo 1")),
)


def _has_route_alias(value, aliases):
    normalized = _normalize(value)
    for alias in aliases:
        target = _normalize(alias)
        if re.search(rf"(?<![a-z]){re.escape(target)}(?![a-z])", normalized):
            return True
    return False


def _route_tier(route):
    # O cluster e a dissecação são ambos considerados: uma rota mista que atende
    # Urca continua sendo preferível mesmo quando o cluster tem outro nome.
    locations = [route.get("bairro")]
    dissecacao = route.get("dissecacao")
    if isinstance(dissecacao, dict):
        locations.extend(dissecacao.keys())

    for tier, aliases in ROUTE_PRIORITY_TIERS:
        if any(_has_route_alias(location, aliases) for location in locations if location):
            return tier
    return None


def _is_allowed_modal(modal):
    normalized = _normalize(modal)
    if not normalized:
        return False
    if any(blocked in normalized for blocked in ("moto", "fiorino", "volumoso")):
        return False
    return "mista" in normalized or "passeio" in normalized


def rank_route_candidates(routes):
    """Retorna somente rotas elegíveis, na ordem determinística de solicitação."""
    candidates = []
    for route in routes or []:
        if not isinstance(route, dict) or not route.get("gaiola"):
            continue
        if not _is_allowed_modal(route.get("modal")):
            continue
        tier = _route_tier(route)
        if tier is None:
            continue

        litragem = _parse_int(route.get("litragem"))
        pacotes = _parse_int(route.get("pacotes_total"))
        candidates.append({
            **route,
            "tier": tier,
            "litragem": litragem,
            "pacotes_total": pacotes,
        })

    # Bairro é absoluto. Dentro do mesmo bairro, menor litragem prevalece;
    # sem litragem comparável, a rota com menos pacotes prevalece.
    return sorted(
        candidates,
        key=lambda route: (
            route["tier"],
            route["litragem"] is None,
            route["litragem"] if route["litragem"] is not None else float("inf"),
            route["pacotes_total"] is None,
            route["pacotes_total"] if route["pacotes_total"] is not None else float("inf"),
            0 if "passeio" in _normalize(route.get("modal")) else 1,
            _normalize(route.get("gaiola")),
        ),
    )


def _with_selection(parsed):
    ranked = rank_route_candidates(parsed.get("routes"))
    parsed["eligible_routes"] = ranked
    parsed["selected_route"] = ranked[0] if ranked else None
    return parsed


def _fallback_with_gemini(file_bytes, mime_type, ocr_text=""):
    if not _genai_key or not _gemini_model_names:
        return {"routes": [], "confidence": 0.0, "source": "no_gemini"}

    prompt = (
        "Voce é um especialista em transcrição de planilhas de rotas logísticas. "
        "As imagens podem ter cabeçalho completo, cabeçalho cortado ou nenhum cabeçalho. "
        "Podem existir colunas extras antes/depois da gaiola e os nomes das colunas podem variar. "
        "Identifique visualmente cada célula pela posição da tabela. "
        "As colunas normalmente são GAIOLA, SPR (total de pacotes), CLUSTER (bairro principal), "
        "BAIRROS (detalhamento/dissecação), MODAL e LITRAGEM. "
        "Extraia TODAS as linhas de rota visíveis. "
        "Regras cruciais: "
        "1. Seja LITERAL: transcreva os nomes dos bairros e modais exatamente como aparecem. "
        "2. GAIOLA pode ter sufixos (ex: B-41, G-48NS). "
        "3. SPR é o total de pacotes da rota. "
        "4. BAIRROS contém a dissecação por sub-bairro (ex: 'Copacabana: 20, Leme: 5'). "
        "5. MODAL indica o veículo (ex: 'ROTA MISTA', 'PASSEIO', 'FIORINO'). "
        "6. LITRAGEM (se houver) é o volume total numérico, extraia o número. "
        "Retorne APENAS um JSON no formato: "
        '{"routes":[{"gaiola":"B-41","bairro":"Copacabana","pacotes_total":124,"modal":"ROTA MISTA","litragem":660,'
        '"dissecacao":{"Copacabana":57,"Leme":30,"Tabajaras":37}}]}. '
        "Use null quando faltar número ou texto, e {} quando não houver dissecação."
    )

    source = "gemini_ocr_fallback" if ocr_text else "gemini_image_fallback"
    last_error = None
    for model_name in _gemini_model_names:
        try:
            model = genai.GenerativeModel(model_name)
            if ocr_text:
                response = model.generate_content(
                    [prompt, "OCR text:\n" + _compact_ocr_for_gemini(ocr_text)],
                    generation_config={"response_mime_type": "application/json"},
                )
            else:
                response = model.generate_content(
                    [prompt, {"mime_type": mime_type, "data": file_bytes}],
                    generation_config={"response_mime_type": "application/json"},
                )

            parsed = _parse_json_response(response.text)
            routes = _normalize_ai_routes(parsed)
            return {
                "routes": routes,
                "confidence": _confidence_for_routes(routes, source),
                "source": f"{source}:{model_name}",
            }
        except Exception as exc:
            last_error = exc
            print(f"[ROUTE-CLAIM] Gemini fallback failed model={model_name}: {exc}")

    return {
        "routes": [],
        "confidence": 0.0,
        "source": "gemini_fallback_failed",
        "error_detail": str(last_error) if last_error else None,
    }


def parse_route_sheet(file_bytes: bytes, mime_type: str, file_name: str = "", caption: str = ""):
    if _contains_no_show(f"{file_name} {caption}"):
        return {"routes": [], "eligible_routes": [], "selected_route": None, "confidence": 0.0, "source": "ignored_no_show", "no_show": True, "parser_version": PARSER_VERSION}

    ocr_text = ""
    ocr_rows = []

    # Fluxo Prioritário para PDF: pdfplumber (Direto no texto)
    if mime_type == "application/pdf" and PDFPLUMBER_AVAILABLE:
        pdf_text = _extract_text_with_pdfplumber(file_bytes)
        if _contains_no_show(pdf_text):
            return {"routes": [], "eligible_routes": [], "selected_route": None, "confidence": 0.0, "source": "ignored_no_show", "no_show": True, "parser_version": PARSER_VERSION}
        if pdf_text:
            pdf_parsed = _parse_routes_from_text(pdf_text, source="pdfplumber_parser")
            if pdf_parsed["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                pdf_parsed["parser_version"] = PARSER_VERSION
                return _with_selection(pdf_parsed)
            print(f"[ROUTE-CLAIM] pdfplumber confidence low ({pdf_parsed['confidence']}), falling back to image/vision")

    # Fallback para PDF ou fluxo de Imagem: OCR via Google Vision
    img_bytes = file_bytes
    actual_mime = mime_type

    if mime_type == "application/pdf" and PDF_SUPPORT_AVAILABLE:
        try:
            images = convert_from_bytes(file_bytes, first_page=1, last_page=1, fmt="jpeg", dpi=300)
            if images:
                img_byte_arr = io.BytesIO()
                images[0].save(img_byte_arr, format="JPEG")
                img_bytes = img_byte_arr.getvalue()
                actual_mime = "image/jpeg"
                print("[ROUTE-CLAIM] PDF converted to JPEG (300 DPI) for Vision fallback")
        except Exception as exc:
            print(f"[ROUTE-CLAIM] PDF conversion failed: {exc}")

    deterministic = {
        "routes": [],
        "confidence": 0.0,
        "source": "unsupported",
        "parser_version": PARSER_VERSION,
        "vision_available": VISION_STATUS["available"],
        "vision_reason": VISION_STATUS["reason"],
        "ocr_text_len": 0,
        "ocr_rows": 0,
    }

    if actual_mime in IMAGE_MIME_TYPES:
        ocr_text, ocr_rows = _extract_text_with_vision(img_bytes)
        if _contains_no_show(ocr_text):
            return {"routes": [], "eligible_routes": [], "selected_route": None, "confidence": 0.0, "source": "ignored_no_show", "no_show": True, "parser_version": PARSER_VERSION}
        if ocr_rows:
            deterministic = _parse_routes_from_lines(ocr_rows, "vision_geometry_parser")
            deterministic["parser_version"] = PARSER_VERSION
            deterministic["vision_available"] = VISION_STATUS["available"]
            deterministic["vision_reason"] = VISION_STATUS["reason"]
            deterministic["ocr_text_len"] = len(ocr_text or "")
            deterministic["ocr_rows"] = len(ocr_rows)
            
            if deterministic["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                return _with_selection(deterministic)
        if ocr_text:
            deterministic = _parse_routes_from_text(ocr_text, source="vision_parser")
            deterministic["parser_version"] = PARSER_VERSION
            deterministic["vision_available"] = VISION_STATUS["available"]
            deterministic["vision_reason"] = VISION_STATUS["reason"]
            deterministic["ocr_text_len"] = len(ocr_text or "")
            deterministic["ocr_rows"] = len(ocr_rows)
            if deterministic["confidence"] >= MIN_DETERMINISTIC_CONFIDENCE:
                return _with_selection(deterministic)

    if ROUTES_ENABLE_GEMINI_IMAGE_FALLBACK:
        fallback = _fallback_with_gemini(img_bytes, actual_mime)
        fallback["parser_version"] = PARSER_VERSION
        fallback["vision_available"] = VISION_STATUS["available"]
        fallback["vision_reason"] = VISION_STATUS["reason"]
        fallback["ocr_text_len"] = len(ocr_text or "")
        fallback["ocr_rows"] = len(ocr_rows)
        if fallback["routes"]:
            return _with_selection(fallback)

    if not (bool(ocr_text) and ROUTES_ENABLE_GEMINI_OCR_FALLBACK):
        deterministic["source"] = (
            f"ocr_parse_failed_gemini_disabled (source={deterministic.get('source')})"
            if ocr_text or ocr_rows
            else "no_ocr_gemini_disabled"
        )
        deterministic["ocr_text_len"] = len(ocr_text or "")
        deterministic["ocr_rows"] = len(ocr_rows)
        return _with_selection(deterministic)

    fallback = _fallback_with_gemini(img_bytes, actual_mime, ocr_text)
    fallback["parser_version"] = PARSER_VERSION
    fallback["vision_available"] = VISION_STATUS["available"]
    fallback["vision_reason"] = VISION_STATUS["reason"]
    fallback["ocr_text_len"] = len(ocr_text or "")
    fallback["ocr_rows"] = len(ocr_rows)
    if fallback["routes"]:
        return _with_selection(fallback)

    if fallback.get("source") == "gemini_fallback_failed":
        return _with_selection(fallback)
    return _with_selection(deterministic)
