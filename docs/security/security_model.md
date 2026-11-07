# Modelo de Segurança e Gestão de Riscos Operacionais
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/security/security_model.md`  

---

## 1. Princípios de Segurança e Confiança Zero (*Zero Trust*)

O QUANT HERMES foi concebido sob a premissa de que falhas de código, alucinações de modelos de IA, interrupções de rede e anomalias de dados de mercado **ocorrerão**. Portanto, a integridade do capital depende de defesas em camadas invioláveis.

---

## 2. Gestão de Segredos e Credenciais

1. **Separação Rígida:** Credenciais de corretora (login MT5, senha, servidor), chaves de API de provedores de LLM e senhas de bancos de dados residem exclusivamente no arquivo `.env` local, o qual é terminantemente ignorado pelo Git (`.gitignore`).
2. **Modelo de Configuração Exemplo:** Apenas o arquivo `.env.example` com valores vazios/fictícios é versionado no repositório.
3. **Higienização de Logs:**
   * O sistema de log estruturado (`structlog`) implementa um filtro de sanitização ativo.
   * Campos contendo palavras-chave como `password`, `secret`, `token`, `key`, `authorization` são mascarados automaticamente antes de serem gravados em disco ou exibidos no console.
4. **Proibição de Contas Reais durante o Desenvolvimento:** É estritamente vedada a conexão de credenciais de contas com saldo financeiro real durante as fases de desenvolvimento e homologação (Fases 0 a 9). Apenas contas de demonstração (*Demo Accounts*) ou Paper Trading são autorizadas.

---

## 3. A Inviolabilidade do Motor de Risco (*Inviolable Floor*)

Diferente de sistemas convencionais onde os limites de risco são meras chaves em arquivos de configuração que qualquer script pode sobrescrever:

1. **Pisos Codificados em Código (`_HARDCODED_MIN`):**
   ```python
   # Exemplo do contrato inviolável de segurança
   _HARDCODED_FLOOR = {
       "max_risk_per_trade_pct": 0.50,    # Risco por operação nunca pode exceder 0.50%
       "max_daily_loss_pct": 2.00,        # Perda diária máxima absoluta: 2.0%
       "max_weekly_loss_pct": 4.00,       # Perda semanal máxima absoluta: 4.0%
       "max_drawdown_limit_pct": 8.00,    # Drawdown de emergência: 8.0%
       "max_open_positions": 5,           # Máximo de posições simultâneas
       "mandatory_stop_loss": True        # Toda ordem DEVE ter Stop Loss numérico
   }
   ```
2. **Validação Unidirecional de Configuração:**
   O arquivo de configuração `config/risk.yaml` pode apenas **tornar as regras mais restritivas** (por exemplo, reduzir o risco por operação para 0.25%), mas se tentar definir um risco de 2.0%, o motor de risco rejeita a configuração na inicialização e impõe o piso de segurança.
3. **Imunidade contra Agentes de IA:**
   Nenhum agente, modelo estatístico ou LLM possui referência ou acesso de escrita aos módulos de risco. Suas saídas são meramente consultivas.

---

## 4. Arquitetura Fail-Safe (Falha Segura)

A auditoria forense do repositório *Multi-Agent Quant* revelou que a ausência de dados de conta permitia o tráfego de ordens. No QUANT HERMES vigora a regra inegociável:

> **Ausência de dados, inconsistência de posições ou perda de comunicação = BLOQUEIO IMEDIATO.**

* **Critérios de Bloqueio Automático:**
  1. Conexão MT5 offline por mais de 5 segundos.
  2. Consulta de `account_info` retornando `None` ou valores zerados.
  3. Spread atual excedendo 2.5× a média histórica do ativo.
  4. Divergência entre as posições registradas em memória e as posições reais da corretora.
  5. Latência de envio de ordem excedendo 1500ms.

---

## 5. Kill Switch e Circuit Breakers

1. **Kill Switch Global:**
   * Mecanismo autônomo e manual para emergências.
   * Ao ser acionado:
     1. Cancela todas as ordens pendentes no book.
     2. Envia ordens de fechamento a mercado para todas as posições ativas.
     3. Bloqueia o recebimento de qualquer novo sinal até reinicialização manual com auditoria.
2. **Circuit Breakers Temporais:**
   * **Diário:** Se a perda acumulada no dia útil atingir 1,5%, novas entradas são desabilitadas até a abertura do próximo dia útil (00:00 UTC).
   * **Semanal:** Se a perda acumulada na semana atingir 3,0%, novas entradas são desabilitadas até o próximo domingo.
   * **Sexta-feira (Weekend Risk):** Às 20:00 UTC da sexta-feira, todas as posições de Scalping e Day Trade são liquidadas compulsoriamente para evitar riscos de gap de fim de semana.

---

## 6. Isolamento de Rede e Infraestrutura

1. **Binding Local:** Os serviços internos (API FastAPI, Redis, PostgreSQL e Prometheus) realizam bind exclusivamente em interfaces de loopback (`127.0.0.1` ou rede privada Docker bridge). Nenhuma porta de banco de dados ou mensageria é exposta para a internet pública (`0.0.0.0`).
2. **Acesso Remoto:** Qualquer conexão futura com VPS Linux ou monitoramento externo deve ser realizada exclusivamente através de túneis criptografados SSH ou VPN (WireGuard/Tailscale).

