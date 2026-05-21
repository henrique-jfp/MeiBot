import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import DBService


def normalize_user_porteiros(whatsapp):
    db = DBService()
    user = db.get_user_by_whatsapp(whatsapp)
    if not user or not user.get("id"):
        print(f"Usuario {whatsapp} nao encontrado.")
        return

    user_id = user["id"]
    rows = db.get_all_porteiros(user_id)
    if not rows:
        print("Nenhum porteiro encontrado.")
        return

    updated = 0
    deleted = 0
    for row in rows:
        row_id = row.get("id")
        rua = row.get("rua")
        numero = row.get("numero")
        nome = row.get("nome_porteiro")
        
        rua_norm = db.normalize_porteiro_rua(rua)
        numero_norm = db.normalize_porteiro_numero(numero)
        nome_norm = db.normalize_porteiro_nome(nome)

        # Se ja estiver normalizado, pula
        if rua_norm == rua and numero_norm == numero and nome_norm == nome:
            continue

        # Verifica se ja existe um registro com os valores normalizados (Deduplicacao)
        check = db.supabase.table("mapeamento_porteiros").select("id")\
            .eq("user_id", user_id)\
            .eq("rua", rua_norm)\
            .eq("numero", numero_norm)\
            .eq("nome_porteiro", nome_norm)\
            .execute()
        
        if check.data and len(check.data) > 0:
            # Ja existe o registro correto. Apaga o "sujo".
            print(f"Mesclando: {rua} {numero} -> {rua_norm} {numero_norm} (Ja existia, apagando duplicata)")
            db.supabase.table("mapeamento_porteiros").delete().eq("id", row_id).execute()
            deleted += 1
        else:
            # Nao existe o correto. Atualiza o atual.
            print(f"Normalizando: {rua} {numero} -> {rua_norm} {numero_norm}")
            db.supabase.table("mapeamento_porteiros").update({
                "rua": rua_norm,
                "numero": numero_norm,
                "nome_porteiro": nome_norm
            }).eq("id", row_id).execute()
            updated += 1

    print(f"\nResumo da Limpeza para {whatsapp}:")
    print(f"- Registros normalizados: {updated}")
    print(f"- Duplicatas removidas: {deleted}")
    print(f"- Total de acoes: {updated + deleted}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python normalize_porteiros.py <whatsapp_number>")
        raise SystemExit(1)

    normalize_user_porteiros(sys.argv[1])
