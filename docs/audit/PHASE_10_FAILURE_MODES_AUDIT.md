# RELATÓRIO DE AUDITORIA DOS 20 MODOS DE FALHA SISTÊMICOS (FASE 10)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/PHASE_10_FAILURE_MODES_AUDIT.md`  
**Data:** 15 de Novembro de 2026  
**Auditor Responsável:** Engenharia de Sistemas e Arquitetura Quantitativa / Antigravity  
**Classificação:** `VALIDADO` (20/20 Testes de Aceitação Aprovados com 100% de Sucesso)  
**Conformidade:** Constituição de Engenharia (`AGENTS.md`) — Regra 2, Regra 11 e Regra 12  

---

## 1. OBJETIVO E ESCOPO DA AUDITORIA

A Regra 2 da Constituição de Engenharia do QUANT HERMES estabelece como requisito mandatório:
> *"Proibido teste que apenas verifique se arquivo existe ou importa. Testes devem cobrir asserções dinâmicas de borda e os 20 modos de falha do sistema."*

Este relatório consolida a auditoria técnica exaustiva, a especificação formal e as evidências executáveis dos **20 Modos de Falha Sistêmicos** que protegem o capital da conta contra qualquer anomalia de rede, integridade de dados, corrupção de disco, violação de risco ou descompasso operacional.

O harness de testes de aceitação foi implementado em `tests/acceptance/test_20_failure_modes.py`, cobrindo 100% dos cenários com injeção dinâmica de falhas e asserções matemáticas sem stubs.

---

## 2. TAXONOMIA E MATRIZ DOS 20 MODOS DE FALHA

| # | Modo de Falha | Camada | Impacto Sem Mitigação | Comportamento Constitucional QUANT HERMES | Status |
| :-: | :--- | :--- | :--- | :--- | :---: |
| **01** | **Queda Abrupta de Conexão com MT5** (Socket Severed / TCP Reset) | Execução / Broker | Ordens orquestradas perdidas, duplicadas ou descontroladas | Transição atômica para `RECONCILIATION_REQUIRED`; bloqueio de reenvio cego; fail-closed imediato. | `VALIDADO` |
| **02** | **Cotações Anômalas e Ticks Stale** (Ask < Bid, Spread Nulo, Duplicidade) | Dados de Mercado | Disparo de ordens fictícias em books corrompidos | `MarketDataCollector` descarta ticks invertidos, nulos ou duplicatas em memória antes do barramento. | `VALIDADO` |
| **03** | **Alargamento Anômalo de Spread** (Extreme Spread Spike / Ilatência) | Risco Soberano | Execução com spread predatório em eventos macro | `RiskEngine` compara com média histórica; se spread $> 2\times$ normal, rejeita com `SPREAD_ANOMALY`. | `VALIDADO` |
| **04** | **Slippage Adverso de Execução** (Deriva entre intenção e preenchimento) | Execução / Auditoria | Degradação oculta de expectancy por preenchimento pior | Cálculo exato do slippage em pontos no `OrderResult`; registro em log de auditoria e métricas. | `VALIDADO` |
| **05** | **Corrupção de Armazenamento SQLite** (Falha de I/O em Idempotência) | Persistência / Disco | Perda da garantia transacional pré-envio de ordens | Postura Fail-Closed estrita: se SQLite falha, nenhuma ordem é enviada ao broker. Retcode 10028. | `VALIDADO` |
| **06** | **Crash Durante Envio de Ordem** (Interrupção súbita pós-registro) | Resiliência / Crash | Incerteza sobre preenchimento após reinicialização | `recover_unresolved_orders()` reconcilia posições do broker com SQLite e impede reenvio cego. | `VALIDADO` |
| **07** | **Supressão de Ordens Duplicadas** (Violação de Idempotência) | Orquestração | Multi-execução do mesmo sinal por repetição de tick | `SqliteIdempotencyStore` detecta colisão de chave primária SHA-256 e suprime duplicata. | `VALIDADO` |
| **08** | **Violação do Risco por Operação** (Hard Cap 0.50%) | Risco Soberano | Ruína do portfólio por sobrealavancagem em um trade | Pydantic V2 barra $\text{target\_risk\_pct} > 0.50\%$; `RiskEngine` veta afrouxamento acima do piso. | `VALIDADO` |
| **09** | **Excesso de Risco Agregado em Aberto** (Teto Máximo 1.00%) | Risco Soberano | Exposição simultânea descontrolada | `RiskEngine` computa risco monetário de posições abertas; veta ordem se soma $> 1.00\%$. | `VALIDADO` |
| **10** | **Limite Máximo de Posições Simultâneas** (Teto 3 Posições) | Risco Soberano | Sobrecarga de margem e fragmentação do portfólio | Veto soberano compulsório com `MAX_POSITIONS_LIMIT` ao atingir 3 posições abertas. | `VALIDADO` |
| **11** | **Desarme por Perda Diária Máxima** (Daily Loss Breaker 1.50%) | Circuit Breaker | Espiral destrutiva de perdas intradiárias | `DailyLossGuard` desarma o sistema no instante em que perda diária $\le -1.50\%$; congela até 00:00 UTC. | `VALIDADO` |
| **12** | **Desarme por Perda Semanal Máxima** (Weekly Loss Breaker 3.00%) | Circuit Breaker | Erosão continuada do capital ao longo da semana | `WeeklyLossGuard` desarma no instante de perda semanal $\le -3.00\%$; congela até segunda 00:00 UTC. | `VALIDADO` |
| **13** | **Kill Switch Compulsório por Drawdown** (Piso Absoluto 8.00%) | Proteção de Capital | Catástrofe de patrimônio líquido | `EmergencyDrawdownGuard` aciona `KillSwitch` permanente com persistência atômica em disco. | `VALIDADO` |
| **14** | **Bloqueio de Fim de Semana** (Weekend Risk Guard após 20h UTC) | Proteção de Capital | Exposição a gaps desastrosos de abertura de domingo | `WeekendRiskGuard` bloqueia novas operações na sexta após 20:00 UTC e no fim de semana. | `VALIDADO` |
| **15** | **Stop Loss Ausente ou Invertido** (Compra com SL > Entrada) | Integridade de Risco | Risco ilimitado ou liquidação instantânea por broker | Schema valida coerência geométrica; `RiskEngine` exige Stop Loss numérico estritamente positivo. | `VALIDADO` |
| **16** | **Arredondamento Seguro de Lotes Sub-Mínimos** (Anti-Sobrealavancagem)| Dimensionamento | Falha no broker ou arredondamento incorreto para cima | `PositionSizer` arredonda estritamente para baixo (*Floor*); se lote $< \text{volMin}$, zera (0.0). | `VALIDADO` |
| **17** | **Detecção de Posição Órfã no Broker** (Ordem externa ou fantasma) | Reconciliação | Posição descontrolada consumindo margem | `PositionReconciler` compara broker contra memória local; alerta `ORPHANED_POSITION_DETECTED`. | `VALIDADO` |
| **18** | **Detecção e Purga de Posição Fantasma Local** (Fechada no broker) | Reconciliação | Bloqueio falso de orçamento de risco por trade morto | Reconciliador detecta fechamento por SL/TP, purga da memória e libera orçamento de risco. | `VALIDADO` |
| **19** | **Falha de Rede na Ponte Dual-Node** (Linux-Windows Bridge Timeout) | Infraestrutura | Ordens perdidas ou desatualizadas no gateway | `LinuxMT5BridgeAdapter` lança `PlatformConnectionError` em timeout/503; fail-closed ativo. | `VALIDADO` |
| **20** | **Token de Risco Inválido, Adulterado ou Ausente** | Segurança Soberana | Despacho fraudulento ou direto de ordem para o broker | `OrderExecutor` exige `RiskAuthorization` aprovada com token; lança `PermissionError` imediato. | `VALIDADO` |

---

## 3. AUDITORIA DETALHADA POR NÚCLEO DE RESILIÊNCIA

### 3.1. Núcleo de Rede e Comunicação (Modos 01 e 19)
- **Modo 01 (Socket Severed):** Testado com `FaultyMT5Adapter.raise_disconnect_on_send = True`. O sistema captura `ConnectionResetError`, atualiza transacionalmente a máquina de estados para `RECONCILIATION_REQUIRED` e retorna `OrderResult(success=False, retcode=10024)`. Nenhuma ordem residual fica sem rastreamento.
- **Modo 19 (Ponte Dual-Node):** Testado injetando `httpx.ConnectTimeout` e `httpx.ReadTimeout` no `LinuxMT5BridgeAdapter`. Ambas as rotinas disparam `PlatformConnectionError` garantindo que o nó Linux aborte qualquer envio sem tentar despachos cegos.

### 3.2. Núcleo de Dados e Feeds de Mercado (Modos 02, 03 e 14)
- **Modo 02 (Sanitização de Cotações):** `MarketDataCollector.ingest_tick` rejeitou com sucesso ticks com `Ask < Bid`, ticks com cotação zero e descartou duplicatas exatas em sequência temporal.
- **Modo 03 (Filtro de Spread):** Com spread nominal de $1.5\text{ pips}$ e tick anômalo com $6.0\text{ pips}$ ($4\times$), `RiskEngine.evaluate_proposal` vetou a ordem com `approved=False` e `SPREAD_ANOMALY`.
- **Modo 14 (Risco de Fim de Semana):** Simulação de tick na sexta-feira às 21:15 UTC resultou em veto compulsório com `WEEKEND_RISK_GUARD`.

### 3.3. Núcleo de Idempotência e Persistência Pós-Crash (Modos 05, 06 e 07)
- **Modo 05 (Falha de SQLite Fail-Closed):** Com `StoreCorruptedError` injetado no método `register_intent_pre_submission`, o `OrderExecutor` abortou imediatamente antes de qualquer interação com o adaptador de mercado, retornando `retcode=10028` e `PERSISTENCE_FAILURE_FAIL_CLOSED`.
- **Modo 06 (Crash Mid-Flight Recovery):** Ordem deixada no estado transitório `SUBMITTING` foi recuperada na reinicialização pelo `recover_unresolved_orders()`, marcada como `RECONCILIATION_REQUIRED` e seu reenvio foi bloqueado.
- **Modo 07 (Supressão de Duplicatas):** Duas chamadas idênticas de `execute_order` resultaram na aprovação e preenchimento da primeira e na rejeição da segunda com `DUPLICATE_ORDER_SUPPRESSED`.

### 3.4. Núcleo Constitucional de Risco Soberano (Modos 08, 09, 10, 15 e 16)
- **Modos 08 e 09 (Pisos Invioláveis de Risco):** O esquema Pydantic rejeita propostas $> 0.50\%$, o construtor do `RiskEngine` rejeita configurações $> 0.50\%$ de risco por trade e $> 1.00\%$ de risco agregado. Tentativa de abrir nova ordem quando posições existentes consumiam $0.85\%$ foi vetada com `AGGREGATE_RISK_LIMIT`.
- **Modo 10 (Teto de Posições):** Veto soberano ao tentar abrir a 4ª posição simultânea.
- **Modo 15 (Stop Loss Obrigatório e Coerente):** A validação do modelo Pydantic bloqueia no ato da instanciação compras com $\text{SL} \ge \text{Preço de Entrada}$ ou vendas com $\text{SL} \le \text{Preço de Entrada}$.
- **Modo 16 (Dimensionamento Seguro):** Com risco de apenas $\$2.00$ para Stop Loss de $100\text{ pips}$, o volume bruto calculado foi $0.002\text{ lotes}$. O `PositionSizer.normalize_lot` arredondou estritamente para $0.0$, eliminando risco de sobrealavancagem oculta.

### 3.5. Núcleo de Circuit Breakers e Proteção de Capital (Modos 11, 12 e 13)
- **Modo 11:** Perda diária de $-1.60\%$ desarmou imediatamente o `DailyLossGuard` com `CIRCUIT_BREAKER_DAILY_LOSS`.
- **Modo 12:** Perda semanal de $-3.20\%$ desarmou o `WeeklyLossGuard` com `CIRCUIT_BREAKER_WEEKLY_LOSS`.
- **Modo 13:** Drawdown acumulado de $8.50\%$ disparou o `EmergencyDrawdownGuard`, que acionou o `KillSwitch` compulsório e gravou o estado de bloqueio em arquivo JSON no disco.

### 3.6. Núcleo de Reconciliação e Segurança Operacional (Modos 04, 17, 18 e 20)
- **Modo 04 (Slippage Audited):** Injeção de $0.00040$ ($4\text{ pips}$) de slippage adverso foi calculada e validada no `OrderResult`.
- **Modo 17 (Orphan Broker Detection):** Posição criada externamente no broker sem registro interno foi detectada pelo `PositionReconciler` e classificada em `orphaned_tickets`.
- **Modo 18 (Ghost Local Purge):** Ticket presente na memória mas ausente no broker foi sinalizado em `ghost_tickets` para purga imediata.
- **Modo 20 (Token Tampering Veto):** Ordens com token vazio ou `approved=False` lançaram instantaneamente `PermissionError` no `OrderExecutor`, sem despachar nenhum byte à rede.

---

## 4. CONCLUSÃO DA AUDITORIA

O QUANT HERMES demonstra robustez comprovada por testes automatizados em todos os 20 modos de falha sistêmicos. Nenhuma fragilidade arquitetural, vazamento de risco ou comportamento permissivo foi detectado.

A conformidade com a Constituição de Engenharia (`AGENTS.md`) é integral.
O sistema está matematicamente e operacionalmente apto para avançar à **Homologação em Paper Trading Contínuo de 30 Dias**.

