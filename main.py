import os
import re
import time
import math
import io
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message
from TeraboxDL import TeraboxDL

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE")
PORT = int(os.environ.get("PORT", 8080))

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
    units = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {units[n]}B"

async def progress_bar(current, total, msg, start, uid):
    if stop_dict.get(uid, False):
        raise Exception("Cancelled by user")
        
    now = time.time()
    diff = now - start
    if diff < 2 or total == 0: 
        return
    
    if current % max(1, (total // 20)) == 0 or current == total:
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

# --- SIMPLE ASYNC FILE WRAPPER ---
class AsyncFileWrapper:
    """Dead simple async file wrapper for Pyrogram"""
    
    def __init__(self, url, filename, cookie):
        self.url = url
        self.name = filename
        self.cookie = cookie
        self.session = None
        self.response = None
        self.size = 0
        self.downloaded = 0
        self.mode = 'rb'
        
    async def setup(self):
        """Setup connection"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': self.cookie,
            'Referer': 'https://www.terabox.com/',
        }
        
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
        
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=aiohttp.TCPConnector(ssl=False)
        )
        
        self.response = await self.session.get(self.url, headers=headers)
        
        if self.response.status != 200:
            raise Exception(f"HTTP {self.response.status}")
        
        self.size = int(self.response.headers.get('Content-Length', 0))
        
        # Test read
        test = await asyncio.wait_for(self.response.content.read(1024), timeout=10)
        if not test:
            raise Exception("No data received")
        
        # Put back test data
        self.buffer = test
        self.downloaded = len(test)
        
        return self
    
    def read(self, size=-1):
        """Sync read for Pyrogram"""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self._read_async(size))
    
    async def _read_async(self, size=-1):
        """Actual async read"""
        # Return buffered first
        if hasattr(self, 'buffer') and self.buffer:
            data = self.buffer
            delattr(self, 'buffer')
            return data
        
        if not self.response:
            return b""
        
        try:
            chunk = await asyncio.wait_for(
                self.response.content.read(size if size > 0 else 524288),
                timeout=30
            )
            
            if chunk:
                self.downloaded += len(chunk)
            
            return chunk
            
        except Exception:
            return b""
    
    async def cleanup(self):
        """Close everything"""
        if self.response:
            self.response.close()
        if self.session:
            await self.session.close()
    
    def __len__(self):
        return max(self.size, 10 * 1024 * 1024)

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
    
    status = await message.reply_text("🔍 **Step 1:** Extracting link...")
    
    try:
        # Step 1: Get direct link
        direct, filename = await get_direct_link(url)
        
        if not direct:
            await status.edit_text(
                "❌ **Failed at Step 1**\n\n"
                "**Could not extract download link**\n\n"
                "Reasons:\n"
                "• Invalid Terabox URL\n"
                "• Expired/wrong cookie\n"
                "• File deleted/private\n\n"
                "Check your TERABOX_COOKIE in env"
            )
            return
        
        await status.edit_text(
            f"✅ **Step 1:** Done\n📄 {filename}\n\n"
            f"🔗 **Step 2:** Testing connection..."
        )
        
        # Step 2: Test connection
        file_wrapper = AsyncFileWrapper(direct, filename, TERABOX_COOKIE)
        
        try:
            await file_wrapper.setup()
            
            size_info = humanbytes(file_wrapper.size) if file_wrapper.size > 0 else "Unknown"
            
            await status.edit_text(
                f"✅ **Step 2:** Connected!\n"
                f"📦 Size: {size_info}\n\n"
                f"📤 **Step 3:** Uploading to Telegram..."
            )
            
        except Exception as conn_err:
            await file_wrapper.cleanup()
            await status.edit_text(
                f"❌ **Failed at Step 2**\n\n"
                f"**Connection test failed**\n\n"
                f"Error: `{str(conn_err)}`\n\n"
                f"Reasons:\n"
                f"• Terabox blocking server IP\n"
                f"• Network timeout\n"
                f"• Invalid direct link"
            )
            return
        
        # Step 3: Upload
        start = time.time()
        
        try:
            # Try video first
            await client.send_video(
                chat_id=message.chat.id,
                video=file_wrapper,
                caption=f"🎬 {filename}",
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status, start, uid)
            )
            
        except Exception as upload_err:
            # Retry as document
            await status.edit_text("⚠️ Video failed, trying document...")
            
            # Need fresh wrapper
            await file_wrapper.cleanup()
            file_wrapper = AsyncFileWrapper(direct, filename, TERABOX_COOKIE)
            await file_wrapper.setup()
            
            await client.send_document(
                chat_id=message.chat.id,
                document=file_wrapper,
                caption=f"📁 {filename}",
                progress=progress_bar,
                progress_args=(status, start, uid)
            )
        
        await file_wrapper.cleanup()
        await status.delete()
        await message.reply_text("✅ **Upload complete!**")
        
    except Exception as e:
        error_msg = str(e)
        
        await status.edit_text(
            f"❌ **Error occurred**\n\n"
            f"```python\n{error_msg[:400]}```\n\n"
            f"**Debug info:**\n"
            f"• Cookie valid? Check env\n"
            f"• File size? Maybe too large\n"
            f"• Network? Render might be blocked"
        )
    
    finally:
        stop_dict[uid] = False

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "🚀 **Terabox Downloader (Debug Mode)**\n\n"
        "This bot shows detailed steps for debugging.\n\n"
        "Send a Terabox link to test!\n\n"
        "**Important:**\n"
        "• Make sure TERABOX_COOKIE is set\n"
        "• Link must be valid and public\n"
        "• Large files may fail on free tier\n\n"
        "/stop - Cancel download"
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
            await message.reply_text("Already processing! Wait or /stop")
            return
        
        await process_link(client, message, tera[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    print("Bot started - Debug mode active")
    app.run()
