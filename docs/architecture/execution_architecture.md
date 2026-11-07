# Arquitetura de Execução e Adaptador MetaTrader 5
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/architecture/execution_architecture.md`  

---

## 1. Princípios da Camada de Execução

A camada de execução do QUANT HERMES é estritamente desacoplada da inteligência e do risco. Sua única responsabilidade é transformar ordens autorizadas em execuções atômicas, seguras, auditáveis e idempotentes no terminal de negociação.

### Regras Fundamentais:
1. **Envio não é Execução:** O envio de uma ordem não é considerado uma operação concluída até que o terminal confirme o bilhete (`ticket`) e o preenchimento real através da consulta de posições ativas.
2. **Idempotência Obrigatória:** Toda solicitação de ordem possui um `idempotency_key` exclusivo. Em caso de timeout ou perda momentânea de resposta de rede, o executor nunca reenvia uma ordem sem antes reconciliar as ordens pendentes e posições abertas na corretora.
3. **Threading COM Seguro no Windows:** Diferente do erro identificado no repositório *Nexus* (que tentou utilizar 4 threads concorrentes para chamadas COM do MT5), o QUANT HERMES executa todas as chamadas nativas do pacote `MetaTrader5` através de um **Executor de Thread Única Dedicada** (`SingleThreadExecutionWorker`), garantindo conformidade com o modelo STA (Single-Threaded Apartment) do Windows e eliminando erros de IPC.

---

## 2. Máquina de Estados de Execução de Ordens

```
[Sinal Gerado] ──► [Decisão do Portfólio] ──► [Autorização do Risco]
                                                        │
                   ┌────────────────────────────────────┘
                   ▼
         [Ordem Criada (PENDING)]
                   │
                   ▼ (Fila Assíncrona do Worker COM)
         [Validação Pré-Voo (OrderCheck)]
            ├─► Margem Insuficiente ──► [REJEITADA_MARGEM]
            ├─► Spread Excessivo     ──► [REJEITADA_SPREAD]
            └─► Preço Inválido       ──► [REJEITADA_PRECO]
                   │
                   ▼ (order_send atômico)
         [Ordem Enviada ao Broker]
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
   [Retcode OK (10009)]   [Timeout / Erro de Rede]
         │                   │
         │                   ▼ (Reconciliação Ativa)
         │           [Consulta positions_get]
         │              ├─► Posição Existe? ──► [RECUPERADA_COM_SUCESSO]
         │              └─► Posição Ausente?──► [FALHA_CONFIRMADA]
         ▼
   [Posição Aberta e Rastreada (ACTIVE)]
         │
         ├─► Modificação de Stop Loss / Take Profit
         ├─► Trailing Stop Dinâmico
         └─► Gatilho de Saída / Invalidação / Fechamento de Sexta-Feira
                   │
                   ▼
         [Posição Fechada (CLOSED)] ──► [Log em Base Histórica e Telemetria]
```

---

## 3. Interface Abstrata: `TradingPlatformAdapter`

Para permitir portabilidade futura (VPS Linux, Paper Trading e simuladores de backtesting) sem reescrever a lógica do sistema, todo o ecossistema comunica-se com a interface abstrata:

```python
from abc import ABC, abstractmethod

class TradingPlatformAdapter(ABC):
    @abstractmethod
    async def connect(self) -> bool:
        """Inicializa e autentica a conexão com a plataforma."""
        pass

    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """Retorna balance, equity, margem livre, alavancagem e moeda."""
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> SymbolSpec:
        """Retorna especificações reais (volStep, volMin, volMax, tickValue, spread)."""
        pass

    @abstractmethod
    async def check_order(self, request: OrderRequest) -> OrderCheckResult:
        """Executa OrderCheck prévio para validar margem e parâmetros."""
        pass

    @abstractmethod
    async def send_order(self, request: OrderRequest) -> OrderExecutionResult:
        """Despacha a ordem com idempotência e retorno auditável."""
        pass

    @abstractmethod
    async def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        """Consulta as posições abertas reais no terminal."""
        pass

    @abstractmethod
    async def close_position(self, ticket: int, volume: float | None = None) -> bool:
        """Fecha uma posição total ou parcialmente."""
        pass
```

### Implementações Planejadas:
1. `WindowsMT5Adapter`: Conecta nativamente via pacote Python `MetaTrader5` utilizando o terminal 64-bit instalado no Windows 11.
2. `PaperTradingAdapter`: Simula execução local em tempo real com ticks reais, modelando spread dinâmico, slippage aleatório e latência.
3. `BacktestAdapter`: Executa sobre base de dados Parquet histórica com resolução tick-a-tick sem vazamento de informação.
4. `LinuxMT5BridgeAdapter` (Fase 9): Comunicação do cérebro Linux com terminal Windows através de túnel seguro gRPC/FastAPI.

---

## 4. Tratamento Específico de Características da Corretora

### 4.1 Modos de Preenchimento (*Filling Modes*)
O QUANT HERMES não assume um tipo fixo de preenchimento (`ORDER_FILLING_FOK` ou `ORDER_FILLING_IOC`). O adaptador consulta dinamicamente `symbol_info.filling_mode`:
* Se o símbolo aceitar `IOC`, prioriza-se `IOC` para evitar que uma ordem parcial fique pendente no book em scalping.
* Se aceitar apenas `RETURN`, utiliza-se a política suportada pela corretora.

### 4.2 Contas Hedging vs. Netting
* **Hedging:** Cada trade recebe um `magic number` exclusivo por estratégia e gera um ticket independente de posição, permitindo posições simultâneas compradas e vendidas no mesmo ativo se forem de horizontes temporais diferentes.
* **Netting:** O sistema mantém uma **tabela de alocação virtual interna**, reconciliando o volume agregado consolidado no terminal com as exposições unitárias de cada estratégia.

### 4.3 Gestão de Sufixos de Ativos
Através do mapeamento dinâmico em `config/instruments.yaml`, símbolos lógicos universais (`EURUSD`, `XAUUSD`) são traduzidos para os símbolos reais da corretora (ex: `EURUSD_i`, `EURUSD.r`, `XAUUSD.m`), garantindo que a inteligência opere de forma agnóstica à corretora.

