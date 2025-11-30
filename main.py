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

# Memory management
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for better memory handling

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

def time_formatter(seconds):
    """Convert seconds to human readable format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"

async def download_progress(current, total, msg, start, uid, phase="Downloading"):
    """Progress bar for download phase"""
    if stop_dict.get(uid, False):
        raise Exception("Cancelled")
    
    now = time.time()
    diff = now - start
    
    # Update every 1.5 seconds
    if diff < 1.5:
        return
    
    percent = (current * 100) / total if total > 0 else 0
    speed = current / diff if diff > 0 else 0
    eta = int((total - current) / speed) if speed > 0 else 0
    
    # Progress bar
    filled = int(percent / 5)
    bar = '█' * filled + '░' * (20 - filled)
    
    status = f"**{phase}:** `{round(percent, 1)}%`\n"
    status += f"[{bar}]\n\n"
    status += f"**Downloaded:** {humanbytes(current)} / {humanbytes(total)}\n"
    status += f"**Speed:** {humanbytes(speed)}/s\n"
    status += f"**ETA:** {time_formatter(eta)}\n"
    status += f"**Elapsed:** {time_formatter(diff)}\n\n"
    status += "💡 /stop to cancel"
    
    try:
        await msg.edit_text(status)
    except:
        pass

async def upload_progress(current, total, msg, start, uid):
    """Progress bar for upload phase"""
    if stop_dict.get(uid, False):
        raise Exception("Cancelled")
    
    now = time.time()
    diff = now - start
    
    if diff < 1.5:
        return
    
    percent = (current * 100) / total if total > 0 else 0
    speed = current / diff if diff > 0 else 0
    eta = int((total - current) / speed) if speed > 0 else 0
    
    filled = int(percent / 5)
    bar = '█' * filled + '░' * (20 - filled)
    
    status = f"**Uploading to Telegram:** `{round(percent, 1)}%`\n"
    status += f"[{bar}]\n\n"
    status += f"**Uploaded:** {humanbytes(current)} / {humanbytes(total)}\n"
    status += f"**Speed:** {humanbytes(speed)}/s\n"
    status += f"**ETA:** {time_formatter(eta)}\n"
    status += f"**Elapsed:** {time_formatter(diff)}\n\n"
    status += "💡 /stop to cancel"
    
    try:
        await msg.edit_text(status)
    except:
        pass

async def download_file(url, filepath, cookie, status_msg, uid):
    """Optimized download with chunked streaming"""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
        'Cookie': cookie,
        'Referer': 'https://www.terabox.com/',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive'
    }
    
    # Aggressive timeout for large files
    timeout = aiohttp.ClientTimeout(
        total=None,  # No total timeout
        connect=30,
        sock_read=120  # 2 minutes read timeout
    )
    
    connector = aiohttp.TCPConnector(
        ssl=False,
        limit=5,
        force_close=False,  # Keep connection alive
        enable_cleanup_closed=True
    )
    
    downloaded = 0
    start_time = time.time()
    last_update = start_time
    
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(url, headers=headers) as response:
            
            if response.status != 200:
                raise Exception(f"HTTP {response.status} - Server rejected request")
            
            total_size = int(response.headers.get('Content-Length', 0))
            
            if total_size == 0:
                raise Exception("Content-Length is 0 - Terabox blocked the IP/request")
            
            if total_size > MAX_FILE_SIZE:
                raise Exception(f"File too large: {humanbytes(total_size)} (Max: 2GB)")
            
            # Initial status
            await status_msg.edit_text(
                f"📥 **Starting download...**\n\n"
                f"**Size:** {humanbytes(total_size)}\n"
                f"**File:** `{filepath.name}`"
            )
            
            # Download with chunked writing
            with open(filepath, 'wb') as f:
                async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                    
                    if stop_dict.get(uid, False):
                        raise Exception("Download cancelled by user")
                    
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 1.5 seconds OR every 10MB
                    now = time.time()
                    if (now - last_update >= 1.5) or (downloaded % (10 * 1024 * 1024) < CHUNK_SIZE):
                        await download_progress(downloaded, total_size, status_msg, start_time, uid, "📥 Downloading")
                        last_update = now
            
            # Final progress
            await download_progress(downloaded, total_size, status_msg, start_time, uid, "📥 Download Complete")
            
            return total_size

async def get_direct_link(url):
    """Extract direct download link from Terabox"""
    try:
        # Normalize URL
        clean = re.sub(r"https?://[a-zA-Z0-9.-]+", "https://www.terabox.com", url)
        
        dl = TeraboxDL(TERABOX_COOKIE)
        loop = asyncio.get_event_loop()
        
        # Run in executor to avoid blocking
        result = await loop.run_in_executor(
            None,
            lambda: dl.get_file_info(clean)
        )
        
        if not result:
            return None, None, None
        
        info = result[0] if isinstance(result, list) else result
        
        link = info.get('dlink') or info.get('download_link') or info.get('url')
        filename = info.get('server_filename', 'video.mp4')
        filesize = info.get('size', 0)
        
        return link, filename, filesize
        
    except Exception as e:
        return None, None, None

async def process_link(client: Client, message: Message, url: str):
    """Main processing pipeline"""
    
    uid = message.from_user.id
    stop_dict[uid] = False
    filepath = None
    
    status = await message.reply_text(
        "🔍 **Step 1/4:** Extracting download link...\n\n"
        "⏳ Please wait..."
    )
    
    try:
        # Step 1: Extract direct link
        direct, filename, filesize = await get_direct_link(url)
        
        if not direct:
            await status.edit_text(
                "❌ **Step 1 Failed!**\n\n"
                "**Could not extract download link**\n\n"
                "**Possible reasons:**\n"
                "• Invalid/expired Terabox URL\n"
                "• TERABOX_COOKIE expired or wrong\n"
                "• File is private or deleted\n"
                "• Terabox API changed\n\n"
                "**Fix:** Update TERABOX_COOKIE in environment"
            )
            return
        
        size_text = humanbytes(filesize) if filesize > 0 else "Unknown"
        
        await status.edit_text(
            f"✅ **Step 1:** Link extracted!\n\n"
            f"**📄 File:** `{filename}`\n"
            f"**📦 Size:** {size_text}\n\n"
            f"📥 **Step 2/4:** Downloading to server..."
        )
        
        # Step 2: Download file
        filepath = DOWNLOAD_DIR / f"{uid}_{int(time.time())}_{filename}"
        
        try:
            downloaded_size = await download_file(direct, filepath, TERABOX_COOKIE, status, uid)
            
            await status.edit_text(
                f"✅ **Step 2:** Downloaded {humanbytes(downloaded_size)}\n\n"
                f"📤 **Step 3/4:** Uploading to Telegram...\n\n"
                f"⏳ Starting upload..."
            )
            
        except Exception as dl_err:
            error_text = str(dl_err)
            
            await status.edit_text(
                f"❌ **Step 2 Failed!**\n\n"
                f"**Download error:** `{error_text[:250]}`\n\n"
                f"**Common reasons:**\n"
                f"• Terabox blocked Render's IP\n"
                f"• Connection timeout\n"
                f"• File too large for bandwidth\n"
                f"• Network instability\n\n"
                f"**Note:** Free tier has limited resources"
            )
            return
        
        # Step 3: Upload to Telegram
        upload_start = time.time()
        
        # Check file exists and has content
        if not filepath.exists() or filepath.stat().st_size == 0:
            await status.edit_text("❌ **Downloaded file is empty or missing!**")
            return
        
        try:
            # Try as video first (better for media files)
            await client.send_video(
                chat_id=message.chat.id,
                video=str(filepath),
                caption=f"🎬 **{filename}**\n\n📦 Size: {humanbytes(downloaded_size)}\n⚡ Downloaded from Terabox",
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status, upload_start, uid)
            )
            
        except Exception as vid_err:
            # Fallback: Send as document
            await status.edit_text(
                "⚠️ Video upload failed, sending as document...\n\n"
                "This is normal for non-video files."
            )
            
            await client.send_document(
                chat_id=message.chat.id,
                document=str(filepath),
                caption=f"📁 **{filename}**\n\n📦 Size: {humanbytes(downloaded_size)}",
                progress=upload_progress,
                progress_args=(status, upload_start, uid)
            )
        
        # Step 4: Cleanup
        await status.edit_text("🧹 **Step 4/4:** Cleaning up server storage...")
        
        if filepath and filepath.exists():
            filepath.unlink()
            
        await asyncio.sleep(1)
        await status.delete()
        
        # Success message
        total_time = time.time() - upload_start
        await message.reply_text(
            f"✅ **Upload Complete!** 🎉\n\n"
            f"**File:** {filename}\n"
            f"**Size:** {humanbytes(downloaded_size)}\n"
            f"**Time:** {time_formatter(total_time)}"
        )
        
    except Exception as e:
        error = str(e)
        
        if "cancel" in error.lower():
            await status.edit_text("🛑 **Cancelled by user**")
        else:
            await status.edit_text(
                f"❌ **Unexpected Error**\n\n"
                f"```\n{error[:350]}\n```\n\n"
                f"Try again or contact support."
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
        "🚀 **Terabox Downloader Pro**\n\n"
        "**✨ Features:**\n"
        "• Download files up to 2GB\n"
        "• Real-time progress tracking\n"
        "• Speed & ETA display\n"
        "• Auto cleanup after upload\n\n"
        "**📥 How to use:**\n"
        "1. Send any Terabox link\n"
        "2. Bot downloads to server\n"
        "3. Bot uploads to Telegram\n"
        "4. File sent to you!\n\n"
        "**⚠️ Limitations:**\n"
        "• Free tier: 512MB RAM, limited bandwidth\n"
        "• Some IPs blocked by Terabox\n"
        "• Large files may take time\n\n"
        "**Commands:**\n"
        "/start - Show this info\n"
        "/stop - Cancel active download\n\n"
        "**Supported:** terabox.com, 1024tera.com, momerybox.com, teraboxapp.com"
    )

@app.on_message(filters.command("stop"))
async def stop_cmd(client, message):
    uid = message.from_user.id
    
    if uid in stop_dict and not stop_dict[uid]:
        stop_dict[uid] = True
        await message.reply_text(
            "🛑 **Stopping download...**\n\n"
            "Please wait while cleanup happens."
        )
    else:
        await message.reply_text("ℹ️ No active download to stop")

@app.on_message(filters.text & filters.regex(r"terabox|1024tera|momerybox|teraboxapp"))
async def handle_url(client, message):
    urls = re.findall(r'(https?://[^\s]+)', message.text)
    tera = [u for u in urls if any(x in u for x in ['terabox', '1024tera', 'momerybox', 'teraboxapp'])]
    
    if tera:
        uid = message.from_user.id
        
        # Check if already processing
        if uid in stop_dict and not stop_dict[uid]:
            await message.reply_text(
                "⚠️ **Already processing a file!**\n\n"
                "Please wait for current download to finish or use /stop to cancel it."
            )
            return
        
        await process_link(client, message, tera[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    print("🚀 Terabox Downloader Pro - Started!")
    print(f"📁 Download directory: {DOWNLOAD_DIR.absolute()}")
    print(f"💾 Max file size: {humanbytes(MAX_FILE_SIZE)}")
    app.run()
