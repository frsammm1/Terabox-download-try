import os
import re
import aiohttp
import asyncio
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# --- Configs ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080)) # Render ye port automatically deta hai

# 2GB Limit
TG_SPLIT_LIMIT = 2000 * 1024 * 1024  

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- WEB SERVER FOR KEEP-ALIVE (CRON JOB KE LIYE) ---
async def web_server():
    async def handle_ping(request):
        return web.Response(text="I am Alive!")

    webapp = web.Application()
    webapp.router.add_get("/", handle_ping)
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web Server Started on Port {PORT}")

# --- Streaming Class ---
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
        headers = {}
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

# --- Helper Functions ---
async def progress_bar(current, total, message: Message):
    try:
        if current % (total // 10) == 0: # Update less frequently
            percent = current * 100 / total
            await message.edit_text(f"📥 Uploading... {percent:.1f}%")
    except:
        pass

def get_file_type(content_type, url):
    ext = os.path.splitext(url)[1].lower()
    video_exts = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm']
    if "video" in content_type or ext in video_exts:
        return "VIDEO"
    elif "image" in content_type:
        return "PHOTO"
    else:
        return "DOCUMENT"

# --- CORE LOGIC: SINGLE LINK PROCESSOR ---
async def process_single_link(client, message, terabox_url):
    status_msg = await message.reply_text(f"⏳ Processing: {terabox_url}")
    
    try:
        # === YOUR DIRECT LINK LOGIC HERE ===
        # direct_url = await get_direct_link(terabox_url)
        direct_url = "REPLACE_WITH_REAL_DIRECT_LINK" 

        if not direct_url:
            await status_msg.edit_text(f"❌ Failed to extract: {terabox_url}")
            return

        async with aiohttp.ClientSession() as session:
            async with session.head(direct_url) as head_resp:
                total_size = int(head_resp.headers.get('Content-Length', 0))
                content_type = head_resp.headers.get('Content-Type', '')
                
                # Filename Extraction
                filename = "video.mp4"
                cd = head_resp.headers.get("Content-Disposition")
                if cd and "filename=" in cd:
                    filename = cd.split("filename=")[1].strip('"')
                
                file_category = get_file_type(content_type, filename)
                
                if file_category == "VIDEO" and not filename.lower().endswith(".mp4"):
                    filename = os.path.splitext(filename)[0] + ".mp4"

            if total_size > TG_SPLIT_LIMIT:
                await status_msg.edit_text(f"⚠️ File > 2GB. Sending Part 1 only.\nName: {filename}")
                # Logic for Part 1 (omitted for brevity, same as previous code)
            else:
                await status_msg.edit_text(f"🚀 Streaming: {filename}\nSize: {total_size / (1024**2):.2f} MB")
                
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
        await status_msg.edit_text(f"⚠️ Error with link: {e}")

# --- MESSAGE HANDLER (MULTI-LINK LOGIC) ---
@app.on_message(filters.text & filters.regex(r"terabox")) # Koi bhi text jisme terabox ho
async def handle_message(client, message):
    text = message.text
    
    # 1. Regex se saare URLs nikalo
    urls = re.findall(r'(https?://[^\s]+)', text)
    
    # 2. Filter only Terabox links
    tera_urls = [url for url in urls if "terabox" in url or "1024tera" in url]
    
    if not tera_urls:
        return

    # 3. Unique Links (Set logic: 5 total -> 4 unique)
    unique_urls = list(set(tera_urls))
    
    await message.reply_text(f"🔎 Found {len(unique_urls)} unique Terabox links. Starting queue...")

    # 4. Loop one by one (Sequential Processing)
    for i, link in enumerate(unique_urls, 1):
        # User ko batao kaunsa number chal raha hai
        # await message.reply_text(f"⬇️ Processing Link {i}/{len(unique_urls)}")
        
        # Await lagaya hai taki jab tak ye complete na ho, agla shuru na ho
        await process_single_link(client, message, link)

# --- STARTUP ---
if __name__ == "__main__":
    print("Bot Starting with Web Server...")
    
    # Client aur Web Server dono ko ek sath chalane ke liye
    loop = asyncio.get_event_loop()
    loop.create_task(web_server()) # Web server background me start
    app.run() # Bot start
      
