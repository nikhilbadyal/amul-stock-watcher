# 🛒 Amul Shop Product Availability Notifier

Don't want to self host? Use the [Amul Stock Watcher](https://t.me/amul_notify) hosted version!

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

3. Create a `.env` file in the project root with the following variables:
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
```

### Usage

Run the script:
```bash
python main.py
```

## ⚙️ Configuration

### Environment Variables

| Variable              | Description                         | Default  |
|-----------------------|-------------------------------------|----------|
| `TELEGRAM_BOT_TOKEN`  | Your Telegram bot token             | Required |
| `TELEGRAM_CHANNEL_ID` | Your Telegram channel ID            | Required |
| `PINCODE`             | Your delivery pincode               | Required |
| `DEFAULT_STORE`       | Default store location              | Required |
| `FORCE_NOTIFY`        | Send notifications for all products | false    |
| `REQUEST_TIMEOUT`     | API request timeout in seconds      | 3        |

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
- The script uses a consolidated notification format to avoid message spam

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This project is for educational purposes only. Please use responsibly and in accordance with Amul Shop's terms of service.
