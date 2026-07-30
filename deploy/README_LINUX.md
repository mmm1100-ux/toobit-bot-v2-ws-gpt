# Linux deployment with systemd

This deployment keeps the bot running after SSH/terminal disconnects and starts it automatically after a server reboot.

## 1. Install prerequisites

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

Python 3.11 or newer is required.

## 2. Create a dedicated system user

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin toobitbot
sudo mkdir -p /opt/toobit-bot
sudo chown -R toobitbot:toobitbot /opt/toobit-bot
```

## 3. Clone and install

```bash
sudo -u toobitbot git clone https://github.com/mmm1100-ux/toobit-bot-v2-ws-gpt.git /opt/toobit-bot
cd /opt/toobit-bot
sudo -u toobitbot python3 -m venv .venv
sudo -u toobitbot .venv/bin/python -m pip install --upgrade pip
sudo -u toobitbot .venv/bin/python -m pip install -e '.[dev]'
sudo -u toobitbot cp config.example.json config.json
```

Edit `/opt/toobit-bot/config.json` and keep `dry_run` set to `true` until live exchange behavior is verified.

## 4. Store API credentials outside the repository

```bash
sudo install -m 600 /dev/null /etc/toobit-bot.env
sudo nano /etc/toobit-bot.env
```

Contents:

```ini
TOOBIT_API_KEY=replace_with_restricted_key
TOOBIT_API_SECRET=replace_with_secret
PYTHONUNBUFFERED=1
```

Use a restricted futures-trading API key with withdrawal disabled.

## 5. Validate before starting

```bash
cd /opt/toobit-bot
sudo -u toobitbot .venv/bin/python -m app.main --config config.json --check
sudo -u toobitbot .venv/bin/python -m pytest
```

## 6. Install the systemd service

```bash
sudo cp deploy/toobit-bot.service /etc/systemd/system/toobit-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now toobit-bot.service
```

## 7. Service management

```bash
sudo systemctl status toobit-bot.service
sudo systemctl restart toobit-bot.service
sudo systemctl stop toobit-bot.service
sudo systemctl start toobit-bot.service
sudo journalctl -u toobit-bot.service -f
```

The application JSON log is also written to the path configured by `runtime.log_path`, normally:

```bash
tail -f /opt/toobit-bot/logs/bot.log
```

## 8. Updating the bot

```bash
sudo systemctl stop toobit-bot.service
cd /opt/toobit-bot
sudo -u toobitbot git pull --ff-only origin main
sudo -u toobitbot .venv/bin/python -m pip install -e '.[dev]' --upgrade
sudo -u toobitbot .venv/bin/python -m app.main --config config.json --check
sudo -u toobitbot .venv/bin/python -m pytest
sudo systemctl start toobit-bot.service
sudo systemctl status toobit-bot.service
```

Do not delete `state.json` during normal updates. It prevents duplicate signals/trades after restart.

## 9. Reboot verification

```bash
sudo reboot
```

After reconnecting:

```bash
sudo systemctl is-enabled toobit-bot.service
sudo systemctl is-active toobit-bot.service
sudo journalctl -u toobit-bot.service -n 100 --no-pager
```

Expected results are `enabled` and `active`.
