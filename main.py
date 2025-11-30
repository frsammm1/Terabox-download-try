import os
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

# Cobalt API URL (Public Instance)
COBALT_API = "https://api.cobalt.tools/api/json"

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER (Keep Alive) ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="Bot Alive")
    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- HELPER: Cobalt API ---
async def get_stream_link(url):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    payload = {
        "url": url,
        "vCodec": "h264",
        "vQuality": "1080",
        "aFormat": "mp3",
        "filenamePattern": "basic"
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(COBALT_API, json=payload, headers=headers) as resp:
                data = await resp.json()
                
                # Check status
                if "url" in data:
                    return data["url"], None
                elif "text" in data: # Error message from API
                    return None, data["text"]
                else:
                    return None, "Unknown API Error"
        except Exception as e:
            return None, str(e)

# --- MAIN HANDLER ---
@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com|twitter\.com)\/"))
async def handle_link(client, message):
    url = message.text
    status_msg = await message.reply_text("🔄 **Bypassing Render IP...**")

    try:
        # 1. Get Direct Link from API
        stream_url, error = await get_stream_link(url)

        if not stream_url:
            await status_msg.edit_text(f"❌ **API Error:** {error}\n(Cobalt server busy ho sakta hai)")
            return

        await status_msg.edit_text("🚀 **Upload Shuru...**")

        # 2. Send to Telegram directly via URL
        # Render par download karne ki jarurat nahi, Telegram seedha URL se kheechega
        await client.send_video(
            chat_id=message.chat.id,
            video=stream_url,
            caption="🎥 Downloaded via Cobalt API",
            supports_streaming=True
        )
        
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Error:** {e}")

# --- START ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **YouTube/Insta Downloader (API Mode)**\nLink bhejo. Render IP Block fixed.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
