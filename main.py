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
YT_COOKIES = os.environ.get("YT_COOKIES")

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Cookie Setup ---
if YT_COOKIES:
    with open("cookies.txt", "w") as f:
        f.write(YT_COOKIES)

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

# --- Helper Functions ---
def humanbytes(size):
    if not size: return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def time_formatter(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{minutes}m {seconds}s"

# --- PROGRESS BAR GENERATOR ---
def get_progress_text(current, total, speed, eta, status_type="Uploading"):
    percentage = current * 100 / total
    progress_str = "[{0}{1}] {2}%\n".format(
        ''.join(["■" for i in range(math.floor(percentage / 10))]),
        ''.join(["□" for i in range(10 - math.floor(percentage / 10))]),
        round(percentage, 1))
    
    return f"🚀 **{status_type}...**\n" + progress_str + \
           f"📁 {humanbytes(current)} / {humanbytes(total)}\n" + \
           f"⚡ {humanbytes(speed)}/s | ⏱ ETA: {time_formatter(eta)}"

# --- DOWNLOAD HOOK (For yt-dlp) ---
# Ye function download karte waqt message edit karega
async def download_hook(d, message, loop):
    if d['status'] == 'downloading':
        try:
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0) or 0
            eta = d.get('eta', 0) or 0
            
            # Har 5 second me update karo taaki flood wait na aaye
            now = time.time()
            if not hasattr(message, 'last_update'):
                message.last_update = 0
            
            if now - message.last_update > 5:
                text = get_progress_text(downloaded, total, speed, eta, "Downloading")
                # Asyncio run_coroutine_threadsafe use karna padega kyunki yt-dlp sync hai
                asyncio.run_coroutine_threadsafe(message.edit_text(text), loop)
                message.last_update = now
        except:
            pass

# --- UPLOAD HOOK (For Pyrogram) ---
async def upload_progress(current, total, message, start_time):
    now = time.time()
    diff = now - start_time
    if diff < 1 or total == 0: return
    
    if current % (total // 10) == 0 or current == total:
        speed = current / diff
        eta = round((total - current) / speed)
        text = get_progress_text(current, total, speed, eta, "Uploading")
        try: await message.edit_text(text)
        except: pass

# --- MAIN LOGIC ---
async def download_video(url, message):
    status_msg = await message.reply_text("🔎 **Fetching Info...**")
    
    output_path = f"downloads/{message.id}.%(ext)s"
    loop = asyncio.get_event_loop()

    # --- IOS MODE SETTINGS ---
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'quiet': True,
        'cookiefile': 'cookies.txt', # Try with cookies first
        
        # iOS Client Spoofing (Better than Android for avoiding blocks)
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'web'],
            }
        },
        # Download Progress Hook
        'progress_hooks': [lambda d: asyncio.ensure_future(download_hook(d, status_msg, loop))],
    }

    try:
        # 1. Info & Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
            
            await status_msg.edit_text(f"⬇️ **Starting Download:** `{title}`")
            
            # Actual Download
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            # Filename Logic
            filename = f"downloads/{message.id}.mp4"
            if not os.path.exists(filename):
                 for file in os.listdir("downloads"):
                     if file.startswith(str(message.id)):
                         filename = f"downloads/{file}"
                         break
            
            if not os.path.exists(filename):
                await status_msg.edit_text("❌ Download Failed.")
                return

            # 2. Upload
            await status_msg.edit_text("🚀 **Uploading to Telegram...**")
            start_time = time.time()
            
            await client.send_video(
                chat_id=message.chat.id,
                video=filename,
                caption=f"🎥 **{title}**",
                duration=duration,
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status_msg, start_time)
            )
            
            await status_msg.delete()
            os.remove(filename)

    except Exception as e:
        error_text = str(e)
        if "Sign in" in error_text or "403" in error_text:
            await status_msg.edit_text("⚠️ **Block Error:** YouTube ne IP block kar di hai.\n\n**Try this:** Render se `YT_COOKIES` delete karke dobara try karo. Public videos bina cookies ke shayad chal jayein.")
        else:
            await status_msg.edit_text(f"⚠️ **Error:** {e}")
        
        # Cleanup
        if os.path.exists(f"downloads/{message.id}.mp4"):
            os.remove(f"downloads/{message.id}.mp4")

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 **YouTube Downloader (iOS Mode)**\nLink bhejo!")

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
        
