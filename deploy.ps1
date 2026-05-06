# deploy.ps1 - Update MeiBot on the server from Windows PowerShell

$SERVER_USER = "pvserver"
$SERVER_IP = "192.168.1.23"
$PROJECT_DIR = "~/MeiBot"

Write-Host "🚀 Iniciando deploy para o servidor Alfredo ($SERVER_IP)..." -ForegroundColor Cyan

$commands = @(
    "cd $PROJECT_DIR",
    "echo '📥 Baixando últimas alterações do Git...'",
    "git pull origin master",
    "echo '♻️ Reiniciando serviços...'",
    "sudo systemctl restart meibot-backend",
    "sudo systemctl restart meibot-bot",
    "echo '✅ Deploy concluído com sucesso!'",
    "sudo systemctl status meibot-backend meibot-bot --no-pager"
)

$remoteCommand = $commands -join " && "

# Executa os comandos via SSH
ssh "$SERVER_USER@$SERVER_IP" "$remoteCommand"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Ocorreu um erro durante o deploy." -ForegroundColor Red
} else {
    Write-Host "✨ Tudo pronto!" -ForegroundColor Green
}
