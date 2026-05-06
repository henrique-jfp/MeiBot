# MeiBot - Deployment Script

This script automates the update process on the HP Pavilion X360 server.

## How to use

1. On your local machine, after committing and pushing changes to GitHub:
   ```bash
   ./deploy.sh
   ```

## Requirements
- SSH access to `pvserver@192.168.1.23`
- `git` installed on the server
- Systemd services configured as `meibot-backend.service` and `meibot-bot.service`
