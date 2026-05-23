import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv("backend/.env")

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("Faltam variáveis de ambiente SUPABASE_URL e SUPABASE_KEY")
    exit(1)

try:
    supabase: Client = create_client(url, key)

    print("--- Categorias de Gastos ---")
    res_cat = supabase.table("eventos").select("*").eq("tipo", "gasto").execute()
    gastos = res_cat.data
    
    if not gastos:
        print("Nenhum gasto encontrado na tabela eventos.")
    else:
        categorias = set()
        for g in gastos:
            cat = g.get('categoria')
            if cat:
                categorias.add(str(cat))
        
        essenciais = [g for g in gastos if str(g.get("categoria")).lower() == "essencial" or str(g.get("sub_tipo")).lower() == "essencial"]
        nao_essenciais = [g for g in gastos if str(g.get("categoria")).lower() == "não essencial" or str(g.get("sub_tipo")).lower() == "não essencial" or str(g.get("categoria")).lower() == "nao essencial"]

        print(f"Total de gastos encontrados: {len(gastos)}")
        print(f"\nCategorias distintas encontradas no banco (campo 'categoria'):")
        print(categorias)

        print("\nExemplos de gastos Essenciais (descrição/categoria/sub_tipo):")
        for e in essenciais[:5]: 
            print(f"- Descrição: {e.get('descricao')}, Sub-tipo: {e.get('sub_tipo')}, Categoria: {e.get('categoria')}, Valor: {e.get('valor')}")
        if not essenciais:
             print("  (nenhum encontrado com categoria/sub_tipo 'essencial')")
            
        print("\nExemplos de gastos Não Essenciais (descrição/categoria/sub_tipo):")
        for ne in nao_essenciais[:5]: 
            print(f"- Descrição: {ne.get('descricao')}, Sub-tipo: {ne.get('sub_tipo')}, Categoria: {ne.get('categoria')}, Valor: {ne.get('valor')}")
        if not nao_essenciais:
            print("  (nenhum encontrado com categoria/sub_tipo 'não essencial')")

        print("\n--- Gasto mais recente com combustível ---")
        combustiveis = []
        for g in gastos:
            desc = str(g.get("descricao") or "").lower()
            cat = str(g.get("categoria") or "").lower()
            sub = str(g.get("sub_tipo") or "").lower()
            
            if "combust" in desc or "gasolina" in desc or "combust" in cat or "gasolina" in cat or "combust" in sub or "gasolina" in sub:
                combustiveis.append(g)

        if combustiveis:
            combustiveis.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            mais_recente = combustiveis[0]
            print(f"Data/Hora (timestamp): {mais_recente.get('timestamp')}")
            print(f"Valor: R$ {mais_recente.get('valor')}")
            print(f"Descrição: {mais_recente.get('descricao')}")
            print(f"Categoria: {mais_recente.get('categoria')}")
        else:
            print("Nenhum gasto com combustível encontrado.")
except Exception as e:
    print(f"Erro ao consultar o banco: {e}")
