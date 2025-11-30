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

# FREE PROXY SERVICES - Ye Terabox block bypass karenge
PROXY_SERVICES = [
    "https://api.allorigins.win/raw?url=",  # AllOrigins
    "https://corsproxy.io/?",  # CORS Proxy
    "https://api.codetabs.com/v1/proxy?quest=",  # CodeTabs
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

# --- ADVANCED STREAMING CLASS ---
class SuperStream:
    def __init__(self, session, url, filename, headers, user_id, use_proxy=False):
        self.session = session
        self.original_url = url
        self.url = url
        self.filename = filename
        self.headers = headers
        self.user_id = user_id
        self.use_proxy = use_proxy
        self.name = filename
        self.mode = 'rb'
        
        self.current_byte = 0
        self.total_size = 0
        self.response = None
        self.failed_proxies = set()
        
    async def __aenter__(self):
        # Agar proxy mode hai to proxy ke through connect karo
        if self.use_proxy:
            success = await self._connect_via_proxy()
            if not success:
                # Sab proxy fail, direct try karo
                self.use_proxy = False
                await self._connect_direct()
        else:
            await self._connect_direct()
            
        return self

    async def _connect_via_proxy(self):
        """Proxy services try karo ek ek karke"""
        available_proxies = [p for p in PROXY_SERVICES if p not in self.failed_proxies]
        
        if not available_proxies:
            return False
            
        # Random proxy select karo
        proxy = random.choice(available_proxies)
        proxied_url = f"{proxy}{self.original_url}"
        
        try:
            timeout = aiohttp.ClientTimeout(total=None, connect=25, sock_read=60)
            
            self.response = await self.session.get(
                proxied_url,
                headers={'User-Agent': self.headers['User-Agent']},  # Proxy ko sirf UA bhejo
                timeout=timeout,
                allow_redirects=True
            )
            
            if self.response.status == 200:
                self.total_size = int(self.response.headers.get('Content-Length', 0))
                
                # Test read - verify data aa raha hai
                test_data = await asyncio.wait_for(self.response.content.read(8192), timeout=15)
                
                if test_data:
                    # Success! Is proxy ka URL use karo
                    self.url = proxied_url
                    # Test data ko current byte mein add karo
                    self.current_byte = len(test_data)
                    # Aur ye data return karne ke liye store karo
                    self._buffer = test_data
                    return True
                    
            self.failed_proxies.add(proxy)
            return False
            
        except Exception as e:
            self.failed_proxies.add(proxy)
            return False

    async def _connect_direct(self):
        """Direct connection - original method"""
        timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=60)
        
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            ssl=False,
            limit=5,
            force_close=False
        )
        
        # Multiple attempts with different headers
        for attempt in range(3):
            try:
                # Har attempt pe thoda headers change karo
                dynamic_headers = self.headers.copy()
                dynamic_headers['User-Agent'] = random.choice([
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
                ])
                
                self.response = await self.session.get(
                    self.original_url,
                    headers=dynamic_headers,
                    timeout=timeout,
                    allow_redirects=True
                )
                
                if self.response.status == 200:
                    self.total_size = int(self.response.headers.get('Content-Length', 0))
                    
                    # Verify connection
                    test_data = await asyncio.wait_for(self.response.content.read(8192), timeout=10)
                    if test_data:
                        self._buffer = test_data
                        self.current_byte = len(test_data)
                        return
                        
                await asyncio.sleep(2 * (attempt + 1))
                
            except Exception as e:
                if attempt == 2:
                    raise Exception(f"Direct connection failed: {str(e)}")
                await asyncio.sleep(3)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.response:
            self.response.close()

    async def read(self, size=-1):
        if stop_dict.get(self.user_id, False):
            return b""
            
        if self.current_byte >= TG_SPLIT_LIMIT:
            return b""
        
        # Pehle buffer se return karo agar hai
        if hasattr(self, '_buffer') and self._buffer:
            data = self._buffer
            delattr(self, '_buffer')
            return data
            
        if not self.response:
            return b""
        
        try:
            chunk = await asyncio.wait_for(
                self.response.content.read(size if size > 0 else 1024*1024),
                timeout=45
            )
            
            if chunk:
                self.current_byte += len(chunk)
                return chunk
            return b""
            
        except asyncio.TimeoutError:
            # Timeout pe proxy try karo agar abhi tak nahi kiya
            if not self.use_proxy:
                # Switch to proxy mode
                self.use_proxy = True
                if await self._connect_via_proxy():
                    return await self.read(size)
            return b""
        except Exception:
            return b""

    def __len__(self):
        return max(self.total_size, 50 * 1024 * 1024)  # Minimum 50MB estimate

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
    except Exception:
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
                "**Possible reasons:**\n"
                "• Invalid/expired link\n"
                "• Cookie expired (update TERABOX_COOKIE)\n"
                "• Terabox API changed"
            )
            return

        await status.edit_text(f"✅ **Link extracted!**\n📄 `{filename}`\n\n🚀 Starting download...")
        
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
            
            # FIRST TRY: Proxy se try karo (Render IP bypass)
            await status.edit_text("🌐 **Connecting via proxy...**")
            
            try:
                async with SuperStream(session, direct_url, filename, headers, user_id, use_proxy=True) as stream:
                    
                    if stop_dict.get(user_id):
                        await status.edit_text("❌ Cancelled")
                        return
                    
                    await status.edit_text("📤 **Uploading to Telegram...**")
                    
                    # Video try karo
                    try:
                        await client.send_video(
                            chat_id=message.chat.id,
                            video=stream,
                            caption=f"🎬 **{filename}**\n\n⚡ Powered by Proxy Magic",
                            supports_streaming=True,
                            progress=progress_bar,
                            progress_args=(status, start_time, user_id)
                        )
                    except Exception:
                        # Video fail to document bhejo
                        await status.edit_text("📦 Sending as document...")
                        
                        # New stream chahiye
                        async with SuperStream(session, direct_url, filename, headers, user_id, use_proxy=True) as stream2:
                            await client.send_document(
                                chat_id=message.chat.id,
                                document=stream2,
                                caption=f"📁 **{filename}**",
                                progress=progress_bar,
                                progress_args=(status, start_time, user_id)
                            )
                
                await status.delete()
                await message.reply_text("✅ **Upload successful!** 🎉")
                
            except Exception as proxy_error:
                # Proxy fail, direct try karo
                await status.edit_text("⚠️ Proxy failed, trying direct connection...")
                
                async with SuperStream(session, direct_url, filename, headers, user_id, use_proxy=False) as stream:
                    
                    try:
                        await client.send_video(
                            chat_id=message.chat.id,
                            video=stream,
                            caption=f"🎬 **{filename}**",
                            supports_streaming=True,
                            progress=progress_bar,
                            progress_args=(status, start_time, user_id)
                        )
                    except Exception:
                        async with SuperStream(session, direct_url, filename, headers, user_id, use_proxy=False) as stream2:
                            await client.send_document(
                                chat_id=message.chat.id,
                                document=stream2,
                                caption=f"📁 **{filename}**",
                                progress=progress_bar,
                                progress_args=(status, start_time, user_id)
                            )
                
                await status.delete()
                await message.reply_text("✅ **Upload successful!** 🎉")
        
        stop_dict[user_id] = False

    except Exception as e:
        error = str(e)
        
        if "cancel" in error.lower():
            await status.edit_text("🛑 **Upload cancelled by user**")
        elif "timeout" in error.lower() or "blocked" in error.lower():
            await status.edit_text(
                "⚠️ **Connection failed!**\n\n"
                "**Tried:**\n"
                "✓ Multiple proxy services\n"
                "✓ Direct connection\n"
                "✓ Different user agents\n\n"
                "**Suggestions:**\n"
                "• Try again in 10 minutes\n"
                "• Check if cookie is valid\n"
                "• Try different link\n"
                "• File might be too large"
            )
        else:
            await status.edit_text(f"❌ **Error:**\n`{error[:300]}`")
        
        stop_dict[user_id] = False

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "🚀 **Advanced Terabox Downloader**\n\n"
        "💡 **Features:**\n"
        "• Automatic proxy rotation\n"
        "• Direct connection fallback\n"
        "• Smart retry mechanism\n"
        "• IP block bypass\n\n"
        "📤 Just send me any Terabox link!\n\n"
        "**Commands:**\n"
        "/start - Show this message\n"
        "/stop - Cancel current download\n\n"
        "**Supported:** terabox, 1024tera, momerybox, teraboxapp"
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
            await message.reply_text("⚠️ **You already have an active download!**\nWait for it to finish or /stop it.")
            return
            
        await process_single_link(client, message, tera_urls[0])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    print("🚀 Bot started with proxy magic!")
    app.run()
