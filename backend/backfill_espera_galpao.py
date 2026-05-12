import os
import sys
import datetime

sys.path.append(os.path.abspath("."))

from app.db import DBService

DRY_RUN = True


def parse_dt(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text)
    except Exception:
        return None


def backfill_espera_galpao():
    db = DBService()

    updated_existing = 0
    created_new = 0
    skipped = 0

    # 1) Mark existing events that already represent galpao wait
    res = db.supabase.table("eventos").select("id, descricao, hora_inicio, hora_fim, sub_tipo").ilike("descricao", "%galpao%").execute()
    for ev in res.data or []:
        if ev.get("sub_tipo") == "espera_galpao":
            continue
        if not ev.get("hora_inicio") or not ev.get("hora_fim"):
            continue
        updated_existing += 1
        if not DRY_RUN:
            db.supabase.table("eventos").update({"sub_tipo": "espera_galpao"}).eq("id", ev["id"]).execute()

    # 2) Create wait events per operation based on op start -> first event start
    ops = db.supabase.table("operacoes_dia").select("id, user_id, data, hora_inicio").execute().data or []
    for op in ops:
        op_id = op.get("id")
        if not op_id:
            continue

        wait_exists = db.supabase.table("eventos").select("id").eq("operacao_id", op_id).eq("sub_tipo", "espera_galpao").limit(1).execute().data
        if wait_exists:
            skipped += 1
            continue

        op_start = parse_dt(op.get("hora_inicio"))
        if not op_start:
            skipped += 1
            continue

        evs = db.supabase.table("eventos").select("id, hora_inicio, sub_tipo").eq("operacao_id", op_id).order("hora_inicio", desc=False).execute().data or []
        start_route = None
        for ev in evs:
            if ev.get("sub_tipo") == "espera_galpao":
                continue
            start_route = parse_dt(ev.get("hora_inicio"))
            if start_route:
                break

        if not start_route:
            skipped += 1
            continue

        diff_minutes = (start_route - op_start).total_seconds() / 60
        if diff_minutes <= 1:
            skipped += 1
            continue

        payload = {
            "user_id": op.get("user_id"),
            "operacao_id": op_id,
            "tipo": "registro",
            "sub_tipo": "espera_galpao",
            "valor": 0,
            "km": 0,
            "pacotes": 0,
            "descricao": "Espera no galpao (retroativa)",
            "hora_inicio": op.get("hora_inicio"),
            "hora_fim": evs[0].get("hora_inicio")
        }
        if op.get("data"):
            payload["timestamp"] = f"{op['data']}T12:00:00Z"

        created_new += 1
        if not DRY_RUN:
            db.supabase.table("eventos").insert(payload).execute()

    print("Backfill complete")
    print(f"Updated existing: {updated_existing}")
    print(f"Created new: {created_new}")
    print(f"Skipped: {skipped}")
    if DRY_RUN:
        print("DRY_RUN is enabled. No changes were written.")


if __name__ == "__main__":
    backfill_espera_galpao()
