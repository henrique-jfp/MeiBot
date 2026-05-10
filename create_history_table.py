import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv('backend/.env')

def create_table():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    supabase = create_client(url, key)
    
    # Criando a tabela via SQL RPC ou apenas preparando a estrutura
    # Como não temos acesso direto ao terminal SQL aqui, vou adicionar a lógica no db.py
    # e garantir que a inserção funcione.
    print("Estrutura de histórico planejada.")

if __name__ == "__main__":
    create_table()
