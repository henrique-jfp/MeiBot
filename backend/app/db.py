import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

class DBService:
    def __init__(self):
        url: str = os.getenv("SUPABASE_URL")
        key: str = os.getenv("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)

    def get_user_by_whatsapp(self, whatsapp_number: str):
        try:
            response = self.supabase.table("users").select("*").eq("whatsapp_number", whatsapp_number).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error getting user: {e}")
        return None

    def create_user(self, whatsapp_number: str, nome: str = None):
        try:
            data = {"whatsapp_number": whatsapp_number, "nome": nome}
            response = self.supabase.table("users").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error creating user: {e}")
        return {"id": None, "whatsapp_number": whatsapp_number, "nome": nome}

    def get_active_operation(self, user_id: str):
        if not user_id: return None
        try:
            response = self.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).eq("status", "ativa").execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error getting active op: {e}")
        return None

    def get_or_create_operation_by_date(self, user_id: str, date_str: str, hora_inicio: str = None, hora_fim: str = None):
        if not user_id: return None
        try:
            response = self.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).eq("data", date_str).execute()
            
            h_inicio = f"{date_str}T{hora_inicio}" if hora_inicio else f"{date_str}T08:00:00"
            h_fim = f"{date_str}T{hora_fim}" if hora_fim else f"{date_str}T20:00:00"

            if response.data:
                op = response.data[0]
                if hora_inicio or hora_fim:
                    update_data = {}
                    if hora_inicio: update_data["hora_inicio"] = h_inicio
                    if hora_fim: update_data["hora_fim"] = h_fim
                    self.supabase.table("operacoes_dia").update(update_data).eq("id", op["id"]).execute()
                return op
            
            data = {
                "user_id": user_id, 
                "data": date_str, 
                "status": "encerrada", 
                "hora_inicio": h_inicio,
                "hora_fim": h_fim
            }
            insert_response = self.supabase.table("operacoes_dia").insert(data).execute()
            if insert_response.data:
                return insert_response.data[0]
        except Exception as e:
            print(f"Error in get_or_create_op: {e}")
        return {"id": None}

    def start_operation(self, user_id: str):
        if not user_id: return {"id": None}
        try:
            data = {"user_id": user_id, "status": "ativa"}
            response = self.supabase.table("operacoes_dia").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error starting op: {e}")
        return {"id": None}

    def end_operation(self, operation_id: str):
        if not operation_id: return None
        try:
            import datetime
            data = {"status": "encerrada", "hora_fim": datetime.datetime.now().isoformat()}
            response = self.supabase.table("operacoes_dia").update(data).eq("id", operation_id).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error ending op: {e}")
        return None

    def get_app_id(self, app_name: str):
        if not app_name:
            return None
        try:
            response = self.supabase.table("apps").select("id").ilike("nome", f"%{app_name}%").execute()
            if response.data:
                return response.data[0]['id']
        except Exception as e:
            print(f"Error getting app id: {e}")
        return None

    def add_event(self, user_id: str, operacao_id: str, event_data: dict):
        if not user_id or not operacao_id: return None
        try:
            app_id = self.get_app_id(event_data.get("app"))
            data = {
                "user_id": user_id,
                "operacao_id": operacao_id,
                "tipo": event_data.get("tipo"),
                "categoria": event_data.get("categoria"),
                "valor": event_data.get("valor", 0),
                "km": event_data.get("km", 0),
                "app_id": app_id,
                "pacotes": event_data.get("pacotes", 0),
                "descricao": event_data.get("descricao")
            }
            response = self.supabase.table("eventos").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error adding event: {e}")
        return None

    def get_operation_summary(self, operation_id: str):
        response = self.supabase.table("eventos").select("*").eq("operacao_id", operation_id).execute()
        return response.data

    def get_weekly_summary(self, user_id: str):
        import datetime
        seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(nome)").eq("user_id", user_id).gte("timestamp", seven_days_ago).execute()
        return response.data

    def get_monthly_summary(self, user_id: str):
        import datetime
        thirty_days_ago = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(nome)").eq("user_id", user_id).gte("timestamp", thirty_days_ago).execute()
        return response.data

    def get_all_time_summary(self, user_id: str):
        import datetime
        thirty_days_ago = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(nome)").eq("user_id", user_id).gte("timestamp", thirty_days_ago).execute()
        return response.data
