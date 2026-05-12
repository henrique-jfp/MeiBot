import os
import re
import unicodedata
import datetime
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
            # 1. Tenta achar a que está marcada como 'ativa'
            response = self.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).eq("status", "ativa").execute()
            if response.data:
                return response.data[0]
            
            # 2. Se não achou 'ativa', tenta achar qualquer uma de HOJE
            import datetime
            today = datetime.date.today().isoformat()
            response = self.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).eq("data", today).execute()
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
            import datetime
            now = datetime.datetime.now().isoformat()
            data = {"user_id": user_id, "status": "ativa", "hora_inicio": now}
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

    def get_app_by_name(self, app_name: str):
        if not app_name: return None
        try:
            response = self.supabase.table("apps").select("*").ilike("nome", f"%{app_name}%").execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error getting app: {e}")
        return None

    def update_app_params(self, app_id: int, valor_base: float, tipo_remuneracao: str, entregador_id: str = None):
        try:
            data = {
                "valor_base": valor_base,
                "tipo_remuneracao": tipo_remuneracao,
                "entregador_padrao_id": entregador_id
            }
            response = self.supabase.table("apps").update(data).eq("id", app_id).execute()
            return response.data
        except Exception as e:
            print(f"Error updating app params: {e}")
            return None

    @staticmethod
    def _normalize_event_time(value, data_ref: str = None):
        if not value:
            return None
        text = str(value).strip()
        if "T" in text:
            return text
        if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", text):
            date_str = data_ref or datetime.date.today().isoformat()
            time_str = text if len(text) == 8 else f"{text}:00"
            return f"{date_str}T{time_str}"
        return text

    def add_event(self, user_id: str, operacao_id: str, event_data: dict):
        if not user_id or not operacao_id: 
            print(f"DEBUG DB: Falha ao salvar evento. User: {user_id}, Op: {operacao_id}")
            return None
        try:
            data_ref = event_data.get("data_referencia")
            # Busca app_id se o nome for fornecido
            app_id = None
            if event_data.get("app"):
                app_info = self.get_app_by_name(event_data.get("app"))
                app_id = app_info["id"] if app_info else None
            
            # Garante que números sejam números
            def to_float(v):
                try: return float(v or 0)
                except: return 0.0

            data = {
                "user_id": user_id,
                "operacao_id": operacao_id,
                "tipo": str(event_data.get("tipo") or "registro"),
                "sub_tipo": event_data.get("sub_tipo"),
                "valor": to_float(event_data.get("valor")),
                "km": to_float(event_data.get("km") or event_data.get("km_rota")),
                "app_id": app_id,
                "pacotes": int(event_data.get("pacotes") or 0),
                "descricao": event_data.get("descricao") or event_data.get("pergunta"),
                "categoria": event_data.get("categoria"),
                "hora_inicio": self._normalize_event_time(
                    event_data.get("hora_inicio") or event_data.get("hora_inicio_rota"),
                    data_ref
                ),
                "hora_fim": self._normalize_event_time(
                    event_data.get("hora_fim") or event_data.get("hora_fim_operacao"),
                    data_ref
                )
            }
            
            # Se tiver data específica no evento
            if data_ref:
                data["timestamp"] = f"{data_ref}T12:00:00Z"

            print(f"DEBUG DB: Inserindo evento: {data['tipo']} - R$ {data['valor']}")
            response = self.supabase.table("eventos").insert(data).execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error adding event: {e}")
        return None

    def add_entregador(self, user_id: str, nome: str, valor_diaria: float):
        try:
            data = {"user_id": user_id, "nome": nome, "valor_diaria": valor_diaria}
            response = self.supabase.table("entregadores").insert(data).execute()
            return response.data
        except Exception as e:
            print(f"Error adding entregador: {e}")
            return None

    def get_entregador_by_name(self, user_id: str, nome: str):
        try:
            response = self.supabase.table("entregadores").select("*").eq("user_id", user_id).ilike("nome", f"%{nome}%").execute()
            if response.data:
                return response.data[0]
        except Exception as e:
            print(f"Error getting entregador: {e}")
        return None

    def get_operation_summary(self, operation_id: str):
        response = self.supabase.table("eventos").select("*, apps(*)").eq("operacao_id", operation_id).execute()
        return response.data

    def get_weekly_summary(self, user_id: str):
        import datetime
        # Usando 8 dias para garantir cobertura de fuso horário
        seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=8)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", seven_days_ago).execute()
        return response.data

    def get_previous_weekly_summary(self, user_id: str):
        import datetime
        now = datetime.datetime.now()
        seven_days_ago = (now - datetime.timedelta(days=8)).isoformat()
        fourteen_days_ago = (now - datetime.timedelta(days=16)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", fourteen_days_ago).lt("timestamp", seven_days_ago).execute()
        return response.data

    def get_monthly_summary(self, user_id: str):
        import datetime
        thirty_days_ago = (datetime.datetime.now() - datetime.timedelta(days=31)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", thirty_days_ago).execute()
        return response.data

    def get_previous_monthly_summary(self, user_id: str):
        import datetime
        now = datetime.datetime.now()
        thirty_days_ago = (now - datetime.timedelta(days=30)).isoformat()
        sixty_days_ago = (now - datetime.timedelta(days=60)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", sixty_days_ago).lt("timestamp", thirty_days_ago).execute()
        return response.data

    def get_operations_for_period(self, user_id: str, days: int):
        import datetime
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        response = self.supabase.table("operacoes_dia").select("*").eq("user_id", user_id).gte("hora_inicio", start_date).execute()
        return response.data

    def get_all_time_summary(self, user_id: str):
        import datetime
        thirty_days_ago = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
        response = self.supabase.table("eventos").select("*, apps(*)").eq("user_id", user_id).gte("timestamp", thirty_days_ago).execute()
        return response.data

    # --- NORMALIZACAO DE PORTEIROS ---

    @staticmethod
    def _clean_text(value: str):
        if value is None:
            return ""
        text = unicodedata.normalize("NFKC", str(value))
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _title_keep_small_words(text: str):
        if not text:
            return text
        small_words = {"de", "da", "do", "das", "dos", "e"}
        words = []
        for w in text.split(" "):
            low = w.lower()
            if low in small_words:
                words.append(low)
            elif w.isupper() and len(w) <= 3:
                words.append(w)
            else:
                words.append(w.capitalize())
        return " ".join(words)

    @classmethod
    def normalize_porteiro_rua(cls, rua: str):
        text = cls._clean_text(rua)
        if not text:
            return "Sem Rua"

        text = re.sub(r"\b(r|r\.)\b", "Rua", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(av|av\.|avenida)\b", "Avenida", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(trav|trav\.|travessa)\b", "Travessa", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()

        text_upper = text.upper()
        if "PAISANDU" in text_upper or "PAISSANDU" in text_upper:
            return "Paissandu"

        return cls._title_keep_small_words(text)

    @classmethod
    def normalize_porteiro_numero(cls, numero: str):
        text = cls._clean_text(numero)
        if not text:
            return "Sem Numero"
        text = re.sub(r"^(n|n\.|nº|no|n°)\s*", "", text, flags=re.IGNORECASE)
        text = text.replace("N°", "").replace("Nº", "")
        text = re.sub(r"\s+", " ", text).strip()
        return text.upper() if text else "Sem Numero"

    @classmethod
    def normalize_porteiro_nome(cls, nome: str):
        text = cls._clean_text(nome)
        if not text:
            return "Porteiro Desconhecido"
        text = text.strip('"“”')
        return cls._title_keep_small_words(text)

    # --- MAPEAMENTO DE PORTEIROS ---

    def add_porteiro(self, user_id: str, rua: str, numero: str, nome: str, turno: str = None, notas: str = None):
        try:
            rua_norm = self.normalize_porteiro_rua(rua)
            numero_norm = self.normalize_porteiro_numero(numero)
            nome_norm = self.normalize_porteiro_nome(nome)
            data = {
                "user_id": user_id,
                "rua": rua_norm,
                "numero": numero_norm,
                "nome_porteiro": nome_norm,
                "turno": turno,
                "notas_predio": self._clean_text(notas) if notas else None
            }
            response = self.supabase.table("mapeamento_porteiros").insert(data).execute()
            return response.data
        except Exception as e:
            if "duplicate key value" in str(e):
                return "DUPLICATE"
            print(f"Error adding porteiro: {e}")
            return None

    def update_porteiro(self, user_id: str, rua: str, numero: str, nome_antigo: str, novo_nome: str = None, novo_turno: str = None, novas_notas: str = None):
        try:
            rua_norm = self.normalize_porteiro_rua(rua)
            numero_norm = self.normalize_porteiro_numero(numero)
            nome_antigo_norm = self.normalize_porteiro_nome(nome_antigo)
            update_data = {}
            if novo_nome: update_data["nome_porteiro"] = self.normalize_porteiro_nome(novo_nome)
            if novo_turno: update_data["turno"] = novo_turno
            if novas_notas: update_data["notas_predio"] = self._clean_text(novas_notas)
            response = self.supabase.table("mapeamento_porteiros").update(update_data).eq("user_id", user_id).eq("rua", rua_norm).eq("numero", numero_norm).eq("nome_porteiro", nome_antigo_norm).execute()
            return response.data
        except Exception as e:
            print(f"Error updating porteiro: {e}")
            return None

    def get_porteiros_by_address(self, user_id: str, rua: str, numero: str):
        try:
            rua_norm = self.normalize_porteiro_rua(rua)
            numero_norm = self.normalize_porteiro_numero(numero)
            response = self.supabase.table("mapeamento_porteiros").select("*").eq("user_id", user_id).eq("rua", rua_norm).eq("numero", numero_norm).execute()
            return response.data
        except Exception as e:
            print(f"Error getting porteiros: {e}")
            return []

    def get_all_porteiros(self, user_id: str):
        try:
            response = self.supabase.table("mapeamento_porteiros").select("*").eq("user_id", user_id).order("rua").order("numero").execute()
            return response.data
        except Exception as e:
            print(f"Error getting all porteiros: {e}")
            return []

    # --- HISTÓRICO DE ANÁLISES ---

    def save_analysis(self, user_id: str, periodo_tipo: str, metrics: dict, insight: str):
        """
        Salva uma análise (semanal ou mensal) para persistência histórica.
        periodo_tipo: 'semanal' ou 'mensal'
        """
        try:
            import datetime
            data = {
                "user_id": user_id,
                "periodo_tipo": periodo_tipo,
                "metrics": metrics,
                "insight": insight,
                "created_at": datetime.datetime.now().isoformat()
            }
            # Tenta inserir na tabela historico_analises. 
            # Nota: A tabela deve existir no Supabase.
            response = self.supabase.table("historico_analises").insert(data).execute()
            return response.data
        except Exception as e:
            print(f"Error saving analysis to DB: {e}")
            return None

    def get_analysis_history(self, user_id: str, limit: int = 10):
        try:
            response = self.supabase.table("historico_analises")\
                .select("*")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            return response.data
        except Exception as e:
            print(f"Error getting analysis history: {e}")
            return []
