import os
import re
import time
import math
import io
import socket
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from TeraboxDL import TeraboxDL

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE") 
PORT = int(os.environ.get("PORT", 8080))
TG_SPLIT_LIMIT = 2000 * 1024 * 1024  

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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
    if not size: return "Unknown"
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

async def progress_bar(current, total, message, start_time):
    now = time.time()
    diff = now - start_time
    if diff < 1 or total == 0: return 
    
    if current % (total // 20) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        def time_fmt(ms):
            s, ms = divmod(int(ms), 1000)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{m}m {s}s"
            
        progress = "[{0}{1}] {2}%\n".format(
            ''.join(["■" for i in range(math.floor(percentage / 10))]),
            ''.join(["□" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 1))
        
        tmp = progress + f"📁 {humanbytes(current)} / {humanbytes(total)}\n🚀 {humanbytes(speed)}/s\n⏱ ETA: {time_fmt(time_to_completion)}"
        try: await message.edit_text(text=f"{tmp}")
        except: pass

# --- STREAMING CLASS (Direct Start) ---
class URLFile(io.BytesIO): 
    def __init__(self, session, url, filename, headers):
        self.session = session
        self.url = url
        self.filename = filename
        self.headers = headers
        self.name = filename
        self.current_byte = 0
        self.total_size = 0 # Will be set after connection
        self.response = None
        self.mode = 'rb' 

    async def __aenter__(self):
        # Timeout settings: Connect fast (10s), but wait long for data (60s)
        timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=60)
        
        # SSL False, IPv4 Forced (via session connector)
        self.response = await self.session.get(self.url, headers=self.headers, timeout=timeout, ssl=False)
        
        # Get size from actual download response (No separate HEAD request)
        self.total_size = int(self.response.headers.get('Content-Length', 0))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.response: self.response.close()

    async def read(self, chunk_size):
        if self.response:
            if self.current_byte >= TG_SPLIT_LIMIT: return b""
            try:
                data = await self.response.content.read(chunk_size)
                if not data: return b""
                self.current_byte += len(data)
                return data
            except: return b""
        return b""

    def __len__(self):
        return self.total_size if self.total_size > 0 else 10*1024*1024 # Fake size if unknown

# --- DIRECT LINK ---
async def get_direct_link(terabox_url):
    try:
        clean_url = re.sub(r"https?://[a-zA-Z0-9.-]+", "https://www.terabox.com", terabox_url)
        client = TeraboxDL(TERABOX_COOKIE)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: client.get_file_info(clean_url))
        
        if not result: return None
        
        file_info = result[0] if isinstance(result, list) else result
        return file_info.get('dlink') or file_info.get('download_link') or file_info.get('url')
    except: return None

# --- PROCESSOR ---
async def process_single_link(client, message, terabox_url):
    status_msg = await message.reply_text(f"⏳ **Connecting...**\n`{terabox_url}`")
    
    try:
        direct_url = await get_direct_link(terabox_url)
        if not direct_url:
            await status_msg.edit_text("❌ Link Extract Failed.")
            return

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Cookie': TERABOX_COOKIE,
            'Referer': 'https://www.terabox.com/' 
        }

        # Force IPv4 connection
        connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            start_time = time.time()
            
            # Note: Hum size check nahi kar rahe, seedha stream class call kar rahe hain
            async with URLFile(session, direct_url, "video.mp4", headers) as stream_file:
                
                # Agar connection ban gaya to edit msg
                await status_msg.edit_text("🚀 **Streaming Started...**")
                
                try:
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=stream_file,
                        caption="🎥 Video from Terabox",
                        supports_streaming=True,
                        progress=progress_bar,
                        progress_args=(status_msg, start_time)
                    )
                except Exception as upload_error:
                    # Agar Video fail hui to Document try karo
                    await status_msg.edit_text("⚠️ Video mode failed, sending as File...")
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=stream_file,
                        caption="📁 File from Terabox",
                        progress=progress_bar,
                        progress_args=(status_msg, start_time)
                    )
            
            await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Failed:** {e}")

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("👋 Ready! Link bhejo.")

@app.on_message(filters.text & filters.regex(r"terabox|1024tera|momerybox|teraboxapp"))
async def handle_message(client, message):
    text = message.text
    urls = re.findall(r'(https?://[^\s]+)', text)
    tera_urls = [url for url in urls if any(x in url for x in ['terabox', '1024tera', 'momerybox', 'teraboxapp'])]
    
    if tera_urls:
        await process_single_link(client, message, tera_urls[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
        
