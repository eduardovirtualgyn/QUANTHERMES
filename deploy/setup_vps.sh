#!/usr/bin/env bash
# ==============================================================================
# QUANT HERMES — SCRIPT DEFENSIVO DE PROVISIONAMENTO DE VPS LINUX
# Ambiente Alvo: Ubuntu 22.04 / 24.04 LTS x86_64
# Execução: sudo bash deploy/setup_vps.sh
# ==============================================================================

set -euo pipefail
IFS=$'\n\t'

echo "=================================================================="
echo ">>> QUANT HERMES — Iniciando Provisionamento do Nó Linux em VPS"
echo "=================================================================="

# 1. Verificação de Privilégios Root
if [ "$EUID" -ne 0 ]; then
    echo "[-] Erro: Este script deve ser executado como root (sudo)."
    exit 1
fi

# 2. Atualização de Pacotes do Sistema
echo ">>> [1/7] Atualizando repositórios e pacotes do sistema operacional..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    ufw \
    fail2ban \
    htop \
    iotop \
    jq \
    logrotate

# 3. Otimização de Limites de Sistema (Kernel & Sockets)
echo ">>> [2/7] Configurando limites de descritores de arquivos e parâmetros de rede..."
cat << 'EOF' > /etc/sysctl.d/99-hermes-quant.conf
# Otimizações de rede para baixa latência e alta concorrência de sockets
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
vm.max_map_count = 262144
vm.swappiness = 10
EOF
sysctl --system > /dev/null

cat << 'EOF' > /etc/security/limits.d/99-hermes.conf
# Limites de arquivos abertos para a aplicação quantitativa
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
EOF

# 4. Instalação Oficial do Docker Engine e Docker Compose Plugin
echo ">>> [3/7] Instalando Docker Engine oficial..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

# 5. Criação de Usuário e Estrutura de Diretórios da Aplicação
echo ">>> [4/7] Configurando diretórios persistentes e permissões..."
APP_DIR="/opt/hermes"
mkdir -p "${APP_DIR}/data/storage"
mkdir -p "${APP_DIR}/data/parquet"
mkdir -p "${APP_DIR}/logs"

if ! id "hermes" &>/dev/null; then
    useradd -u 1000 -m -s /bin/bash hermes
    usermod -aG docker hermes
fi

chown -R hermes:hermes "${APP_DIR}"
chmod -R 750 "${APP_DIR}"

# 6. Configuração de Hardening de Firewall (UFW)
echo ">>> [5/7] Configurando firewall defensivo (UFW)..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH Administrativo'
# A porta da API (8000) e do Gateway (8001) NÃO devem ficar abertas à Internet pública!
# Devem ser acessadas via túnel SSH, WireGuard VPN ou Reverse Proxy (Nginx/Caddy com HTTPS/mTLS)
ufw --force enable

# 7. Configuração de Logrotate para o QUANT HERMES
echo ">>> [6/7] Configurando rotação automática de logs..."
cat << 'EOF' > /etc/logrotate.d/hermes-quant
/opt/hermes/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 hermes hermes
}
EOF

# 8. Verificação Final de Integridade
echo ">>> [7/7] Verificando serviços ativos..."
docker --version
docker compose version

echo "=================================================================="
echo ">>> SUCESSO: VPS Linux provisionada com sucesso para QUANT HERMES."
echo ">>> Diretório base da aplicação: ${APP_DIR}"
echo ">>> Para iniciar os serviços: cd ${APP_DIR} && docker compose up -d"
echo "=================================================================="
