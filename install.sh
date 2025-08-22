#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# Update package list
echo "Updating package list..."
apt update -y

# Install Python and pip if not installed
if ! command -v python3 &> /dev/null; then
  echo "Installing Python and pip..."
  apt install python3 python3-pip -y
fi

# Install required Python libraries
echo "Installing Python libraries..."
pip3 install python-telegram-bot jdatetime requests

# Create directory
echo "Creating directory /root/bot..."
mkdir -p /root/bot

# Download bot code
echo "Downloading bot.py..."
curl -Ls https://raw.githubusercontent.com/YourUsername/TelegramBot/main/bot.py -o /root/bot/bot.py

# Check if download was successful
if [ ! -f /root/bot/bot.py ]; then
  echo "Failed to download bot.py. Please check the GitHub repository URL."
  exit 1
fi

# Prompt for user inputs
echo "Please provide the following details:"
read -p "Bot Token: " BOT_TOKEN
read -p "Admin ID: " ADMIN_ID
read -p "Support Telegram Username (e.g., @SupportID): " SUPPORT_USERNAME

# Replace placeholders in bot.py
echo "Configuring bot..."
sed -i "s/BOT_TOKEN = \"BOT_TOKEN_PLACEHOLDER\"/BOT_TOKEN = \"$BOT_TOKEN\"/g" /root/bot/bot.py
sed -i "s/ADMIN_ID = ADMIN_ID_PLACEHOLDER/ADMIN_ID = $ADMIN_ID/g" /root/bot/bot.py
sed -i "s/SUPPORT_USERNAME = \"SUPPORT_USERNAME_PLACEHOLDER\"/SUPPORT_USERNAME = \"$SUPPORT_USERNAME\"/g" /root/bot/bot.py

# Install screen if not installed
if ! command -v screen &> /dev/null; then
  echo "Installing screen..."
  apt install screen -y
fi

# Run the bot in a detached screen session
echo "Starting the bot in background..."
screen -dmS bot python3 /root/bot/bot.py

echo "Bot installed and running in background. Use 'screen -r bot' to attach."
