# 🛒 Amul Shop Product Availability Notifier

Don't want to self-host? Use the [Amul Stock Watcher](https://t.me/amul_notify) hosted version!

A Python script that monitors product availability on the Amul Shop website and sends notifications via Telegram when products become available.

## 🌟 Features

- Monitors product availability on Amul Shop website
- Sends consolidated Telegram notifications for available products
- Configurable store location and pincode
- Option to force notifications for all products regardless of availability
- Automated checking with configurable intervals
- Environment-based configuration using .env file

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- Redis server (for state persistence)
- Telegram Bot Token
- Telegram Channel ID

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/amul-stock-watcher.git
cd amul-stock-watcher
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start Redis server:
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or install Redis locally (macOS)
brew install redis
brew services start redis

# Or install Redis locally (Ubuntu)
sudo apt-get install redis-server
sudo systemctl start redis-server
```

4. Create a `.env` file in the project root with the following variables:
```env
# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHANNEL_ID=your_channel_id

# Store Configuration
PINCODE=your_pincode
DEFAULT_STORE=your_store

# Notification Settings
FORCE_NOTIFY=false
REQUEST_TIMEOUT=3

# Redis Configuration (for state persistence)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=my-very-secure-password # Optional, if your Redis server requires authentication
REDIS_SSL=false # Set to true if your Redis server requires SSL/TLS
REDIS_KEY_PREFIX=amul:
```

### Usage

Run the script:
```bash
python main.py
```

## ⚙️ Configuration

### Environment Variables

| Variable              | Description                         | Default   |
|-----------------------|-------------------------------------|-----------|
| `TELEGRAM_BOT_TOKEN`  | Your Telegram bot token             | Required  |
| `TELEGRAM_CHANNEL_ID` | Your Telegram channel ID            | Required  |
| `PINCODE`             | Your delivery pincode               | 110001  |
| `DEFAULT_STORE`       | Default store location              | delhi  |
| `FORCE_NOTIFY`        | Send notifications for all products | false     |
| `REQUEST_TIMEOUT`     | API request timeout in seconds      | 3         |
| `REDIS_HOST`          | Redis server hostname               | localhost |
| `REDIS_PORT`          | Redis server port                   | 6379      |
| `REDIS_DB`            | Redis database number               | 0         |
| `REDIS_PASSWORD`      | Redis password (if required)        | (empty)   |
| `REDIS_SSL`           | Enable SSL/TLS for Redis connection | false     |
| `REDIS_KEY_PREFIX`    | Prefix for Redis keys               | amul:     |

### Telegram Bot Setup

1. Create a new bot using [@BotFather](https://t.me/botfather) on Telegram
2. Get your bot token and add it to the `.env` file
3. Create a channel and add your bot as an administrator
4. Get your channel ID and add it to the `.env` file

## 🔄 Automation

The script can be automated using cron jobs or similar scheduling tools. Example cron job to run every 10 minutes:

```bash
*/10 * * * * cd /path/to/project && python main.py
```

## 📝 Notes

- The script checks for protein products by default
- Make sure your pincode is serviceable by Amul Shop
- Keep your `.env` file secure and never commit it to version control
- **Smart Notifications**: Only notifies when products transition from out-of-stock to in-stock (prevents spam)
- Uses Redis to persist previous state and track availability changes
- The script uses a consolidated notification format to avoid message spam

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This project is for educational purposes only. Please use responsibly and in accordance with Amul Shop's terms of service.
