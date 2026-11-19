# QUANT HERMES no Windows (RoboForex ProCent)

O sistema inteiro roda **numa máquina Windows**, a mesma em que o terminal MetaTrader 5 da RoboForex está aberto. Não há cérebro Linux, não há Docker obrigatório e não há Wine.

O processo único é `deploy/windows/service_main.py`. Ele sobe o monitoramento em `127.0.0.1:8000` e, no modo `mt5_demo`, chama o pacote `MetaTrader5` direto. O gateway HTTP remoto existe no código e fica **desligado** (`remote_gateway_enabled: false` e variável `HERMES_REMOTE_GATEWAY` ausente).

Docker (`docker-compose.yml`) é só opcional para experimento. Não faz parte da instalação da conta.

## Por que Agendador de Tarefas, e não NSSM

O terminal MT5 vive na sessão interativa do usuário. Um serviço de Windows (NSSM ou serviço pywin32) sobe na sessão 0 e **não enxerga** esse terminal. Por isso o auto-start é uma tarefa do Agendador:

* dispara no logon **do mesmo usuário** que abre o RoboForex;
* reinicia até 5 vezes, com 1 minuto de intervalo, se o processo cair;
* não exige binário de terceiros.

NSSM só faria sentido se o terminal também fosse aberto nessa mesma sessão, o que este guia não usa.

Parar com educação: crie o arquivo `data\storage\hermes.stop` ou use Ctrl+C no console. O Agendador, ao encerrar a tarefa à força, mata o processo; prefira o arquivo de parada.

## 1. O que instalar antes

1. Windows 10, Windows 11 ou Windows Server, 64 bits.
2. Python 3.11 de 64 bits (python.org). Marque **Add python.exe to PATH**. O MetaTrader5 não tem wheel de 32 bits utilizável aqui.
3. Terminal RoboForex MT5 instalado. Ainda não faça login na conta real.

## 2. Conta demo ProCent primeiro

1. No site da RoboForex, abra uma conta **demo ProCent** (moeda **USC**, centavos). Anote login, senha e servidor (algo como `RoboForex-Pro`).
2. Abra o terminal, entre nessa conta demo e confirme em Propriedades da conta que a moeda é **USC**.
3. Clique em **Algo Trading** até ficar verde. Sem isso o preflight recusa.
4. No Observador de Mercado, mostre `EURUSD` e `XAUUSD` (ou o nome com o sufixo que a conta usa). Se o símbolo tiver sufixo, grave em `config/system.yaml`:

```yaml
broker:
  symbol_suffix: "m"   # exemplo; use o sufixo real ou aliases
```

5. Não marque a conta real ainda.

## 3. Preparar o QUANT HERMES

No PowerShell, na pasta do repositório (não precisa ser administrador para o venv; o firewall pede elevação e, se faltar, o processo continua preso a `127.0.0.1`):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\windows\setup.ps1
```

O script:

* cria `.venv` com Python 3.11;
* instala o projeto e o pacote `MetaTrader5`;
* copia `.env.production.example` para `.env` se `.env` não existir;
* tenta uma regra de firewall bloqueando a porta 8000 vinda da rede;
* registra as tarefas `QUANT-HERMES`, `QUANT-HERMES-Backup` e `QUANT-HERMES-LogRotate`.

Edite `.env` e preencha pelo menos:

```text
HERMES_OPERATOR_TOKEN=um-segredo-longo-so-seu
HERMES_EXECUTION_MODE=mt5_demo
MT5_LOGIN=12345678
MT5_PASSWORD=senha-da-demo
MT5_SERVER=RoboForex-Pro
MT5_PATH=C:\Program Files\RoboForex MT5 Terminal\terminal64.exe
```

Não há token padrão. `HERMES_GATEWAY_TOKEN` fica vazio enquanto o gateway remoto estiver desligado. `HERMES_BIND_HOST` diferente de `127.0.0.1` é recusado.

Deixe o terminal demo aberto e logado. Rode:

```powershell
.\.venv\Scripts\python.exe deploy\preflight_check.py --require-terminal
```

O preflight só segue se: Python é 3.11+, o pacote MetaTrader5 importa, o terminal está no ar e logado, a moeda é USC (ou CENT), o mapeamento de cada símbolo do `config/instruments.yaml` acha o nome no broker, o AutoTrading está ligado e `HERMES_OPERATOR_TOKEN` existe. Ele não envia ordem. Se falhar, não suba o serviço.

Subida manual (primeiro dia):

```powershell
.\.venv\Scripts\python.exe deploy\windows\service_main.py
```

Abra `http://127.0.0.1:8000/dashboard` nesta mesma máquina. De outra máquina isso não responde: a porta não está na rede. Para ver de longe, use Área de Trabalho Remota ou um túnel, não publique 8000.

Confira no diário do terminal se alguma ordem de teste que você autorizar na demo aparece com stop. Este repositório, na revisão, não dispara ordem sozinho contra a corretora.

## 4. Auto-start, log e backup

A tarefa `QUANT-HERMES` sobe no próximo logon. Para subir agora sem reiniciar a sessão:

```powershell
Start-ScheduledTask -TaskName "QUANT-HERMES"
```

Logs em `logs\`. Todo dia, 03:15, `deploy\log_rotate.py` gira arquivo que passou de 50 MB e guarda 7 cópias.

Backup às 03:00: `deploy\backup_state.py` grava `data\backups\hermes_state_backup_*.tar.gz` com SHA-256, usando a API de backup online do SQLite (funciona com o banco aberto no Windows).

Parar:

```powershell
New-Item -ItemType File -Force -Path data\storage\hermes.stop
```

Apague `hermes.stop` antes de subir de novo. O processo também apaga esse arquivo na partida.

## 5. Só depois: conta real

Repita a demo por tempo suficiente para ver rejeição de risco, stop e reconciliação. Aí:

1. Pare a tarefa `QUANT-HERMES`.
2. Troque no `.env` o login, a senha e o servidor para a conta **real ProCent**, ainda em USC. Não use conta em USD.
3. Entre no terminal com essa conta, Algo Trading verde.
4. Rode de novo `deploy\preflight_check.py --require-terminal` e leia a moeda e o login impressos.
5. Só então `Start-ScheduledTask -TaskName "QUANT-HERMES"`.

O teto de risco do código não muda na conta real: 0,25% por operação, 0,50% de piso máximo, perda diária 1,50%, semanal 3%, drawdown 8%, no máximo 3 posições, stop obrigatório.

## 6. Testes sem o terminal

Na máquina de desenvolvimento, sem MetaTrader5:

```powershell
$env:HERMES_EXECUTION_MODE = "paper"
$env:HERMES_OPERATOR_TOKEN = "token-de-teste-longo"
.\.venv\Scripts\python.exe -m pytest
```

Testes que precisariam do terminal conectado são pulados se o pacote não importa ou se o preflight de terminal não foi pedido. O modo paper não chama `initialize()`.

## 7. O que não usar

* `deploy/setup_vps.sh` e `deploy/systemd/` são resquício de um desenho Linux. Não provisionam esta instalação.
* Wine não é suportado.
* Não rode dois processos HERMES no mesmo terminal.
