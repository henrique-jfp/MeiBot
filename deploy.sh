#!/bin/bash
# deploy.sh - Update MeiBot on the server

SERVER_USER="pvserver"
SERVER_IP="192.168.1.23"
PROJECT_DIR="~/MeiBot"

echo "🚀 Iniciando deploy para o servidor Alfredo ($SERVER_IP)..."

ssh $SERVER_USER@$SERVER_IP "bash -s" << EOF
    cd $PROJECT_DIR
    echo "📥 Baixando últimas alterações do Git..."
    git pull origin master
    
    echo "♻️ Reiniciando serviços..."
    sudo systemctl restart meibot-backend
    sudo systemctl restart meibot-bot
    
    echo "✅ Deploy concluído com sucesso!"
    sudo systemctl status meibot-backend meibot-bot --no-pager
EOF
