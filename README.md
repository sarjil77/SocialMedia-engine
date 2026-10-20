# 🍰 Bakery Social Engine

**Automated pipeline that transforms raw bakery photos/videos into viral-ready Instagram Reels and Feed Posts.**

Powered by Gemini 2.5 Flash AI, FFmpeg video processing, and a Telegram-based human-in-the-loop approval system.

## ✨ Features

- 📸 **Telegram Bot Ingestion** — Staff sends photos/videos via private Telegram bot
- 🤖 **AI Multimodal Analysis** — Gemini 2.5 Flash classifies products and generates viral content
- 🎬 **Video Pipeline** — 9:16 normalization, color grading, B-roll hooks, text overlays, TTS voiceover mixing
- 🖼️ **Image Pipeline** — Background removal (rembg), luxury compositing, typography, brand watermarking
- 📝 **Auto-generated Content** — Punchy hooks, Hinglish/Gujarati voiceover scripts, captions with CTAs & hashtags
- ✅ **Admin Approval Gate** — Preview + inline buttons: Publish Now / Schedule / Regenerate / Discard
- 📅 **Scheduled Publishing** — APScheduler processes timed posts automatically
- 📱 **Instagram Publishing** — Meta Graph API for Reels & Feed posts via Cloudinary hosting

## 🏗️ Architecture

```
Telegram → Bot Handlers → Gemini AI Analysis → Media Pipeline → Admin Preview → Instagram
             ↓                    ↓                  ↓
         SQLite DB          TTS (edge-tts)      FFmpeg / Pillow+rembg
```

## 📁 Project Structure

```
bakery-social-engine/
├── pyproject.toml            # uv/pip config with all dependencies
├── .env.example              # Environment variable template
├── assets/
│   ├── backgrounds/          # Luxury marble/wood backgrounds
│   ├── broll/                # 1.5s vertical hook clips
│   ├── fonts/                # Montserrat, NotoSansGujarati
│   ├── music/                # Royalty-free background loops
│   └── overlays/             # Brand logo PNG
├── src/
│   ├── main.py               # Entrypoint — bot + scheduler
│   ├── config.py             # Pydantic settings from .env
│   ├── db.py                 # SQLite state tracking
│   ├── bot/
│   │   ├── handlers.py       # Media ingestion + approval callbacks
│   │   └── keyboards.py      # Inline approval keyboards
│   ├── ai/
│   │   ├── analyzer.py       # Gemini multimodal analysis
│   │   ├── prompts.py        # System prompts (Gujlish/Hinglish)
│   │   └── tts.py            # TTS wrapper (edge-tts)
│   ├── media/
│   │   ├── video_editor.py   # FFmpeg reel pipeline
│   │   └── image_editor.py   # Pillow + rembg compositing
│   └── publisher/
│       └── instagram.py      # Meta Graph API publishing
└── tests/
    └── test_core.py          # Unit tests
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- [FFmpeg](https://ffmpeg.org/download.html) installed and on PATH
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Google AI API key (for Gemini)

### Setup

```bash
# 1. Clone and enter the project
cd bakery-social-engine

# 2. Create virtual environment and install dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Add assets (see each assets/*/README.md)
# Download fonts, add backgrounds, music, etc.

# 5. Run the bot
uv run python -m src.main
```

### Getting Your API Keys

| Service | How to Get | Required? |
|---------|-----------|-----------|
| **Telegram Bot Token** | Chat with [@BotFather](https://t.me/BotFather) → `/newbot` | ✅ Yes |
| **Telegram Admin Chat ID** | Forward a message to [@userinfobot](https://t.me/userinfobot) | ✅ Yes |
| **Google Gemini API Key** | [Google AI Studio](https://aistudio.google.com/apikey) | ✅ Yes |
| **Meta Access Token** | [Meta Developer Portal](https://developers.facebook.com/) → Instagram Graph API | For publishing |
| **Cloudinary** | [Cloudinary Signup](https://cloudinary.com/) (free tier) | For publishing |

### Environment Variables

See [`.env.example`](.env.example) for all configuration options. Key settings:

```env
TELEGRAM_BOT_TOKEN=...       # Required
TELEGRAM_ADMIN_CHAT_ID=...   # Required
GEMINI_API_KEY=...            # Required
ENABLE_VOICEOVER=true         # Toggle TTS
EDGE_TTS_VOICE=gu-IN-DhwaniNeural  # Gujarati voice
```

## 🎯 Usage Flow

1. **Send Media** — Staff sends 1-3 photos or a video to the Telegram bot
2. **AI Processes** — Gemini analyzes the product, generates content
3. **Media Renders** — FFmpeg/Pillow creates the final polished output
4. **Admin Reviews** — Preview with caption sent to admin chat
5. **Approve** — Tap `✅ Publish Now`, `📅 Schedule`, `🔄 Regenerate`, or `❌ Discard`
6. **Published!** — Automatically uploaded to Instagram via Meta Graph API

## 🎤 TTS Voices

Default: `gu-IN-DhwaniNeural` (Gujarati female). Other options:

| Voice | Language | Code |
|-------|----------|------|
| Dhwani | Gujarati | `gu-IN-DhwaniNeural` |
| Niranjan | Gujarati | `gu-IN-NiranjanNeural` |
| Swara | Hindi | `hi-IN-SwaraNeural` |
| Madhur | Hindi | `hi-IN-MadhurNeural` |

## 📄 License

MIT
