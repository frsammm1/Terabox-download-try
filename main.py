import os
import re
import time
import math
import io
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from TeraboxDL import TeraboxDL

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE") 
PORT = int(os.environ.get("PORT", 8080))

# 2GB Limit
TG_SPLIT_LIMIT = 2000 * 1024 * 1024  

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="Bot is Running & Alive!")
    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web Server Started on Port {PORT}")

# --- Helper: Human Readable Size ---
def humanbytes(size):
    if not size:
        return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

# --- Advanced Progress Bar ---
async def progress_bar(current, total, message, start_time):
    now = time.time()
    diff = now - start_time
    
    if diff < 1: return 

    if current % (total // 15) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000
        estimated_total_time = elapsed_time + time_to_completion
        
        # Time Formatting
        def time_fmt(ms):
            s, ms = divmod(int(ms), 1000)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        
        estimated_str = time_fmt(time_to_completion)
        
        progress = "[{0}{1}] {2}%\n".format(
            ''.join(["■" for i in range(math.floor(percentage / 10))]),
            ''.join(["□" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 1))
            
        tmp = progress + f"📁 {humanbytes(current)} / {humanbytes(total)}\n🚀 {humanbytes(speed)}/s\n⏱ ETA: {estimated_str}"
        
        try:
            await message.edit_text(text=f"{tmp}")
        except:
            pass

# --- Streaming Class (Binary Mode + SSL Fix) ---
class URLFile(io.BytesIO): 
    def __init__(self, session, url, total_size, filename, headers, start_byte=0):
        self.session = session
        self.url = url
        self.total_size = total_size
        self.filename = filename
        self.headers = headers
        self.name = filename
        self.start_byte = start_byte
        self.current_byte = 0
        self.response = None
        self.mode = 'rb' 

    async def __aenter__(self):
        req_headers = self.headers.copy()
        if self.start_byte > 0:
            req_headers['Range'] = f'bytes={self.start_byte}-'
        
        # SSL False kiya hai taaki connection error na aaye
        timeout = aiohttp.ClientTimeout(total=None, connect=60)
        self.response = await self.session.get(self.url, headers=req_headers, timeout=timeout, ssl=False)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.response:
            self.response.close()

    async def read(self, chunk_size):
        if self.response:
            if self.current_byte >= TG_SPLIT_LIMIT:
                return b""
            data = await self.response.content.read(chunk_size)
            self.current_byte += len(data)
            return data
        return b""

    def __len__(self):
        remaining = self.total_size - self.start_byte
        return min(remaining, TG_SPLIT_LIMIT)

def get_file_type(content_type, url):
    ext = os.path.splitext(url)[1].lower()
    video_exts = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
    if "video" in content_type or ext in video_exts:
        return "VIDEO"
    elif "image" in content_type:
        return "PHOTO"
    else:
        return "DOCUMENT"

# --- SMART URL CLEANER & DIRECT LINK ---
async def get_direct_link(terabox_url):
    try:
        if not TERABOX_COOKIE:
            return None, "Error: TERABOX_COOKIE missing."

        clean_url = re.sub(r"https?://[a-zA-Z0-9.-]+", "https://www.terabox.com", terabox_url)
        
        client = TeraboxDL(TERABOX_COOKIE)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: client.get_file_info(clean_url))
        
        if not result:
             return None, "Link dead or Cookie expired."

        file_info = None
        if isinstance(result, list) and len(result) > 0:
            file_info = result[0] 
        elif isinstance(result, dict):
            file_info = result

        if not file_info:
            return None, "No file info found."

        direct_link = file_info.get('dlink') or file_info.get('download_link') or file_info.get('url')

        if not direct_link:
            return None, "Direct Link extraction failed."

        return direct_link, None

    except Exception as e:
        return None, f"Exception: {e}"

# --- PROCESSOR ---
async def process_single_link(client, message, terabox_url):
    status_msg = await message.reply_text(f"⏳ **Processing...**\n`{terabox_url}`")
    
    try:
        direct_url, error_msg = await get_direct_link(terabox_url)

        if not direct_url:
            await status_msg.edit_text(f"❌ **Error:** {error_msg}")
            return

        # --- HEADERS MAGIC (FIX FOR 0B ERROR) ---
        # Referer add karna jaruri hai varna Terabox reject kar deta hai
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Cookie': TERABOX_COOKIE,
            'Referer': 'https://www.terabox.com/' 
        }

        # SSL Verify False kiya hai (FIX FOR CONNECTION ERROR)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.head(direct_url, headers=headers, allow_redirects=True) as head_resp:
                    total_size = int(head_resp.headers.get('Content-Length', 0))
                    content_type = head_resp.headers.get('Content-Type', '')
                    
                    # Agar HEAD request me size 0 aaya, to GET request try karo
                    if total_size == 0:
                        # Sometimes HEAD fails on Terabox, GET works
                        pass 

                    filename = "video.mp4"
                    cd = head_resp.headers.get("Content-Disposition")
                    if cd and "filename=" in cd:
                        filename = cd.split("filename=")[1].strip('"')
                    
                    file_category = get_file_type(content_type, filename)
                    if file_category == "VIDEO" and not filename.lower().endswith(".mp4"):
                        filename = os.path.splitext(filename)[0] + ".mp4"

            except Exception as e:
                # Agar HEAD request fail hua, tab bhi hum download try karenge
                print(f"HEAD Failed: {e}")
                total_size = 100 * 1024 * 1024 # Fake size assume kar lo start karne ke liye
                filename = "video.mp4"
                file_category = "VIDEO"

            if total_size > TG_SPLIT_LIMIT:
                await status_msg.edit_text(f"⚠️ **File Too Big**\nSize: {humanbytes(total_size)}\nSending first 2GB only...")
            else:
                await status_msg.edit_text(f"🚀 **Starting Download...**\n**File:** {filename}\n**Size:** {humanbytes(total_size)}")
            
            start_time = time.time()
            # Yaha bhi session pass kar rahe hain jisme SSL disabled hai
            async with URLFile(session, direct_url, total_size, filename, headers) as stream_file:
                if file_category == "VIDEO":
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=stream_file,
                        caption=f"🎥 **{filename}**",
                        supports_streaming=True,
                        progress=progress_bar,
                        progress_args=(status_msg, start_time)
                    )
                elif file_category == "PHOTO":
                    await client.send_photo(message.chat.id, photo=stream_file)
                else:
                    await client.send_document(
                        message.chat.id, 
                        document=stream_file, 
                        caption=f"📁 **{filename}**",
                        progress=progress_bar,
                        progress_args=(status_msg, start_time)
                    )
            
            await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Critical Error:** {e}")

# --- HANDLERS ---
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("👋 Terabox Link Bhejo!")

@app.on_message(filters.text & filters.regex(r"terabox|1024tera|momerybox|teraboxapp"))
async def handle_message(client, message):
    text = message.text
    urls = re.findall(r'(https?://[^\s]+)', text)
    tera_urls = [url for url in urls if any(x in url for x in ['terabox', '1024tera', 'momerybox', 'teraboxapp'])]
    
    if not tera_urls:
        return

    unique_urls = list(set(tera_urls))
    await message.reply_text(f"🔎 Found {len(unique_urls)} links. Processing...")

    for link in unique_urls:
        await process_single_link(client, message, link)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
        
