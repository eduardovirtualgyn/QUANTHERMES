# QUANT HERMES — ARQUITETURA DE IMPLANTAÇÃO DUAL-NODE EM VPS
## ISOLAMENTO ANALÍTICO LINUX E EXECUÇÃO FÍSICA WINDOWS METATRADER 5

**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/architecture/dual_node_deployment.md`  
**Fase:** FASE 9 — Preparação de Implantação em VPS Linux e Containerização  
**Classificação:** ARQUITETURA DE PRODUÇÃO E INFRAESTRUTURA  

---

### 1. Desafio Estrutural do MetaTrader 5

A biblioteca oficial Python do `MetaTrader5` distribuída pela MetaQuotes é um wrapper C++ compilado para a arquitetura Win32/Win64. Ela requer a presença das APIs do Windows (Single-Threaded Apartment do COM, bibliotecas `user32.dll`, `kernel32.dll` e o processo `terminal64.exe` ativo na mesma máquina).

Tentar executar o `terminal64.exe` em Linux puro via Wine em ambientes de alta frequência frequentemente gera:
1. Instabilidade em chamadas multithread COM.
2. Latência imprevisível durante repinturas de gráfico e renderização gráfica GDI emulada.
3. Dificuldade de auditoria e profiling de bibliotecas científicas avançadas (LightGBM, XGBoost, Polars).

---

### 2. A Solução Institucional: Arquitetura de Nó Duplo (Dual-Node)

Para resolver esse dilema sem comprometer nem a execução física nem a integridade matemática, o QUANT HERMES adota uma **Arquitetura de Nó Duplo** desacoplada:

```
+-------------------------------------------------------------+
|                     NÓ ANALÍTICO (LINUX VPS)                |
|                    Contêiner Docker: hermes-brain           |
|                                                             |
|  - Event Bus Prioritário                                    |
|  - Sistema Multiagente (AG01 a AG08)                        |
|  - Consenso e Platt Scaler                                  |
|  - Risk Engine Soberano & Circuit Breakers                  |
|  - Modelos Quantitativos (HMM, XGBoost, LightGBM)           |
|  - Validador Purgado & Monte Carlo (Block Bootstrap)        |
|  - SqliteIdempotencyStore (Persistência WAL)                |
|  - Dashboard Web & API de Telemetria (Porta 8000)           |
|  - LinuxMT5BridgeAdapter (TradingPlatformAdapter)           |
+------------------------------+------------------------------+
                               |
                               | Túnel Seguro (WireGuard VPN / mTLS)
                               | Autenticação: X-Hermes-Bridge-Token
                               v
+-------------------------------------------------------------+
|                     NÓ EXECUTOR (WINDOWS SERVER)            |
|                     Processo Nativo: mt5_gateway            |
|                                                             |
|  - MT5 Remote Gateway (FastAPI na porta 8001)               |
|  - WindowsMT5Adapter (STA Thread Dedicada, max_workers=1)   |
|  - Terminal MetaTrader 5 Físico (terminal64.exe)            |
|  - Conexão TCP direta com o Servidor da Corretora           |
+-------------------------------------------------------------+
```

---

### 3. Componentes da Arquitetura

#### 3.1 Nó Analítico (Linux VPS — `hermes-brain`)
- **Sistema Operacional:** Ubuntu 22.04 / 24.04 LTS rodando Docker Engine.
- **Isolamento de Processos:** Contêiner Docker baseado em `python:3.11-slim` executado sob usuário não-privilegiado `hermes`.
- **Adaptador de Execução:** O `LinuxMT5BridgeAdapter` implementa a interface abstrata `TradingPlatformAdapter`, convertendo chamadas de negócio em requisições REST/WebSocket assíncronas de alta performance para o nó Windows.
- **Segurança de Acesso:** A API e Dashboard escutam em `127.0.0.1:8000` e são protegidos por proxy reverso (Nginx ou Caddy) com terminação TLS e autenticação HTTP.

#### 3.2 Nó Executor (Windows Server — `mt5_gateway`)
- **Sistema Operacional:** Windows Server 2022 / Windows 11 Pro.
- **Processo Gateway:** Executa o microserviço `execution/gateway/mt5_gateway.py`.
- **Validação de Token:** Toda requisição deve conter o cabeçalho secreto `X-Hermes-Bridge-Token`. Tentativas de acesso sem token ou com credenciais incorretas são abortadas com HTTP 403 Forbidden.
- **Serialização COM:** As chamadas à biblioteca `MetaTrader5` são despachadas estritamente por uma fila serializada em thread dedicada (`max_workers=1`), respeitando integralmente a **ADR-003** e eliminando falhas de concorrência.

---

### 4. Gestão de Latência e Política Fail-Safe de Conexão

1. **Latência de Rede:**
   - Em provedores de nuvem (ex: Hetzner, AWS ou Vultr), instâncias Linux e Windows alocadas no mesmo datacenter comunicam-se pela rede privada com latência inferior a **1.0 milissegundo**.
2. **Queda de Conexão (Fail-Safe):**
   - Caso o link de rede entre o nó Linux e o nó Windows seja interrompido:
     - O `LinuxMT5BridgeAdapter` detecta o timeout e levanta `PlatformConnectionError`.
     - O `OrderExecutor` e o `RiskEngine` bloqueiam imediatamente o despacho de novas intenções operacionais (Regra 12 de `AGENTS.md`).
     - O `mt5_gateway` no nó Windows possui watchdog local: se ficar sem contato com o cérebro por mais de 60 segundos com posições abertas, aciona rotina de proteção e fecha ordens pendentes.

---

### 5. Guia de Implantação Passo a Passo

1. **No Nó Windows Server:**
   ```powershell
   # 1. Iniciar o MetaTrader 5 e fazer login na conta da corretora
   # 2. Configurar o token no ambiente:
   $env:HERMES_BRIDGE_TOKEN = "SEU_TOKEN_SECRETO_INSTITUCIONAL"
   $env:HERMES_GATEWAY_PORT = "8001"
   # 3. Iniciar o microserviço Gateway:
   python execution/gateway/mt5_gateway.py
   ```

2. **No Nó Linux VPS:**
   ```bash
   # 1. Provisionar a VPS com script automatizado:
   sudo bash deploy/setup_vps.sh

   # 2. Configurar variáveis de ambiente:
   cp deploy/.env.vps.example .env
   # Ajustar MT5_GATEWAY_URL e tokens em .env

   # 3. Construir e iniciar os contêineres:
   docker compose up -d --build

   # 4. Verificar logs de inicialização e telemetria:
   docker compose logs -f hermes-brain
   ```

