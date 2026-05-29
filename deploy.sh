#!/bin/bash
set -e

SERVER_IP="16.171.206.198"
PEM_KEY="bot.pem"
USER="ubuntu"
REMOTE_DIR="/home/ubuntu/transportation-bot"

echo "🔧 Fixing PEM key permissions..."
chmod 600 "$PEM_KEY"

echo "📦 1/6 - Installing system packages (Tesseract + OCR)..."
ssh -i "$PEM_KEY" -o ConnectTimeout=10 "$USER@$SERVER_IP" "sudo apt-get update -qq && sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng python3-pip python3-venv"

echo "📂 2/6 - Creating project directory..."
ssh -i "$PEM_KEY" "$USER@$SERVER_IP" "mkdir -p $REMOTE_DIR/downloads"

echo "📤 3/6 - Uploading bot files..."
scp -i "$PEM_KEY" bot.py extractor.py requirements.txt "$USER@$SERVER_IP:$REMOTE_DIR/"

echo "🐍 4/6 - Setting up Python virtual environment..."
ssh -i "$PEM_KEY" "$USER@$SERVER_IP" "cd $REMOTE_DIR && python3 -m venv venv && venv/bin/pip install -r requirements.txt"

echo "🔐 5/6 - Creating .env file..."
read -sp "Enter your BOT_TOKEN: " TOKEN
echo
ssh -i "$PEM_KEY" "$USER@$SERVER_IP" "echo 'BOT_TOKEN=$TOKEN' > $REMOTE_DIR/.env"

echo "🚀 6/6 - Creating systemd service and starting bot..."
ssh -i "$PEM_KEY" "$USER@$SERVER_IP" << 'ENDSSH'
  sudo tee /etc/systemd/system/transportation-bot.service > /dev/null <<- SERVICE
[Unit]
Description=Transportation Bot (Telegram)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/transportation-bot
ExecStart=/home/ubuntu/transportation-bot/venv/bin/python3 /home/ubuntu/transportation-bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
  sudo systemctl daemon-reload
  sudo systemctl enable transportation-bot
  sudo systemctl restart transportation-bot
ENDSSH

echo ""
echo "✅✅✅ تم التثبيت بنجاح!"
echo "📋 لمشاهدة logs:"
echo "   ssh -i $PEM_KEY $USER@$SERVER_IP 'tail -f $REMOTE_DIR/bot.log'"
echo ""
echo "🔍 للتأكد من أن البوت شغال:"
echo "   ssh -i $PEM_KEY $USER@$SERVER_IP 'sudo systemctl status transportation-bot'"
