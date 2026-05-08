import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini for route parsing
_genai_key = os.getenv("GEMINI_API_KEY")
if _genai_key:
    genai.configure(api_key=_genai_key)

_gemini_model = genai.GenerativeModel('gemini-1.5-flash')


def parse_route_sheet(file_bytes: bytes, mime_type: str):
    prompt = """
    You are reading a route sheet from a delivery group.
    Extract ONLY the fields below for each route line you can read:
    - gaiola (format like A-1, B-52, F-53)
    - bairro (main neighborhood column)
    - pacotes_total (total packages for the route)
    - dissecacao (if present, map of neighborhood -> packages)

    Return ONLY JSON in this format:
    {
      "routes": [
        {
          "gaiola": "B-52",
          "bairro": "Rocinha",
          "pacotes_total": 136,
          "dissecacao": {"Rocinha": 50, "Gavea": 32}
        }
      ]
    }

    If a field is missing, use null. If dissecacao is not present, use an empty object.
    """

    response = _gemini_model.generate_content([
        prompt,
        {"mime_type": mime_type, "data": file_bytes}
    ])

    text = response.text.replace('```json', '').replace('```', '').strip()
    return json.loads(text)
