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
    for row in rows:
        rua = row.get("rua")
        numero = row.get("numero")
        nome = row.get("nome_porteiro")
        rua_norm = db.normalize_porteiro_rua(rua)
        numero_norm = db.normalize_porteiro_numero(numero)
        nome_norm = db.normalize_porteiro_nome(nome)

        if rua_norm == rua and numero_norm == numero and nome_norm == nome:
            continue

        db.supabase.table("mapeamento_porteiros").update({
            "rua": rua_norm,
            "numero": numero_norm,
            "nome_porteiro": nome_norm
        }).eq("id", row.get("id")).execute()
        updated += 1

    print(f"Normalizacao concluida. Registros atualizados: {updated}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python normalize_porteiros.py <whatsapp_number>")
        raise SystemExit(1)

    normalize_user_porteiros(sys.argv[1])
