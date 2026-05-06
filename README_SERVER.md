# 🧠 Servidor ContaComigo (Alfredo) - HP Pavilion X360

Este documento é a referência técnica oficial para a configuração, operação e manutenção do servidor local que hospeda o ecossistema ContaComigo. O servidor foi projetado para ser resiliente, eficiente em hardware limitado e totalmente gerenciável por IA.

---

## 💻 1. Especificações de Hardware (pvserver)
O hardware foi otimizado para rodar serviços 24/7 com baixo consumo de energia.
*   **Modelo:** HP Pavilion X360 11-N226BR
*   **Processador:** Intel Celeron N2830 (Dual Core @ 2.16GHz)
*   **Memória RAM:** 4GB DDR3L
    *   *Otimização:* 4GB de Swap + ZRAM (compressão de memória em tempo real) para suportar bibliotecas Python pesadas.
*   **Armazenamento:** SSD 120GB (Leitura ~450 MB/s)
*   **Sistema Operacional:** Ubuntu Server 24.04 LTS (Headless - Sem interface gráfica)
*   **Nobreak Natural:** A bateria interna do notebook garante autonomia de 3-5 horas em caso de falha de energia na rede elétrica.

---

## 🏗️ 2. Arquitetura de Deploy Híbrida
O sistema utiliza uma abordagem de separação estrita para garantir performance:

1.  **Ambientes Virtuais (VENV):** 
    *   `~/contacomigo/venv`: Isolado para as regras de negócio e bot.
    *   `~/alfredo-ops/venv`: Isolado exclusivamente para o servidor MCP.
2.  **Bibliotecas de Sistema:** Dependências pesadas como `Pandas`, `Numpy`, `OpenCV` e `Psycopg2` são instaladas via `apt` no sistema e compartilhadas com o venv via `--system-site-packages` para reduzir overhead.
3.  **Persistência e Orquestração:** Gerenciado via `systemd` para garantir auto-restart e logs centralizados no `journalctl`.
4.  **Rede e Túnel:** Cloudflare Tunnel (`cloudflared`) expondo serviços locais de forma segura sem abertura de portas no roteador.

---

## 🛠️ 3. Painel de Controle (Comandos de Gestão)

### 3.1 Monitoramento de Logs em Tempo Real
```bash
sudo journalctl -u contacomigo -f      # Logs do Bot e API Flask
sudo journalctl -u alfredo-mcp -f      # Logs da Interface de IA (MCP)
sudo journalctl -u AdGuardHome -f      # Logs do Bloqueador de Anúncios
sudo journalctl -u cloudflared -f      # Logs do Túnel de Internet
```

### 3.2 Gestão de Status dos Serviços
```bash
sudo systemctl status contacomigo   # O Cérebro (Bot)
sudo systemctl status alfredo-mcp   # A Interface de IA
sudo systemctl status AdGuardHome   # O Filtro de Rede
sudo systemctl status cloudflared  # O Túnel HTTPS
```

### 3.3 Comandos de Manutenção Rápida
```bash
sudo systemctl restart contacomigo   # Reiniciar Bot
sudo systemctl restart alfredo-mcp   # Reiniciar Gestor IA
sudo systemctl restart AdGuardHome   # Reiniciar Adblock
btop                                 # Monitorar Saúde (CPU/RAM/Temp)
```

---

## 🛠️ 4. Alfredo Ops (Interface MCP)
O servidor possui um endpoint **Model Context Protocol (MCP)** que permite gerenciar o hardware via linguagem natural.

*   **Endpoint SSE:** `https://mcp.henriquedejesus.dev/sse`
*   **Segurança:** Requer Header `Authorization: Bearer <TOKEN>`
*   **Capacidades:**
    *   Monitoramento térmico e de disco.
    *   Restart de serviços via IA.
    *   Análise de logs conversacional.
    *   Deploy automático (`git pull` + `restart`).

---

## 🌐 5. Configuração de Rede & Portas
O Cloudflare Tunnel mapeia o tráfego externo para as portas internas do servidor:

| Serviço | Domínio Externo | Porta Interna | Protocolo |
| :--- | :--- | :--- | :--- |
| **Alfredo Bot** | `alfredo.henriquedejesus.dev` | `10000` | HTTP/WS |
| **Alfredo Ops** | `mcp.henriquedejesus.dev` | `10001` | SSE/HTTP |
| **AdGuard Home** | Local (192.168.1.23) | `53 / 80` | UDP / TCP |

---

## ⚠️ 6. Manutenção e Cuidados 24h

1.  **Tampa e Suspensão:** O sistema está configurado via `logind.conf` para ignorar o fechamento da tampa. O notebook deve permanecer fechado para proteção.
2.  **Energia:** Deve permanecer conectado à tomada. A bateria interna é a salvaguarda de dados.
3.  **Ciclo de Deploy:**
    ```bash
    cd ~/contacomigo
    git pull
    sudo systemctl restart contacomigo
    ```
4.  **Gestão de Espaço:** O SSD de 120GB deve ser monitorado. Limpe logs antigos com:
    ```bash
    sudo journalctl --vacuum-time=7d
    ```

---

## 📁 7. Estrutura de Pastas Críticas
*   `~/contacomigo`: Repositório principal do Bot e MiniApp.
*   `~/alfredo-ops`: Instalação isolada do Servidor MCP.
*   `/opt/AdGuardHome`: Instalação do bloqueador de anúncios.
*   `/etc/systemd/system/`: Arquivos `.service` de todos os projetos.
*   `/etc/sudoers.d/mcp_nopasswd`: Regras de permissão para a IA gerenciar o Linux.

---
**Status:** 🟢 Operacional e Híbrido
**Responsável:** pvserver
**Data de Referência:** Abril de 2026
