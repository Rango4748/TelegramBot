#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# Predefined configuration values (replace these with your actual values)
BOT_TOKEN="YOUR_BOT_TOKEN"  # Replace with your Telegram Bot Token
ADMIN_ID="YOUR_ADMIN_ID"    # Replace with your Telegram Admin ID (a number, e.g., 123456789)
SUPPORT_USERNAME="@YourSupportUsername"  # Replace with your Telegram support username (e.g., @SupportID)

# Function to validate inputs
validate_bot_token() {
  local token=$1
  if [[ $token =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    return 0
  else
    return 1
  fi
}

validate_admin_id() {
  local id=$1
  if [[ $id =~ ^[0-9]+$ ]]; then
    return 0
  else
    return 1
  fi
}

validate_support_username() {
  local username=$1
  if [[ $username =~ ^@.+$ ]]; then
    return 0
  else
    return 1
  fi
}

# Check configuration values
if [ -z "$BOT_TOKEN" ] || ! validate_bot_token "$BOT_TOKEN"; then
  echo "Error: BOT_TOKEN is empty or invalid. Please set a valid Bot Token in the script."
  exit 1
fi

if [ -z "$ADMIN_ID" ] || ! validate_admin_id "$ADMIN_ID"; then
  echo "Error: ADMIN_ID is empty or invalid. Please set a valid Admin ID (a number) in the script."
  exit 1
fi

if [ -z "$SUPPORT_USERNAME" ] || ! validate_support_username "$SUPPORT_USERNAME"; then
  echo "Error: SUPPORT_USERNAME is empty or invalid. Please set a valid username (e.g., @SupportID) in the script."
  exit 1
fi

# Check disk space
echo "Checking disk space..."
if ! df -h / | grep -q "Avail"; then
  echo "Error: Unable to check disk space. Please check your system."
  exit 1
fi
AVAILABLE_SPACE=$(df / | tail -1 | awk '{print $4}')
if [ "$AVAILABLE_SPACE" -lt 10000 ]; then  # Less than 10MB available
  echo "Error: Insufficient disk space. Please free up space and try again."
  exit 1
fi

# Function to install the bot
install_bot() {
  # Check if bot is already installed
  if [ -d "/root/bot" ] || [ -f "/etc/systemd/system/telegram-bot.service" ]; then
    echo "Bot is already installed. Please uninstall first if you want to reinstall."
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
  curl -Ls https://raw.githubusercontent.com/Rango4748/TelegramBot/main/bot.py -o /root/bot/bot.py

  # Check if download was successful
  if [ ! -f /root/bot/bot.py ]; then
    echo "Failed to download bot.py. Please check the GitHub repository URL."
    exit 1
  fi

  # Replace placeholders in bot.py
  echo "Configuring bot..."
  sed -i "s/BOT_TOKEN = \"BOT_TOKEN_PLACEHOLDER\"/BOT_TOKEN = \"$BOT_TOKEN\"/g" /root/bot/bot.py
  sed -i "s/ADMIN_ID = ADMIN_ID_PLACEHOLDER/ADMIN_ID = $ADMIN_ID/g" /root/bot/bot.py
  sed -i "s/SUPPORT_USERNAME = \"SUPPORT_USERNAME_PLACEHOLDER\"/SUPPORT_USERNAME = \"$SUPPORT_USERNAME\"/g" /root/bot/bot.py

  # Create systemd service
  echo "Creating systemd service..."
  cat << EOF > /etc/systemd/system/telegram-bot.service
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /root/bot/bot.py
WorkingDirectory=/root/bot
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

  # Enable and start the service
  systemctl daemon-reload
  systemctl enable telegram-bot
  systemctl start telegram-bot

  # Check service status
  if systemctl is-active --quiet telegram-bot; then
    echo "Bot installed and running as a systemd service."
  else
    echo "Failed to start the bot. Check logs with 'journalctl -u telegram-bot'."
    exit 1
  fi

  # Copy script to /usr/local/bin/bot
  echo "Setting up 'bot' command..."
  cp "$0" /usr/local/bin/bot
  chmod +x /usr/local/bin/bot
  if [ -f /usr/local/bin/bot ] && [ -s /usr/local/bin/bot ]; then
    echo "Successfully created /usr/local/bin/bot"
    ls -l /usr/local/bin/bot
  else
    echo "Failed to create /usr/local/bin/bot or file is empty"
    exit 1
  fi

  # Check if /usr/local/bin is in PATH
  if ! echo $PATH | grep -q "/usr/local/bin"; then
    echo "Adding /usr/local/bin to PATH..."
    echo "export PATH=\$PATH:/usr/local/bin" >> /root/.bashrc
    export PATH=$PATH:/usr/local/bin
    echo "Added /usr/local/bin to PATH. Run 'source /root/.bashrc' or restart your shell."
  fi

  echo "You can now use the 'bot' command to manage the bot."
}

# Function to uninstall the bot
uninstall_bot() {
  # Check if bot is installed
  if [ ! -d "/root/bot" ] && [ ! -f "/etc/systemd/system/telegram-bot.service" ]; then
    echo "Bot is not installed."
    exit 1
  fi

  echo "Stopping and disabling systemd service..."
  systemctl stop telegram-bot 2>/dev/null
  systemctl disable telegram-bot 2>/dev/null
  rm -f /etc/systemd/system/telegram-bot.service
  systemctl daemon-reload
  systemctl reset-failed

  echo "Removing bot files..."
  rm -rf /root/bot

  echo "Removing 'bot' command..."
  rm -f /usr/local/bin/bot

  echo "Bot uninstalled successfully."
}

# Debug: Print when script is run
echo "Running bot management script..."

# Menu
while true; do
  echo "Telegram Bot Management"
  echo "1. Install"
  echo "2. Uninstall"
  echo "0. Exit"
  read -p "Select an option [0-2]: " choice

  case $choice in
    1)
      install_bot
      break
      ;;
    2)
      uninstall_bot
      break
      ;;
    0)
      echo "Exiting..."
      exit 0
      ;;
    *)
      echo "Invalid option. Please select 0, 1, or 2."
      ;;
  esac
done
