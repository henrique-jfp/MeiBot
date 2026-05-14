import os
import asyncio
import json
from dotenv import load_dotenv

# Use absolute path to backend app
import sys
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.ai_service import AIService

async def test_interpretation():
    # As chaves devem ser lidas do ambiente ou do arquivo .env
    load_dotenv('backend/.env')
    
    ai = AIService()
    text = "dia 13/05/2026 fiz Correios. Cheguei no galpão às 13:20 e saí para a rota às 14:40. Entreguei 154 pacotes no total e finalizei o dia às 18:45. Gastei 12 com cigarro e 11 com açai."
    
    print(f"Testing message: {text}")
    result = await ai.interpret_message(text)
    print("Result:")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(test_interpretation())
