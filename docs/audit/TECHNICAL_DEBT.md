# INVENTÁRIO DE DÍVIDAS TÉCNICAS E VULNERABILIDADES (TECHNICAL DEBT)
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Documento:** `docs/audit/TECHNICAL_DEBT.md`  
**Data:** 07 de Novembro de 2026  
**Auditor Responsável:** Auditoria Técnica Independente / Antigravity  

---

## 1. CLASSIFICAÇÃO DE SEVERIDADE

* **P0 — CRÍTICO (Bloqueador de Produção):** Vulnerabilidade que pode provocar perdas financeiras catastróficas, envio de ordens duplicadas, violação de limites de risco ou corrupção irreversível de estado. Deve ser corrigida antes de qualquer execução com capital real ou demo autônoma.
* **P1 — ALTO (Risco Técnico ou Quantitativo Substancial):** Falha conceitual em modelos matemáticos, lacunas em validação cruzada, vazamento de dados ou instabilidade de subsistemas secundários que afetam a robustez estatística do sistema.
* **P2 — MÉDIO (Melhoria de Engenharia e Manutenibilidade):** Otimizações de performance, refatorações de código, padronizações de logging e suporte a ambientes adicionais (como Linux VPS).
* **P3 — BAIXO (Débito Cosmético ou Menor):** Ajustes de documentação, warnings de bibliotecas terceiras e melhorias ergonômicas.

---

## 2. INVENTÁRIO DE RISCOS PRIORIZADOS

### 2.1. DÍVIDAS P0 (CRÍTICAS)

#### [DEBT-P0-01] Janela de Idempotência em Memória Volátil
- **Arquivo / Linha:** `execution/order_executor.py` (`self._processed_idempotency_keys: dict[str, float]`)
- **Problema:** O registro de ordens processadas reside exclusivamente em um dicionário Python na memória RAM com janela de retenção de 60 segundos.
- **Consequência Financeira:** Em caso de reinicialização ou crash do processo durante o envio de ordens sob instabilidade de rede da corretora, ordens idênticas podem ser submetidas novamente após a reinicialização rápida, gerando duplicação de lote e violação do risco máximo.
- **Severidade:** **P0 — CRÍTICO**
- **Recomendação de Remediação:** Substituir o dicionário em memória por uma tabela de controle em banco de dados SQLite operando em modo WAL (`journal_mode=WAL`) com commit síncrono antes do despacho da ordem ao `TradingPlatformAdapter`, ou utilizar um log append-only com `fsync`.

#### [DEBT-P0-02] Instabilidade Crítica na Fase 8 com Hang em Loop de WebSocket
- **Arquivo / Linha:** `monitoring/server.py` (`telemetry_ws` loop) e `tests/unit/test_monitoring_api.py`
- **Problema:** O endpoint `/ws/telemetry` implementa um loop `while True:` assíncrono que não gerencia desconexão limpa de clientes nos testes automatizados, provocando travamento por tempo indeterminado (*hang*) nas rotinas de teste com `Starlette TestClient`.
- **Consequência Técnica:** O processo de monitoramento fica congelado, consumindo CPU em loop fechado e impedindo a execução contínua de pipelines de CI/CD.
- **Severidade:** **P0 — BLOQUEADOR DE CI/CD**
- **Recomendação de Remediação:** Implementar timeout explícito de heartbeat, tratamento de exceção `WebSocketDisconnect` e cancelamento cooperativo via `asyncio.Event`.

---

### 2.2. DÍVIDAS P1 (ALTAS)

#### [DEBT-P1-01] Suposição IID no Motor de Estresse de Monte Carlo
- **Arquivo / Linha:** `intelligence/learning/monte_carlo.py` (`MonteCarloStressTester.run_simulation`)
- **Problema:** O gerador de bootstrap reamostra retornos históricos com reposição de forma puramente independente e identicamente distribuída (IID).
- **Consequência Quantitativa:** Mercados financeiros apresentam dependência temporal de cauda grossa e agrupamento de volatilidade (*volatility clustering*). O modelo IID subestima severamente a probabilidade de sequências longas de perdas consecutivas, subestimando o risco real de atingir o limite de emergência de 8% de drawdown.
- **Severidade:** **P1 — ALTO**
- **Recomendação de Remediação:** Implementar algoritmo de *Block Bootstrap* ou modelo de simulação baseado em matriz de transição de regimes (HMM Monte Carlo), preservando a autocorrelação dos retornos em regimes de alta volatilidade.

#### [DEBT-P1-02] Purga por Deslocamento de Índice Discreto no Walk-Forward
- **Arquivo / Linha:** `intelligence/learning/validation.py` (`PurgedWalkForwardValidator.split`)
- **Problema:** A janela de purga e embargo calcula o corte subtraindo um número fixo de barras inteiras (`test_start - forward_horizon`).
- **Consequência Quantitativa:** Caso a série temporal contenha fins de semana, feriados ou lacunas de liquidez, o corte por índice ordinal não corresponde ao intervalo temporal contínuo real da formação do retorno futuro, permitindo vazamento sutil de informação (*lookahead bias residual*).
- **Severidade:** **P1 — ALTO**
- **Recomendação de Remediação:** Realizar o corte purgado com base em índices de data/hora (`pd.Timestamp` delta) em vez de contagem posicional de linhas.

#### [DEBT-P1-03] Simulação Simplificada de PnL nos Folds do Validador Walk-Forward
- **Arquivo / Linha:** `intelligence/learning/validation.py` (`_evaluate_fold`)
- **Problema:** A avaliação de fold utiliza retornos financeiros discretizados fixos (ex: +$20 para acerto, -$10 para erro) em vez de simular os custos reais de spread variável, comissão e slippage dinâmico.
- **Consequência Quantitativa:** As métricas de Sharpe Ratio e Profit Factor registradas no `ModelRegistry` podem estar sobrestimadas em até 25% em relação ao comportamento real em ambiente com spread dinâmico.
- **Severidade:** **P1 — ALTO**
- **Recomendação de Remediação:** Integrar o `BacktestEngine` determinístico diretamente na função de avaliação de folds de validação cruzada.

---

### 2.3. DÍVIDAS P2 (MÉDIAS)

#### [DEBT-P2-01] Dependência Exclusiva de Binário Windows para API MetaTrader 5
- **Arquivo / Linha:** `execution/adapters/mt5_adapter.py`
- **Problema:** A biblioteca oficial `MetaTrader5` distribuída pela MetaQuotes é compilada exclusivamente para arquitetura Windows (chamadas diretas a DLLs Win32/COM).
- **Consequência Técnica:** Impede a execução direta do nó de orquestração em contêineres Docker Linux puros sem camada de emulação Wine ou arquitetura de microsserviço desacoplado em dois nós.
- **Severidade:** **P2 — MÉDIO (Impede Fase 9)**
- **Recomendação de Remediação:** Formalizar o padrão de arquitetura distribuída: o nó Linux executa o cérebro quantitativo (Agentes, ML, HMM, Risk) e despacha intenções aprovadas via gRPC/Redis para um nó Windows leve dedicado exclusivamente ao terminal MT5.

#### [DEBT-P2-02] Retenção de Cooldown do Portfolio Manager em Memória
- **Arquivo / Linha:** `risk/portfolio.py` (`self._last_symbol_execution: dict[str, datetime]`)
- **Problema:** A janela de cooldown de 60 segundos entre operações no mesmo símbolo é armazenada em memória volátil.
- **Consequência Técnica:** Reinicializações do sistema resetam o cooldown antes do término da janela de 60 segundos.
- **Severidade:** **P2 — MÉDIO**
- **Recomendação de Remediação:** Unificar o estado de cooldown na tabela de persistência do `ExecutionStateManager`.

---

### 2.4. DÍVIDAS P3 (BAIXAS)

#### [DEBT-P3-01] Alertas de Depreciação no Scipy e LightGBM
- **Arquivo / Linha:** `intelligence/learning/classifier.py` e `intelligence/regime/hmm_detector.py`
- **Problema:** Utilização de parâmetros com alterações previstas em versões futuras do Scipy e warnings de conversão de tipos NumPy em matrizes não-C-contiguous.
- **Consequência Técnica:** Poluição de logs de testes e risco de quebra em atualizações não pinadas de pacotes.
- **Severidade:** **P3 — BAIXO**
- **Recomendação de Remediação:** Fixar dependências rigorosas no `pyproject.toml` ou `requirements.txt` e suprimir warnings específicos via filtro do pytest.

---

## 3. RESUMO DO PLANO DE REMEDIAÇÃO TÉCNICA

| Identificador | Resumo da Ação Corretiva | Esforço Estimado | Fase Alvo |
| :--- | :--- | :---: | :---: |
| **DEBT-P0-01** | Implementar persistência atômica da chave de idempotência em SQLite WAL | 4 horas | Fase 7.1 |
| **DEBT-P0-02** | Refatorar loop de telemetria WebSocket com tratamento de desconexão limpa | 3 horas | Fase 8 |
| **DEBT-P1-01** | Atualizar Monte Carlo para Block Bootstrap / HMM Regime Switching | 6 horas | Fase 6.1 |
| **DEBT-P1-02** | Ajustar purga temporal com timestamp real no Walk-Forward | 3 horas | Fase 6.1 |
| **DEBT-P1-03** | Conectar Backtest Engine na avaliação econômica de folds do Walk-Forward | 5 horas | Fase 6.1 |
| **DEBT-P2-01** | Definir protocolo de comunicação de nó duplo (Linux Brain $\leftrightarrow$ Windows MT5) | 8 horas | Fase 9 |
| **DEBT-P2-02** | Persistir estado de cooldown do Portfolio Manager | 2 horas | Fase 7.1 |

