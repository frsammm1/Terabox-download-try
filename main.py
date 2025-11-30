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

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="Alive")
    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- SERVER LIST (Backup pe Backup) ---
# Agar main server fail ho, to ye try honge
COBALT_INSTANCES = [
    "https://cobalt.xy24.eu/api/json",
    "https://cobalt.kwiatekmiki.pl/api/json",
    "https://dl.khub.clan.hu/api/json",
    "https://cobalt.mccloud.to/api/json",
    "https://api.cobalt.tools/api/json" # Official (Last priority)
]

# --- API LOGIC (Server Rotation) ---
async def get_stream_link(url):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
    }
    
    payload = {
        "url": url,
        "vCodec": "h264",
        "vQuality": "1080",
        "filenamePattern": "basic"
    }

    async with aiohttp.ClientSession() as session:
        # Har server ko try karo
        for base_url in COBALT_INSTANCES:
            try:
                print(f"Trying Server: {base_url}")
                async with session.post(base_url, json=payload, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        continue # Agla server try karo
                    
                    data = await resp.json()
                    
                    # Agar link mil gaya to return karo
                    if "url" in data:
                        return data["url"], None
                    
                    # Agar error text mila
                    if "text" in data:
                        print(f"Server Error: {data['text']}")
                        continue # Agla try karo

            except Exception as e:
                print(f"Connection Error: {e}")
                continue # Agla try karo

    return None, "All servers are busy or down."

# --- MAIN HANDLER ---
@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be|instagram\.com|twitter\.com)\/"))
async def handle_link(client, message):
    url = message.text
    # Status message bhejo
    status_msg = await message.reply_text("🔄 **Processing via Cloud API...**")

    try:
        # 1. API se Link nikalo
        stream_url, error = await get_stream_link(url)

        if not stream_url:
            await status_msg.edit_text(f"❌ **Failed:** {error}\n(Sabhi free servers busy hain, thodi der baad try karna)")
            return

        await status_msg.edit_text("🚀 **Uploading...**")

        # 2. Telegram ko bolo link se file kheench le
        # Isse Render ki bandwidth use nahi hoti
        await client.send_video(
            chat_id=message.chat.id,
            video=stream_url,
            caption="🎥 **Downloaded via Cobalt**",
            supports_streaming=True
        )
        
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Error:** {e}")

# --- START ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **Multi-Server Downloader**\nMain 5 alag-alag servers try karta hu taaki download fail na ho.\nLink bhejo!")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
    
