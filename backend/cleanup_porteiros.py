import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

from db import DBService

DRY_RUN = True


def cleanup_porteiros():
    db = DBService()
    users_res = db.supabase.table("users").select("id").execute()
    users = users_res.data or []

    total_updates = 0
    total_deletes = 0
    total_merges = 0

    for user in users:
        user_id = user.get("id")
        if not user_id:
            continue

        porteiros = db.get_all_porteiros(user_id)
        seen = {}

        for p in porteiros:
            rua_norm = db.normalize_porteiro_rua(p.get("rua"))
            numero_norm = db.normalize_porteiro_numero(p.get("numero"))
            nome_norm = db.normalize_porteiro_nome(p.get("nome_porteiro"))

            key = (user_id, rua_norm, numero_norm, nome_norm)
            keeper = seen.get(key)

            if keeper is None:
                seen[key] = p
                needs_update = False
                update_data = {}

                if p.get("rua") != rua_norm:
                    update_data["rua"] = rua_norm
                    needs_update = True
                if p.get("numero") != numero_norm:
                    update_data["numero"] = numero_norm
                    needs_update = True
                if p.get("nome_porteiro") != nome_norm:
                    update_data["nome_porteiro"] = nome_norm
                    needs_update = True

                if needs_update:
                    total_updates += 1
                    if not DRY_RUN:
                        db.supabase.table("mapeamento_porteiros").update(update_data).eq("id", p["id"]).execute()
                continue

            merge_data = {}
            if not (keeper.get("turno") or "").strip() and (p.get("turno") or "").strip():
                merge_data["turno"] = p.get("turno")
            if not (keeper.get("notas_predio") or "").strip() and (p.get("notas_predio") or "").strip():
                merge_data["notas_predio"] = p.get("notas_predio")

            if merge_data:
                total_merges += 1
                if not DRY_RUN:
                    db.supabase.table("mapeamento_porteiros").update(merge_data).eq("id", keeper["id"]).execute()

            total_deletes += 1
            if not DRY_RUN:
                db.supabase.table("mapeamento_porteiros").delete().eq("id", p["id"]).execute()

    print("Cleanup complete")
    print(f"Users: {len(users)}")
    print(f"Updates: {total_updates}")
    print(f"Merges: {total_merges}")
    print(f"Deletes: {total_deletes}")
    if DRY_RUN:
        print("DRY_RUN is enabled. No changes were written.")


if __name__ == "__main__":
    cleanup_porteiros()
