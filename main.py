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
from pyrogram.types import Message
from TeraboxDL import TeraboxDL
import random

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE")
PORT = int(os.environ.get("PORT", 8080))
TG_SPLIT_LIMIT = 2000 * 1024 * 1024

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
stop_dict = {}

# FREE PROXY SERVICES
PROXY_SERVICES = [
    "https://api.allorigins.win/raw?url=",
    "https://corsproxy.io/?",
    "https://api.codetabs.com/v1/proxy?quest=",
]

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

async def progress_bar(current, total, message, start_time, user_id):
    if stop_dict.get(user_id, False):
        raise Exception("User cancelled")
        
    now = time.time()
    diff = now - start_time
    if diff < 1.5 or total == 0: return
    
    if current % max(1, (total // 25)) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        eta = round((total - current) / speed) if speed > 0 else 0
        
        def time_fmt(s):
            m, s = divmod(int(s), 60)
            h, m = divmod(m, 60)
            return f"{h}h {m}m" if h > 0 else f"{m}m {s}s"
            
        bar = ''.join(["█" for i in range(math.floor(percentage / 5))]) + ''.join(["░" for i in range(20 - math.floor(percentage / 5))])
        
        tmp = f"**Uploading:** {round(percentage, 1)}%\n[{bar}]\n\n"
        tmp += f"📦 {humanbytes(current)} / {humanbytes(total)}\n"
        tmp += f"⚡ {humanbytes(speed)}/s | ⏱ {time_fmt(eta)}\n\n"
        tmp += "/stop to cancel"
        
        try:
            await message.edit_text(tmp)
        except: 
            pass

# --- PROPER FILE STREAM CLASS (BytesIO BASE) ---
class ProxyStream(io.BytesIO):
    """Pyrogram-compatible streaming class with proxy support"""
    
    def __init__(self, session, url, filename, headers, user_id):
        super().__init__()
        self.session = session
        self.original_url = url
        self.filename = filename
        self.headers = headers
        self.user_id = user_id
        self.name = filename
        self.mode = 'rb'
        
        self.current_byte = 0
        self.total_size = 0
        self.response = None
        self.failed_proxies = set()
        self.using_proxy = False
        self._closed = False
        
    async def initialize(self):
        """Connection setup - proxy first, then direct"""
        
        # Try proxy first
        success = await self._try_proxy_connection()
        
        if not success:
            # Fallback to direct
            await self._try_direct_connection()
            
        return self
    
    async def _try_proxy_connection(self):
        """Try connecting via free proxies"""
        available = [p for p in PROXY_SERVICES if p not in self.failed_proxies]
        
        for proxy_url in available:
            try:
                proxied = f"{proxy_url}{self.original_url}"
                
                timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=45)
                
                self.response = await self.session.get(
                    proxied,
                    headers={'User-Agent': self.headers['User-Agent']},
                    timeout=timeout,
                    allow_redirects=True
                )
                
                if self.response.status == 200:
                    # Test actual data flow
                    test = await asyncio.wait_for(
                        self.response.content.read(16384),
                        timeout=12
                    )
                    
                    if test:
                        self.total_size = int(self.response.headers.get('Content-Length', 0))
                        if self.total_size == 0:
                            # Estimate from test chunk
                            self.total_size = 200 * 1024 * 1024
                        
                        # Write test data to buffer
                        super().write(test)
                        super().seek(0)
                        self.current_byte = len(test)
                        self.using_proxy = True
                        return True
                        
            except Exception:
                self.failed_proxies.add(proxy_url)
                if self.response:
                    self.response.close()
                continue
                
        return False
    
    async def _try_direct_connection(self):
        """Direct connection without proxy"""
        timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=50)
        
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            ssl=False,
            limit=10
        )
        
        for attempt in range(3):
            try:
                # Rotate User-Agent
                headers = self.headers.copy()
                headers['User-Agent'] = random.choice([
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36',
                    'Mozilla/5.0 (X11; Linux x86_64) Firefox/122.0'
                ])
                
                self.response = await self.session.get(
                    self.original_url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True
                )
                
                if self.response.status == 200:
                    test = await asyncio.wait_for(
                        self.response.content.read(16384),
                        timeout=10
                    )
                    
                    if test:
                        self.total_size = int(self.response.headers.get('Content-Length', 0))
                        if self.total_size == 0:
                            self.total_size = 200 * 1024 * 1024
                        
                        super().write(test)
                        super().seek(0)
                        self.current_byte = len(test)
                        return
                        
            except Exception as e:
                if attempt == 2:
                    raise Exception(f"Connection failed: {str(e)}")
                await asyncio.sleep(2 * (attempt + 1))
    
    async def read_async(self, size=-1):
        """Async read method"""
        if stop_dict.get(self.user_id, False):
            return b""
            
        if self.current_byte >= TG_SPLIT_LIMIT:
            return b""
        
        # First check if BytesIO buffer has data
        buffered = super().read(size if size > 0 else -1)
        if buffered:
            return buffered
        
        # Read from network
        if not self.response:
            return b""
        
        try:
            chunk = await asyncio.wait_for(
                self.response.content.read(size if size > 0 else 1048576),
                timeout=40
            )
            
            if chunk:
                self.current_byte += len(chunk)
                # Write to internal buffer
                pos = super().tell()
                super().write(chunk)
                super().seek(pos)
                return chunk
                
            return b""
            
        except asyncio.TimeoutError:
            return b""
        except Exception:
            return b""
    
    def read(self, size=-1):
        """Sync read wrapper for Pyrogram"""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.read_async(size))
    
    def close(self):
        """Close stream and cleanup"""
        if not self._closed:
            self._closed = True
            if self.response:
                self.response.close()
            super().close()
    
    def __len__(self):
        return max(self.total_size, 100 * 1024 * 1024)

# --- LINK EXTRACTOR ---
async def get_direct_link(terabox_url):
    try:
        clean_url = re.sub(r"https?://[a-zA-Z0-9.-]+", "https://www.terabox.com", terabox_url)
        
        client = TeraboxDL(TERABOX_COOKIE)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: client.get_file_info(clean_url))
        
        if not result:
            return None, None
        
        file_info = result[0] if isinstance(result, list) else result
        dlink = file_info.get('dlink') or file_info.get('download_link') or file_info.get('url')
        filename = file_info.get('server_filename', 'terabox_file.mp4')
        
        return dlink, filename
    except Exception as e:
        return None, None

# --- MAIN PROCESSOR ---
async def process_single_link(client: Client, message: Message, terabox_url: str):
    user_id = message.from_user.id
    stop_dict[user_id] = False
    
    status = await message.reply_text("🔍 **Extracting download link...**")
    
    try:
        direct_url, filename = await get_direct_link(terabox_url)
        
        if not direct_url:
            await status.edit_text(
                "❌ **Link extraction failed!**\n\n"
                "**Check:**\n"
                "• Link validity\n"
                "• TERABOX_COOKIE in env\n"
                "• Cookie not expired"
            )
            return

        await status.edit_text(f"✅ **Got it!**\n📄 `{filename}`\n\n🔗 Connecting...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': TERABOX_COOKIE,
            'Referer': 'https://www.terabox.com/',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=False)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            start_time = time.time()
            
            # Create stream
            stream = ProxyStream(session, direct_url, filename, headers, user_id)
            
            try:
                await stream.initialize()
                
                if stop_dict.get(user_id):
                    stream.close()
                    await status.edit_text("❌ Cancelled")
                    return
                
                connection_type = "🌐 Proxy" if stream.using_proxy else "🔗 Direct"
                await status.edit_text(f"{connection_type} **connected!**\n📤 Uploading...")
                
                # Try video upload
                try:
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=stream,
                        caption=f"🎬 **{filename}**\n\n{connection_type} connection",
                        supports_streaming=True,
                        progress=progress_bar,
                        progress_args=(status, start_time, user_id)
                    )
                    
                except Exception as vid_err:
                    # Fallback to document
                    stream.close()
                    
                    await status.edit_text("📦 Sending as document...")
                    
                    # Create new stream for document
                    stream2 = ProxyStream(session, direct_url, filename, headers, user_id)
                    await stream2.initialize()
                    
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=stream2,
                        caption=f"📁 **{filename}**",
                        progress=progress_bar,
                        progress_args=(status, start_time, user_id)
                    )
                    
                    stream2.close()
                
                stream.close()
                await status.delete()
                await message.reply_text("✅ **Done!** 🎉")
                
            except Exception as stream_err:
                stream.close()
                raise stream_err
        
        stop_dict[user_id] = False

    except Exception as e:
        error = str(e)
        
        if "cancel" in error.lower():
            await status.edit_text("🛑 **Cancelled**")
        elif "timeout" in error.lower():
            await status.edit_text(
                "⏱ **Timeout!**\n\n"
                "**Tried:**\n"
                "• Proxy servers\n"
                "• Direct connection\n\n"
                "**Try:**\n"
                "• Smaller file\n"
                "• Wait 10 mins\n"
                "• Check cookie"
            )
        elif "connection" in error.lower():
            await status.edit_text(
                "🔌 **Connection failed!**\n\n"
                "• Terabox blocking requests\n"
                "• All proxies failed\n"
                "• Try again later"
            )
        else:
            await status.edit_text(f"❌ **Error:**\n```{error[:250]}```")
        
        stop_dict[user_id] = False

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "🚀 **Terabox Downloader Pro**\n\n"
        "✨ **Features:**\n"
        "• Multi-proxy routing\n"
        "• Auto fallback system\n"
        "• IP block bypass\n"
        "• Smart retry logic\n\n"
        "📤 **Just send Terabox link!**\n\n"
        "**Commands:**\n"
        "/start - Info\n"
        "/stop - Cancel download"
    )

@app.on_message(filters.command("stop"))
async def stop_handler(client, message):
    user_id = message.from_user.id
    if user_id in stop_dict and not stop_dict[user_id]:
        stop_dict[user_id] = True
        await message.reply_text("🛑 **Stopping...**")
    else:
        await message.reply_text("ℹ️ No active download")

@app.on_message(filters.text & filters.regex(r"terabox|1024tera|momerybox|teraboxapp"))
async def handle_message(client, message):
    urls = re.findall(r'(https?://[^\s]+)', message.text)
    tera_urls = [u for u in urls if any(x in u for x in ['terabox', '1024tera', 'momerybox', 'teraboxapp'])]
    
    if tera_urls:
        user_id = message.from_user.id
        if user_id in stop_dict and not stop_dict[user_id]:
            await message.reply_text("⚠️ **Already downloading!**\nWait or /stop first.")
            return
            
        await process_single_link(client, message, tera_urls[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    print("🚀 Bot online with proxy magic!")
    app.run()
