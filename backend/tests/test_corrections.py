import unittest

from app.corrections import enrich_interpreted_payload


class CorrectionsHeuristicsTests(unittest.TestCase):
    def test_forca_correcao_de_porteiro_quando_ha_nome_correto(self):
        interpreted = {
            "intencao": "cadastrar_porteiro",
            "porteiro_info": {
                "rua": "rua senador vergueiro",
                "numero": "85",
                "nome": "Joyce Cerqueira",
                "nome_antigo": "",
            },
            "eventos": [],
        }

        payload = enrich_interpreted_payload(
            "Corrigir nome do porteiro da rua senador vergueiro, 85. O nome correto é Joyce Cerqueira",
            interpreted,
        )

        self.assertEqual(payload["intencao"], "corrigir_porteiro")

    def test_monta_correcao_de_registro_para_horario_de_inicio(self):
        interpreted = {
            "intencao": "corrigir_porteiro",
            "eventos": [],
        }

        payload = enrich_interpreted_payload(
            "Corrigir horário de início da operação dos correios de hoje, o horario correto é 15:20",
            interpreted,
        )

        self.assertEqual(payload["intencao"], "corrigir_registro")
        self.assertEqual(payload["correcao_info"]["app"], "Correios")
        self.assertEqual(payload["correcao_info"]["campos"]["hora_inicio"], "15:20")
        self.assertTrue(payload["correcao_info"]["atualizar_operacao"])
        self.assertEqual(payload["eventos"][0]["hora_inicio_rota"], "15:20")


if __name__ == "__main__":
    unittest.main()
