# Auditoria de Licenças e Diretrizes de Propriedade Intelectual
**Projeto:** QUANT HERMES — Autonomous Multi-Agent Quantitative Trading System  
**Fase:** FASE 0 — Auditoria e Planejamento  
**Documento:** `docs/research/license_audit.md`  

---

## 1. Mapeamento de Licenças dos Repositórios Auditados

| Repositório | Licença Declarada | Tipo de Licença | Risco de Contaminação Copyleft | Parecer Legal / Engenharia |
| :--- | :--- | :--- | :--- | :--- |
| **Samvid Trading Core** | MIT License | Permissiva | Baixo | Reutilização permitida com preservação de copyright. |
| **Nexus Trading System MT5** | **GNU AGPL-3.0** | **Copyleft Estrito de Rede** | **EXTREMO** | **CÓDIGO REJEITADO.** Proibida cópia direta. Clean-Room obrigatório. |
| **Multi-Agent Quant** | MIT License | Permissiva | Baixo | Reutilização permitida com preservação de copyright. |
| **MT5 Portfolio Framework** | MIT License | Permissiva | Baixo | Reutilização permitida com preservação de copyright. |
| **TradingAgents** | Apache 2.0 | Permissiva c/ Patentes | Baixo / Moderado | Reutilização permitida com preservação de avisos de licença e NOTICE. |
| **EA31337** | **GNU GPL-3.0** | **Copyleft Estrito** | **ALTO** | **CÓDIGO REJEITADO.** Proibida cópia direta de código MQL/C++. |

---

## 2. Riscos Específicos e Implicações de Copyleft

### 2.1 GNU AGPL-3.0 (Nexus Trading System MT5)
A GNU Affero General Public License v3 (AGPL-3.0) estende o copyleft do GPL para software executado como serviço em rede (SaaS / VPS).
* **Impacto:** Se qualquer linha, função ou módulo do Nexus for copiado e incorporado ao QUANT HERMES, a licença AGPL exige que o código-fonte integral de todo o QUANT HERMES seja disponibilizado publicamente para qualquer usuário ou operador que se conecte ao sistema via rede (inclusive APIs ou dashboards).
* **Decisão Inegociável:** **Nenhuma linha de código do Nexus Trading System MT5 será copiada, importada ou derivada diretamente.** O QUANT HERMES utilizará apenas seus conceitos arquiteturais abstratos de forma independente.

### 2.2 GNU GPL-3.0 (EA31337)
A GPL-3.0 aplica o princípio de "contaminação viral": qualquer projeto que contenha código sob GPL-3.0 deve, obrigatoriamente, ser distribuído sob GPL-3.0 se for redistribuído ou empacotado.
* **Decisão Inegociável:** **Nenhum arquivo `.mq5`, `.mq4` ou `.mqh` do EA31337 será copiado.** Todos os scripts, bibliotecas e Expert Advisors desenvolvidos para o QUANT HERMES serão 100% originais.

---

## 3. Protocolo de Engenharia Clean-Room (Sala Limpa)

Para garantir que o QUANT HERMES seja um sistema autônomo, proprietário e livre de disputas de licenciamento ou contaminação de copyleft:

1. **Separação de Papéis:**
   * A fase de auditoria analisa o repositório de referência unicamente para entender *problemas a evitar* e *requisitos funcionais abstratos*.
   * Toda a codificação do QUANT HERMES será escrita do zero, baseada em especificações de requisitos formais, schemas Pydantic próprios e interfaces abstratas.
2. **Proibição de Copiar-Colar:**
   * Nenhuma cópia direta de código de terceiros (`copy-paste`) é autorizada no repositório do QUANT HERMES.
3. **Isolamento da Pasta de Referência:**
   * A pasta `references/` utilizada na Fase 0 é meramente transitória para auditoria forense local e **deve ser incluída no `.gitignore`** para que nunca seja commitada no repositório final do projeto.
4. **Licença Adotada pelo QUANT HERMES:**
   * O QUANT HERMES será estruturado sob uma licença clara e institucional (definida como proprietária interna ou MIT para componentes de base modular, a critério dos mantenedores do projeto).

---

## 4. Verificação de 19/11/2026 — nada de GPL/AGPL no pacote

A pasta `references/` está no `.gitignore` e **não faz parte do pacote instalável**. Uma busca nos módulos `core`, `execution`, `risk`, `strategies`, `intelligence`, `portfolio`, `monitoring`, `data` e `deploy` não encontra `import` de `references`, `ea31337` ou `nexus`. O teste `tests/security/test_license_boundary.py` repete essa busca. Código sob GPL-3.0 (EA31337) e AGPL-3.0 (Nexus) permanece rejeitado: não é importado nem copiado para o pacote principal. Se uma cópia local de `references/` existir na máquina de auditoria, ela fica fora do Git e fora do caminho de import.

