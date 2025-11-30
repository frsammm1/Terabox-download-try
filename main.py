import os
import re
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from TeraboxDL import TeraboxDL

# --- Configs (Env Variables) ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE") 
PORT = int(os.environ.get("PORT", 8080))

# 2GB Limit (Telegram Limit)
TG_SPLIT_LIMIT = 2000 * 1024 * 1024  

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER (Keep Alive Logic) ---
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

# --- Streaming Class (Memory Friendly) ---
class URLFile:
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

    async def __aenter__(self):
        # Range header support for splitting or resuming
        req_headers = self.headers.copy()
        if self.start_byte > 0:
            req_headers['Range'] = f'bytes={self.start_byte}-'
        
        # Timeout None rakha hai taki badi files beech me na kate
        timeout = aiohttp.ClientTimeout(total=None, connect=60)
        self.response = await self.session.get(self.url, headers=req_headers, timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.response:
            self.response.close()

    async def read(self, chunk_size):
        if self.response:
            # 2GB Limit Check
            if self.current_byte >= TG_SPLIT_LIMIT:
                return b""
            data = await self.response.content.read(chunk_size)
            self.current_byte += len(data)
            return data
        return b""

    def __len__(self):
        remaining = self.total_size - self.start_byte
        return min(remaining, TG_SPLIT_LIMIT)

# --- Progress Bar ---
async def progress_bar(current, total, message: Message):
    try:
        # Har 10% par update karega to avoid flood wait
        if current % (total // 10) == 0:
            percent = current * 100 / total
            await message.edit_text(f"📥 Uploading... {percent:.1f}%")
    except:
        pass

# --- Helper: File Type Detector ---
def get_file_type(content_type, url):
    ext = os.path.splitext(url)[1].lower()
    video_exts = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
    
    if "video" in content_type or ext in video_exts:
        return "VIDEO"
    elif "image" in content_type:
        return "PHOTO"
    else:
        return "DOCUMENT"

# --- CORE LOGIC: Get Direct Link (FIXED) ---
async def get_direct_link(terabox_url):
    try:
        if not TERABOX_COOKIE:
            return None, "Error: TERABOX_COOKIE variable missing in Render."

        # Library setup
        client = TeraboxDL(TERABOX_COOKIE)
        
        # FIX: 'direct_url=True' argument hata diya hai.
        # Ye background me chalega taki bot freeze na ho
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: client.get_file_info(terabox_url))
        
        if not result:
             return None, "Failed. Link dead or Cookie expired."

        # Result parsing logic (List vs Dict handle karne ke liye)
        file_info = None
        if isinstance(result, list) and len(result) > 0:
            file_info = result[0] 
        elif isinstance(result, dict):
            file_info = result

        if not file_info:
            return None, "No file info found in response."

        # Alag alag keys try karenge link nikalne ke liye
        direct_link = file_info.get('dlink') or file_info.get('download_link') or file_info.get('url')

        if not direct_link:
            return None, "Direct Link not found in API response."

        return direct_link, None

    except Exception as e:
        return None, f"Exception: {e}"

# --- SINGLE LINK PROCESSOR ---
async def process_single_link(client, message, terabox_url):
    status_msg = await message.reply_text(f"⏳ Extracting: {terabox_url}")
    
    try:
        # 1. Get Direct Link
        direct_url, error_msg = await get_direct_link(terabox_url)

        if not direct_url:
            await status_msg.edit_text(f"❌ {error_msg}")
            return

        # Headers setup (Important: User-Agent + Cookie pass karna safe rehta hai)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Cookie': TERABOX_COOKIE
        }

        # 2. Metadata Check (Size & Type)
        async with aiohttp.ClientSession() as session:
            async with session.head(direct_url, headers=headers) as head_resp:
                total_size = int(head_resp.headers.get('Content-Length', 0))
                content_type = head_resp.headers.get('Content-Type', '')
                
                # Filename Extraction
                filename = "video.mp4"
                cd = head_resp.headers.get("Content-Disposition")
                if cd and "filename=" in cd:
                    filename = cd.split("filename=")[1].strip('"')
                
                # Determine Type
                file_category = get_file_type(content_type, filename)
                
                # Force MP4 extension for videos to enable streaming
                if file_category == "VIDEO" and not filename.lower().endswith(".mp4"):
                    filename = os.path.splitext(filename)[0] + ".mp4"

            # 3. Size Handling
            if total_size > TG_SPLIT_LIMIT:
                await status_msg.edit_text(f"⚠️ File > 2GB ({total_size/(1024**3):.2f} GB).\nSending Part 1 (2GB)...")
            else:
                await status_msg.edit_text(f"🚀 Streaming: {filename}\nSize: {total_size / (1024**2):.2f} MB")
            
            # 4. Start Streaming Upload
            async with URLFile(session, direct_url, total_size, filename, headers) as stream_file:
                if file_category == "VIDEO":
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=stream_file,
                        caption=f"🎥 **{filename}**",
                        supports_streaming=True,
                        progress=progress_bar,
                        progress_args=(status_msg,)
                    )
                elif file_category == "PHOTO":
                    await client.send_photo(message.chat.id, photo=stream_file)
                else:
                    await client.send_document(
                        message.chat.id, 
                        document=stream_file, 
                        caption=filename,
                        progress=progress_bar,
                        progress_args=(status_msg,)
                    )
            
            await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ Error: {e}")

# --- MESSAGE HANDLER ---
@app.on_message(filters.text & filters.regex(r"terabox"))
async def handle_message(client, message):
    text = message.text
    # Regex to find links
    urls = re.findall(r'(https?://[^\s]+)', text)
    tera_urls = [url for url in urls if "terabox" in url or "1024tera" in url]
    
    if not tera_urls:
        return

    # Unique Links Logic
    unique_urls = list(set(tera_urls))
    await message.reply_text(f"🔎 Found {len(unique_urls)} unique links. Queue started...")

    # Process one by one
    for link in unique_urls:
        await process_single_link(client, message, link)

# --- STARTUP ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server()) # Start Web Server for Keep-Alive
    app.run() # Start Bot
                
