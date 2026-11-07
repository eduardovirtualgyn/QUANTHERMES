# AGENTS.md — Constituição de Engenharia do QUANT HERMES
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Versão:** 1.0  
**Ambiente:** Windows 11 (Inicial) / VPS Linux (Alvo)  
**Linguagem:** Python 3.11+ / MQL5  
**Plataforma de Execução:** MetaTrader 5  

---

## 1. Princípio Fundamental Inviolável

> **Os agentes analisam, formulam hipóteses e recomendam; as estratégias geram intenções; o Portfolio Manager consolida e aloca capital; mas SOMENTE o Risk Engine, mediante autorização estrita, pode enviar ordens ao Execution Engine.**
> 
> **Nenhum agente, modelo de Machine Learning ou LLM poderá jamais alterar seus próprios limites financeiros, afrouxar parâmetros de risco ou despachar ordens diretamente para o mercado.**

---

## 2. As Quinze Regras Inegociáveis de Engenharia

1. **Nunca desenvolver todo o sistema em um único arquivo:** Modularidade estrita em camadas desacopladas.
2. **Nunca misturar inteligência artificial, gestão de risco e execução de ordens:** Cada módulo possui fronteiras bem delimitadas.
3. **Não implementar funcionalidades fictícias:** Proibido criar stubs ou mock-ups apenas para simular arquitetura completa.
4. **Não declarar um módulo concluído sem código, testes e evidências:** "Funciona" exige prova automatizada executável.
5. **Não inventar resultados de backtest, rentabilidade ou precisão:** A honestidade estatística é inegociável.
6. **Não considerar um projeto GitHub confiável apenas pela documentação:** Todo código externo deve ser auditado no nível de implementação.
7. **Não copiar código indiscriminadamente:** Toda linha incorporada deve ter origem, licença e propósito comprovados.
8. **Verificação de Licenças:** Proibida a inclusão de bibliotecas ou códigos sob GPL, AGPL ou licenças restritivas incompatíveis sem análise formal.
9. **Zero credenciais no código:** Segredos residem exclusivamente em arquivos `.env` locais ignorados pelo Git.
10. **Não executar operações financeiras reais durante o desenvolvimento:** Apenas contas demo ou simuladores de paper trading são permitidos.
11. **Rastreabilidade total:** Toda operação deve ser identificável, auditável e vinculada ao agente, estratégia e regime.
12. **Princípio Fail-Safe:** Toda falha crítica de dados, comunicação, risco ou execução deve resultar no bloqueio de novas operações.
13. **Proibição de Martingale:** Nunca utilizar aumento de lote após perdas, grid ilimitado ou estratégias de recuperação destrutivas.
14. **Imunidade dos Arquivos de Risco:** Agentes não podem possuir permissão de escrita em módulos ou arquivos de configuração de risco.
15. **Não implementar aprendizado online não supervisionado em produção:** Modelos de produção só são substituídos após aprovação em testes de validação purgada fora da amostra com mecanismo de rollback.

---

## 3. Matriz dos Oito Agentes Especializados

* **AG01 — TREND INTELLIGENCE:** Análise multi-timeframe de tendências (EMAs, ADX, MACD, Regressão Linear).
* **AG02 — MARKET STRUCTURE INTELLIGENCE:** Mapeamento determinístico de BOS, CHoCH, Liquidity Sweeps e zonas de oferta/demanda.
* **AG03 — MOMENTUM AND BREAKOUT:** Compressão de volatilidade (Bollinger Squeeze), aceleração e expansão de range.
* **AG04 — MEAN REVERSION:** Desvios estatísticos (Z-Scores, RSI dinâmico, distanciamento de médias) em regimes não-tendenciais.
* **AG05 — GOLD AND MACRO INTELLIGENCE:** Especialização em XAUUSD, Dólar DXY, yields e filtros de notícias macroeconômicas de alto impacto.
* **AG06 — QUANTITATIVE INTELLIGENCE:** Detecção de regimes via Hidden Markov Models (HMM), classificadores XGBoost/LightGBM e calibração de probabilidades.
* **AG07 — ADVERSARIAL RESEARCH:** Questionamento dialético (Bull vs. Bear), detecção de overfitting e armadilhas de liquidez via LLMs opcionais (desacoplado do scalping).
* **AG08 — PORTFOLIO INTELLIGENCE:** Cálculo do consenso ponderado, correlação de ativos e alocação prudencial de capital.

---

## 4. O Motor de Consenso

Não se adota votação majoritária simples. A decisão é governada pela equação de pontuação composta:

$$\text{Composite Score} = \sum_{i=1}^{M} \left( w_i(R) \times D_i \times C_i \times Q_i \right)$$

Onde:
* $w_i(R)$ é o peso do agente $i$ calibrado para o regime $R$.
* $D_i$ é a direção do sinal (+1 para BUY, -1 para SELL, 0 para HOLD).
* $C_i$ é a confiança calibrada do agente.
* $Q_i$ é a qualidade histórica fora da amostra do agente.

---

## 5. Parâmetros Invioláveis de Risco (Linha de Base Segura)

* **Risco por Operação:** 0,25% (Piso máximo absoluto: 0,50%).
* **Risco Agregado em Aberto:** 1,00%.
* **Perda Diária Máxima:** 1,50% (Circuit breaker encerra o dia).
* **Perda Semanal Máxima:** 3,00% (Circuit breaker encerra a semana).
* **Drawdown Limite de Emergência:** 8,00% (Bloqueio compulsório e auditoria).
* **Máximo de Posições Simultâneas:** 3 posições.
* **Stop Loss Obrigatório:** Nenhuma ordem trafega sem Stop Loss numérico válido baseado no ATR ou estrutura técnica.
* **Dimensionamento Real:** O cálculo de lotes é derivado exclusivamente via `OrderCalcProfit` do MT5, arredondado para baixo no passo do volume (`volStep`).

---

## 6. Padrões de Código e Qualidade

1. **Tipagem Estrita:** Uso de `typing` e schemas imutáveis `Pydantic V2` para todas as mensagens do barramento.
2. **Padrão de Testes:** Proibido teste que apenas verifique se arquivo existe ou importa. Testes devem cobrir asserções dinâmicas de borda e os 20 modos de falha do sistema.
3. **Threading COM:** Todas as operações da API Python do MetaTrader 5 devem ser executadas em fila serializada por uma única thread dedicada (`max_workers=1`).
4. **Isolamento de SO:** O núcleo analítico não deve conter chamadas diretas dependentes do Windows, mantendo portabilidade plena para contêineres Linux.

