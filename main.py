import os
import time
import math
import asyncio
import yt_dlp
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER (Keep Alive) ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="YT Bot Alive")
    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- Helpers ---
def humanbytes(size):
    if not size: return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{minutes}m {seconds}s"

async def progress_bar(current, total, message, start_time):
    now = time.time()
    diff = now - start_time
    if diff < 1 or total == 0: return
    
    if current % (total // 10) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        progress = "[{0}{1}] {2}%\n".format(
            ''.join(["■" for i in range(math.floor(percentage / 10))]),
            ''.join(["□" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 1))
        
        tmp = progress + f"📁 {humanbytes(current)} / {humanbytes(total)}\n🚀 {humanbytes(speed)}/s\n⏱ ETA: {time_formatter(time_to_completion)}"
        try: await message.edit_text(tmp)
        except: pass

# --- DOWNLOAD LOGIC ---
async def download_video(url, message):
    status_msg = await message.reply_text("🔎 **Fetching Info...**")
    
    # Output filename template
    output_path = f"downloads/{message.id}.%(ext)s"
    
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. Info Extract
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
            
            await status_msg.edit_text(f"⬇️ **Downloading:** `{title}`")
            
            # 2. Download
            # Note: yt-dlp sync chalta hai, isliye executor me run karenge taki bot na ruke
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            # Find the file (extension can vary)
            filename = f"downloads/{message.id}.mp4"
            if not os.path.exists(filename):
                 # Fallback check agar mkv ya webm me aaya
                 for file in os.listdir("downloads"):
                     if file.startswith(str(message.id)):
                         filename = f"downloads/{file}"
                         break
            
            if not os.path.exists(filename):
                await status_msg.edit_text("❌ Download Failed (File not found).")
                return

            # 3. Upload
            await status_msg.edit_text("🚀 **Uploading...**")
            start_time = time.time()
            
            await client.send_video(
                chat_id=message.chat.id,
                video=filename,
                caption=f"🎥 **{title}**",
                duration=duration,
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status_msg, start_time)
            )
            
            await status_msg.delete()
            
            # 4. Cleanup
            os.remove(filename)

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Error:** {e}")
        # Cleanup if failed
        if os.path.exists(f"downloads/{message.id}.mp4"):
            os.remove(f"downloads/{message.id}.mp4")

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **YouTube Downloader Ready!**\nLink bhejo (Shorts/Video).")

@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?([a-zA-Z0-9_-]+)"))
async def handle_yt(client, message):
    url = message.text
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    await download_video(url, message)

if __name__ == "__main__":
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
        
