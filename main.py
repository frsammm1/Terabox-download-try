import os
import re
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message
from TeraboxDL import TeraboxDL  # <--- Ye library humne add ki hai

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Cookie bahut jaruri hai is library ke liye
TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE") 

PORT = int(os.environ.get("PORT", 8080))
TG_SPLIT_LIMIT = 2000 * 1024 * 1024  

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER (Keep Alive) ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="I am Alive!")
    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- Streaming Class (Same as before) ---
class URLFile:
    def __init__(self, session, url, total_size, filename, start_byte=0):
        self.session = session
        self.url = url
        self.total_size = total_size
        self.filename = filename
        self.name = filename
        self.start_byte = start_byte
        self.current_byte = 0
        self.response = None

    async def __aenter__(self):
        headers = {'User-Agent': 'Mozilla/5.0'} # Basic header added
        if self.start_byte > 0:
            headers['Range'] = f'bytes={self.start_byte}-'
        timeout = aiohttp.ClientTimeout(total=None, connect=60)
        self.response = await self.session.get(self.url, headers=headers, timeout=timeout)
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

# --- Progress Bar ---
async def progress_bar(current, total, message: Message):
    try:
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

# --- NEW DIRECT LINK LOGIC (USING Damantha126/TeraboxDL) ---
async def get_direct_link(terabox_url):
    try:
        if not TERABOX_COOKIE:
            return None, "Error: TERABOX_COOKIE not found in Env Variables."

        # Library initialize karo
        client = TeraboxDL(TERABOX_COOKIE)
        
        # Link fetch karo (Library sync hai, isliye hum ise executor me chalayenge taki bot na ruke)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: client.get_file_info(terabox_url, direct_url=True))
        
        if not result or 'download_link' not in result:
             return None, "Failed to extract link. Cookie might be expired."

        return result['download_link'], None

    except Exception as e:
        return None, f"Exception: {e}"

# --- SINGLE LINK PROCESSOR ---
async def process_single_link(client, message, terabox_url):
    status_msg = await message.reply_text(f"⏳ Extracting: {terabox_url}")
    
    try:
        # 1. Direct Link nikalo (Naye function se)
        direct_url, error_msg = await get_direct_link(terabox_url)

        if not direct_url:
            await status_msg.edit_text(f"❌ {error_msg}")
            return

        # 2. Metadata Check
        async with aiohttp.ClientSession() as session:
            # User Agent jaruri hai taki Terabox connection na tode
            headers = {'User-Agent': 'Mozilla/5.0'}
            async with session.head(direct_url, headers=headers) as head_resp:
                total_size = int(head_resp.headers.get('Content-Length', 0))
                content_type = head_resp.headers.get('Content-Type', '')
                
                # Filename logic
                filename = "video.mp4"
                cd = head_resp.headers.get("Content-Disposition")
                if cd and "filename=" in cd:
                    filename = cd.split("filename=")[1].strip('"')
                
                file_category = get_file_type(content_type, filename)
                
                if file_category == "VIDEO" and not filename.lower().endswith(".mp4"):
                    filename = os.path.splitext(filename)[0] + ".mp4"

            if total_size > TG_SPLIT_LIMIT:
                await status_msg.edit_text(f"⚠️ File > 2GB ({total_size/(1024**3):.2f}GB). Part 1 sending...")
            else:
                await status_msg.edit_text(f"🚀 Streaming: {filename}\nSize: {total_size / (1024**2):.2f} MB")
            
            # 3. Streaming Start
            async with URLFile(session, direct_url, total_size, filename) as stream_file:
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

# --- HANDLER ---
@app.on_message(filters.text & filters.regex(r"terabox"))
async def handle_message(client, message):
    text = message.text
    urls = re.findall(r'(https?://[^\s]+)', text)
    tera_urls = [url for url in urls if "terabox" in url or "1024tera" in url]
    
    if not tera_urls:
        return

    unique_urls = list(set(tera_urls))
    await message.reply_text(f"🔎 Found {len(unique_urls)} links.")

    for link in unique_urls:
        await process_single_link(client, message, link)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    app.run()
            
