import unittest

from app.routes_claim.ai_routes import (
    _contains_no_show,
    _parse_routes_from_lines,
    parse_route_sheet,
    rank_route_candidates,
)


class RoutesClaimTests(unittest.TestCase):
    def test_ignora_ns_em_nome_ou_texto_anexo(self):
        self.assertTrue(_contains_no_show("planilha_NS.pdf"))
        self.assertTrue(_contains_no_show("B-41NS rota cancelada"))
        self.assertTrue(_contains_no_show("NO SHOW"))
        self.assertFalse(_contains_no_show("lista de rotas"))

        parsed = parse_route_sheet(b"conteudo nao lido", "application/pdf", file_name="rotas_noshow.pdf")
        self.assertTrue(parsed["no_show"])
        self.assertEqual(parsed["routes"], [])

    def test_extrai_litragem_quando_identificada_na_linha(self):
        parsed = _parse_routes_from_lines(
            ["B-41 124 Copacabana ROTA MISTA LITRAGEM: 660"],
            "test",
        )
        self.assertEqual(parsed["routes"][0]["litragem"], 660)

    def test_prioridade_de_bairro_vem_antes_da_litragem_e_pacotes(self):
        ranked = rank_route_candidates([
            {"gaiola": "B-10", "bairro": "Copacabana", "modal": "ROTA MISTA", "litragem": 100, "pacotes_total": 10},
            {"gaiola": "B-11", "bairro": "Urca", "modal": "PASSEIO", "litragem": 900, "pacotes_total": 400},
            {"gaiola": "B-12", "bairro": "Urca", "modal": "ROTA MISTA", "litragem": 300, "pacotes_total": 20},
        ])
        self.assertEqual([route["gaiola"] for route in ranked], ["B-12", "B-11", "B-10"])

    def test_desempata_por_pacotes_sem_litragem_e_exclui_modais_proibidos(self):
        ranked = rank_route_candidates([
            {"gaiola": "B-20", "bairro": "Ipanema", "modal": "ROTA MISTA", "pacotes_total": 90},
            {"gaiola": "B-21", "bairro": "Ipanema", "modal": "PASSEIO", "pacotes_total": 70},
            {"gaiola": "B-22", "bairro": "Urca", "modal": "MOTO", "pacotes_total": 1},
            {"gaiola": "B-23", "bairro": "Urca", "modal": "FIORINO", "pacotes_total": 1},
            {"gaiola": "B-24", "bairro": "Urca", "modal": "VOLUMOSO", "pacotes_total": 1},
        ])
        self.assertEqual([route["gaiola"] for route in ranked], ["B-21", "B-20"])

    def test_considera_bairro_da_dissecacao(self):
        ranked = rank_route_candidates([
            {
                "gaiola": "B-30",
                "bairro": "Copacabana",
                "dissecacao": {"Urca": 2},
                "modal": "ROTA MISTA",
                "pacotes_total": 100,
            },
            {"gaiola": "B-31", "bairro": "Tabajaras", "modal": "PASSEIO", "pacotes_total": 10},
        ])
        self.assertEqual(ranked[0]["gaiola"], "B-30")


if __name__ == "__main__":
    unittest.main()
