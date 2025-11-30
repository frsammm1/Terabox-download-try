import os
import re
import time
import math
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message
from TeraboxDL import TeraboxDL
from pathlib import Path

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE")
PORT = int(os.environ.get("PORT", 8080))
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
stop_dict = {}

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

def humanbytes(size):
    if not size: return "0 B"
    power = 2**10
    n = 0
    units = {0: '', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power and n < 4:
        size /= power
        n += 1
    return f"{round(size, 2)} {units[n]}B"

async def progress_bar(current, total, msg, start, uid):
    if stop_dict.get(uid, False):
        raise Exception("Cancelled")
        
    now = time.time()
    diff = now - start
    if diff < 2 or total == 0: 
        return
    
    percent = (current * 100) / total
    speed = current / diff
    eta = round((total - current) / speed) if speed > 0 else 0
    
    bar_len = math.floor(percent / 5)
    bar = '█' * bar_len + '░' * (20 - bar_len)
    
    text = f"**{round(percent, 1)}%**\n[{bar}]\n\n"
    text += f"📦 {humanbytes(current)} / {humanbytes(total)}\n"
    text += f"⚡ {humanbytes(speed)}/s | ⏱ {eta}s left"
    
    try:
        await msg.edit_text(text)
    except:
        pass

# --- DOWNLOAD FILE ---
async def download_file(url, filepath, cookie, status_msg, uid):
    """Download file to disk first"""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Cookie': cookie,
        'Referer': 'https://www.terabox.com/',
    }
    
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(url, headers=headers) as response:
            
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            
            total_size = int(response.headers.get('Content-Length', 0))
            
            if total_size == 0:
                raise Exception("Content-Length is 0 - Server blocked request")
            
            downloaded = 0
            start_time = time.time()
            
            with open(filepath, 'wb') as f:
                async for chunk in response.content.iter_chunked(524288):  # 512KB chunks
                    
                    if stop_dict.get(uid, False):
                        raise Exception("Cancelled by user")
                    
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 2%
                    if downloaded % (total_size // 50) == 0 or downloaded == total_size:
                        now = time.time()
                        diff = now - start_time
                        
                        if diff > 2:
                            percent = (downloaded * 100) / total_size
                            speed = downloaded / diff
                            eta = round((total_size - downloaded) / speed) if speed > 0 else 0
                            
                            bar_len = math.floor(percent / 5)
                            bar = '█' * bar_len + '░' * (20 - bar_len)
                            
                            text = f"**Downloading: {round(percent, 1)}%**\n[{bar}]\n\n"
                            text += f"📥 {humanbytes(downloaded)} / {humanbytes(total_size)}\n"
                            text += f"⚡ {humanbytes(speed)}/s | ⏱ {eta}s"
                            
                            try:
                                await status_msg.edit_text(text)
                            except:
                                pass
            
            return total_size

# --- GET DIRECT LINK ---
async def get_direct_link(url):
    try:
        clean = re.sub(r"https?://[a-zA-Z0-9.-]+", "https://www.terabox.com", url)
        
        dl = TeraboxDL(TERABOX_COOKIE)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: dl.get_file_info(clean))
        
        if not result:
            return None, None
        
        info = result[0] if isinstance(result, list) else result
        link = info.get('dlink') or info.get('download_link') or info.get('url')
        name = info.get('server_filename', 'video.mp4')
        
        return link, name
        
    except Exception as e:
        return None, None

# --- MAIN PROCESS ---
async def process_link(client: Client, message: Message, url: str):
    uid = message.from_user.id
    stop_dict[uid] = False
    
    status = await message.reply_text("🔍 **Step 1/4:** Extracting link...")
    filepath = None
    
    try:
        # Step 1: Extract direct link
        direct, filename = await get_direct_link(url)
        
        if not direct:
            await status.edit_text(
                "❌ **Step 1 Failed: Link extraction**\n\n"
                "**Reasons:**\n"
                "• Invalid/expired Terabox URL\n"
                "• TERABOX_COOKIE is wrong/expired\n"
                "• File is private or deleted\n\n"
                "**Fix:** Update cookie in environment variables"
            )
            return
        
        await status.edit_text(
            f"✅ **Step 1:** Link extracted\n"
            f"📄 `{filename}`\n\n"
            f"📥 **Step 2/4:** Downloading to server..."
        )
        
        # Step 2: Download file to disk
        filepath = DOWNLOAD_DIR / f"{uid}_{int(time.time())}_{filename}"
        
        try:
            file_size = await download_file(direct, filepath, TERABOX_COOKIE, status, uid)
            
            await status.edit_text(
                f"✅ **Step 2:** Downloaded {humanbytes(file_size)}\n\n"
                f"📤 **Step 3/4:** Uploading to Telegram..."
            )
            
        except Exception as dl_err:
            await status.edit_text(
                f"❌ **Step 2 Failed: Download**\n\n"
                f"**Error:** `{str(dl_err)[:300]}`\n\n"
                f"**Reasons:**\n"
                f"• Render IP blocked by Terabox\n"
                f"• Connection timeout\n"
                f"• File too large for free tier\n\n"
                f"**Note:** Render free tier has limited bandwidth & IPs often blocked"
            )
            return
        
        # Step 3: Upload to Telegram
        start_upload = time.time()
        
        try:
            # Try as video first
            await client.send_video(
                chat_id=message.chat.id,
                video=str(filepath),
                caption=f"🎬 {filename}\n\n📦 Size: {humanbytes(file_size)}",
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status, start_upload, uid)
            )
            
        except Exception:
            # Fallback to document
            await status.edit_text("⚠️ Video upload failed, trying as document...")
            
            await client.send_document(
                chat_id=message.chat.id,
                document=str(filepath),
                caption=f"📁 {filename}\n\n📦 Size: {humanbytes(file_size)}",
                progress=progress_bar,
                progress_args=(status, start_upload, uid)
            )
        
        # Step 4: Cleanup
        await status.edit_text("🧹 **Step 4/4:** Cleaning up...")
        
        if filepath and filepath.exists():
            filepath.unlink()
        
        await status.delete()
        await message.reply_text("✅ **Complete!** 🎉")
        
    except Exception as e:
        error = str(e)
        
        if "cancel" in error.lower():
            await status.edit_text("🛑 **Cancelled by user**")
        else:
            await status.edit_text(
                f"❌ **Unexpected error**\n\n"
                f"```python\n{error[:400]}```"
            )
    
    finally:
        # Always cleanup
        stop_dict[uid] = False
        if filepath and filepath.exists():
            try:
                filepath.unlink()
            except:
                pass

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🚀 **Terabox Downloader**\n\n"
        "**Method:** Download → Upload\n"
        "**Why:** Pyrogram doesn't accept custom async streams\n\n"
        "**Process:**\n"
        "1️⃣ Extract direct link from Terabox\n"
        "2️⃣ Download file to Render server\n"
        "3️⃣ Upload to Telegram\n"
        "4️⃣ Delete from server\n\n"
        "**Limitations:**\n"
        "• Free tier: Limited storage & bandwidth\n"
        "• Terabox often blocks Render IPs\n"
        "• Large files may fail\n\n"
        "Send a Terabox link to start!"
    )

@app.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    uid = message.from_user.id
    if uid in stop_dict and not stop_dict[uid]:
        stop_dict[uid] = True
        await message.reply_text("🛑 Stopping...")
    else:
        await message.reply_text("No active download")

@app.on_message(filters.text & filters.regex(r"terabox|1024tera|momerybox|teraboxapp"))
async def handle_url(client, message):
    urls = re.findall(r'(https?://[^\s]+)', message.text)
    tera = [u for u in urls if any(x in u for x in ['terabox', '1024tera', 'momerybox', 'teraboxapp'])]
    
    if tera:
        uid = message.from_user.id
        if uid in stop_dict and not stop_dict[uid]:
            await message.reply_text("⚠️ Already processing! Wait or /stop")
            return
        
        await process_link(client, message, tera[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    print("Bot started - Download-first mode")
    app.run()
