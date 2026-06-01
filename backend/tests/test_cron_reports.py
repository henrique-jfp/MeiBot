import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cron_reports import resolve_report_period, save_or_update_analysis


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db):
        self.db = db
        self.mode = None
        self.payload = None
        self.filters = []

    def select(self, *_args):
        self.mode = "select"
        return self

    def update(self, payload):
        self.mode = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def execute(self):
        if self.mode == "select":
            rows = self.db.analyses
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]
            return FakeResponse(rows)

        if self.mode == "update":
            target_id = next(value for key, value in self.filters if key == "id")
            for row in self.db.analyses:
                if row.get("id") == target_id:
                    row.update(self.payload)
                    self.db.updated = True
                    return FakeResponse([row])
            return FakeResponse([])

        if self.mode == "insert":
            row = {"id": "new-analysis", **self.payload}
            self.db.analyses.append(row)
            self.db.inserted = True
            return FakeResponse([row])

        return FakeResponse([])


class FakeSupabase:
    def __init__(self, db):
        self.db = db

    def table(self, name):
        self.db.last_table = name
        return FakeQuery(self.db)


class FakeDB:
    def __init__(self, analyses=None):
        self.analyses = analyses or []
        self.updated = False
        self.inserted = False
        self.last_table = None
        self.supabase = FakeSupabase(self)


class CronReportsPeriodTests(unittest.TestCase):
    def test_mensal_no_primeiro_dia_fecha_mes_anterior(self):
        period = resolve_report_period("mensal", reference_date=datetime.date(2026, 6, 1))

        self.assertEqual(period.start, datetime.date(2026, 5, 1))
        self.assertEqual(period.end, datetime.date(2026, 5, 31))
        self.assertEqual(period.label, "01/05 a 31/05")

    def test_semanal_no_sabado_fecha_segunda_a_sabado(self):
        period = resolve_report_period("semanal", reference_date=datetime.date(2026, 5, 30))

        self.assertEqual(period.start, datetime.date(2026, 5, 25))
        self.assertEqual(period.end, datetime.date(2026, 5, 30))
        self.assertEqual(period.label, "25/05 a 30/05")

    def test_semanal_no_domingo_usa_sabado_anterior(self):
        period = resolve_report_period("semanal", reference_date=datetime.date(2026, 5, 31))

        self.assertEqual(period.start, datetime.date(2026, 5, 25))
        self.assertEqual(period.end, datetime.date(2026, 5, 30))

    def test_periodo_explicito_para_backfill(self):
        period = resolve_report_period("mensal", start_date="2026-05-01", end_date="2026-05-31")

        self.assertEqual(period.start, datetime.date(2026, 5, 1))
        self.assertEqual(period.end, datetime.date(2026, 5, 31))

    def test_backfill_exige_datas_juntas(self):
        with self.assertRaises(ValueError):
            resolve_report_period("semanal", start_date="2026-05-25")

    def test_save_or_update_atualiza_periodo_existente(self):
        period = resolve_report_period("semanal", start_date="2026-05-25", end_date="2026-05-30")
        db = FakeDB([{
            "id": "existing-analysis",
            "user_id": "user-1",
            "periodo_tipo": "semanal",
            "metrics": {"period_start": "2026-05-25"},
            "insight": "antigo",
        }])

        response = save_or_update_analysis(db, "user-1", period, {"period_start": "2026-05-25"}, "novo")

        self.assertTrue(db.updated)
        self.assertFalse(db.inserted)
        self.assertEqual(response.data[0]["insight"], "novo")

    def test_save_or_update_insere_periodo_novo(self):
        period = resolve_report_period("mensal", start_date="2026-05-01", end_date="2026-05-31")
        db = FakeDB()

        response = save_or_update_analysis(db, "user-1", period, {"period_start": "2026-05-01"}, "novo")

        self.assertTrue(db.inserted)
        self.assertFalse(db.updated)
        self.assertEqual(response.data[0]["periodo_tipo"], "mensal")


if __name__ == "__main__":
    unittest.main()
