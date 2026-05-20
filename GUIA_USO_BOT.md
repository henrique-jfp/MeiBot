    # 🤖 Guia de Uso Completo - MeiBot

    O **MeiBot** é o seu assistente de inteligência artificial projetado para facilitar a vida de entregadores e motoristas logísticos. Ele escuta seus áudios, lê seus textos e até imagens para registrar seus ganhos, gastos, horários e mapear porteiros, além de capturar rotas automaticamente em grupos.

    Fixe esta mensagem ou guarde-a para consultar sempre que tiver dúvidas sobre como usar o bot.

    ---

    ## 1. 📦 REGISTRO DE ROTAS E FINANCEIRO (DIA A DIA)

    Você pode mandar **áudio ou texto** de forma natural, como se estivesse conversando com um amigo. O bot entende a linguagem do dia a dia.

    **Início e Fim do Expediente:**
    *   `"Começando os trabalhos de hoje"` -> Marca o início da operação.

    *   `"Finalizei por hoje, indo pra casa"` -> Encerra a operação do dia e gera um resumo.


    **Tempos de Espera (Galpão):**
    *   `"Cheguei no galpão da Shopee"` -> Marca a hora de chegada (início da espera).

    *   `"Saí do galpão, começando a rota"` -> Marca a hora que saiu e começou a entregar (fim da espera).


    **Registro de Ganhos e Rotas:**
    *   Fale apenas o necessário, ele já tem suas métricas salvas(Shopee e Correios).
    *   *Exemplos:*
        *   `"Fiz Correios hoje, 120 pacotes."`

        *   `"Shopee hoje deu 305 reais mais 20 de extra, rodei 60km."`

        *   `"Mercado Livre, 150 reais, 40 pacotes, terminei as 16h."`


    **Registro de Despesas:**
    *   *Exemplos:*
        *   `"Gastei 50 reais de gasolina."`
        *   `"20 reais com almoço e água."`
        *   `"Paguei 130 pro ajudante hoje."`

    **Fale o Resumo:**
    *   *Exemplos:*
        *   `"Finalizei Shopee, Cheguei no galpão 5:10, comecei a rota 6:45 e terminei 9:47"`

        *   `"Finalizei Shopee, Cheguei no galpão 5 e 10 da manhã, comecei a rota 6 e 45 da manhã e terminei 9 e meia da manhã"`

        *   `"Finalizei Correios, Cheguei no galpão 13:10, comecei a rota 14:05 e terminei 17:47"`

        *   `"Finalizei Correios, Cheguei no galpão Uma e vinte da tarde, comecei a rota 2 e 10 da tarde e terminei 5 e 47 da tarde"`


    **Leitura de Comprovantes (Imagem):**

    *   Envie um **print ou foto** da tela do aplicativo com o resumo da rota. O bot vai ler a imagem (OCR) e extrair os valores, pacotes e KM automaticamente.


    ---

    ## 2. 🏢 MAPEAMENTO DE PORTEIROS

    Nunca mais esqueça o nome de um porteiro ou as regras de um prédio! O bot usa a localização que você passa para gerenciar uma lista.

    *   **Cadastrar novo porteiro:**
        *   `"Rua Senador Vergueiro, 5. O nome do porteiro é João."`
    *   **Consultar um prédio:**
        *   `"Quem é o porteiro da Senador Vergueiro, 85?"`
    *   **Listar todos os porteiros mapeados:**
        *   `"Meus porteiros"` ou `"Lista de porteiros"`
        *   `"Mande o Link do Dashboard(Mapa de porteiros ou resumo)"`

    ---

    ## 3. ✏️ CORREÇÃO DE DADOS (ERROU? O BOT ARRUMA!)

    Se o bot entendeu algo errado, se o áudio falhou ou se você informou algo incorreto antes, basta pedir para corrigir. Seja explícito sobre **o que** quer corrigir.

    **Corrigir a Operação ou Lançamentos:**
    *   `"Corrigir o horário de início da operação de hoje para 08:30."`

    *   `"Corrigir o valor dos Correios de ontem para 255 reais."`

    *   `"Corrigir os pacotes da Shopee de hoje, foram 110 pacotes."`

    *   `"Corrigir a quilometragem da rota de hoje para 55 km."`

    *   `"Corrigir meu gasto com combustível para 60 reais."`



    **Corrigir um Porteiro:**
    *   *Se houver só um porteiro no prédio:* `"Corrigir o nome do porteiro da Rua Paissandu, 200. O nome correto é Jorge."`

    *   *Se houver mais de um porteiro no prédio, diga o nome antigo e o novo:* `"Corrigir o porteiro Carlos para José na Rua Senador Vergueiro, 85."`

    *   *Alterar turno ou adicionar notas:* `"Corrigir o turno do porteiro da Rua Barata Ribeiro, 502 para 'Noite' e a nota para 'Não recebe depois das 18h'."`


    ---

    ## 4. 📊 RESUMOS, ANÁLISES E DASHBOARD

    Você pode pedir os resultados da sua operação a qualquer momento e receber conselhos financeiros.

    *   **Resumo do Dia:** `"Resumo de hoje"` ou `"Como foi meu dia?"`

    *   **Resumo Semanal:** `"Resumo da semana"`

    *   **Resumo Mensal:** `"Resumo do mês"`

    *   **Perguntas Livres:** `"Quanto eu gastei de gasolina essa semana?"` ou `"Qual foi meu lucro líquido ontem?"`

    *   **Link do Dashboard Visual:** `"Me dá o link do painel"` ou `"Dashboard"` *(O bot enviará o link para você acessar a interface web rica).*



    > 💡 **Visão do Analista IA:** Nos resumos diários, semanais e mensais, o MeiBot atua como um consultor operacional. Ele dará feedbacks curtos e práticos analisando seu lucro real (R$/KM), alertando sobre gastos supérfluos e medindo seu tempo inativo (espera excessiva em galpões).


    ---

    ## 5. 🚀 SISTEMA DE CAPTURA DE ROTAS (GRUPOS DO WPP)

    O MeiBot monitora grupos específicos de distribuição de rotas em horários pré-programados para reservar a melhor rota para você de forma ultra-rápida.

    **Como funciona (Automático):**
    1. O bot liga sozinho em horários agendados (Ex: Domingo à Quinta, a partir das 23h até 04:30h da manhã seguinte).
    2. Assim que um administrador posta uma planilha (PDF/Foto) no grupo autorizado, o bot lê e procura as rotas do seu interesse (ex: Rocinha, priorizando o maior volume).
    3. Se encontrar, ele envia a mensagem de reserva automaticamente no grupo. Ex: `Henrique de Jesus Freitas Pereira 2554974 B-41`.
    4. **Ação do Usuário:** O bot aguarda você confirmar se a reserva deu certo.
    - Reaja com ✅, ✔️ ou 👍 à mensagem do bot para **Confirmar**. (O bot mandará uma mensagem no seu privado e parará a busca do dia).
    - Reaja com ❌ à mensagem do bot para **Recusar** (O bot continuará tentando reservar a próxima melhor rota encontrada).

    **Comandos Manuais (No seu chat privado com o bot):**
    *   `ativar rotas`: Liga o buscador de rotas imediatamente, fora do horário programado.

    *   `desativar rotas`: Desliga o buscador completamente.

    *   `reativar rotas`: Força o bot a esquecer as rotas que já leu hoje, útil se uma mesma planilha for reenviada e você precisa que ele a analise novamente.

    ---

    **Dica de Ouro:** Use o **microfone** do WhatsApp! 🎙️ O MeiBot usa um dos transcritores de áudio mais rápidos do mundo. Fale naturalmente enquanto dirige ou caminha, ele processa tudo em segundos!
