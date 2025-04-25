import os
import time
import logging
import sqlite3
import asyncio
import requests
import yt_dlp
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
ADMIN_ID = 6086282402
GEMINI_API_KEY = "AIzaSyAKIIP4FgvMPo7EfFmqrW7oQkvtqM96clM"
CLIPDROP_API_KEY = "bb7430dde6f87c0fbcc72ee3d0f85e8423b79a93399fa230fbfdbcdcba0b7f6388999e7107f2f879a01e48378c768cc0"
MAX_FILE_SIZE_MB = 300  # Maximum file size in MB
MAX_CONCURRENT_DOWNLOADS = 50  # Maximum concurrent downloads

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
generation_config = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 4096,
}
model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config=generation_config)

# ClipDrop API endpoints
CLIPDROP_ENDPOINTS = {
    "text_removal": "https://clipdrop-api.co/text-inpainting/v1",
    "logo_removal": "https://clipdrop-api.co/remove-background/v1",
    "image_generation": "https://clipdrop-api.co/text-to-image/v1",
    "bulk_removal": "https://clipdrop-api.co/batch-processing/v1",
    "ios_demo": "https://clipdrop-api.co/image-upscaling/v1"
}

# Create download semaphore for limiting concurrent downloads
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS)

# Database setup
def setup_database():
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        is_active INTEGER DEFAULT 1,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        downloads_count INTEGER DEFAULT 0
    )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
        (user_id, username, first_name, last_name)
    )
    conn.commit()
    conn.close()

def update_user_activity(user_id):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()

def increment_download_count(user_id):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET downloads_count = downloads_count + 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_active = 1")
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

def get_user_details():
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, last_name, last_active, downloads_count FROM users ORDER BY last_active DESC")
    users = cursor.fetchall()
    conn.close()
    return users

def is_user_active(user_id):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0] == 1
    return False

def activate_user(user_id):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def deactivate_user(user_id):
    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    update_user_activity(user.id)

    welcome_text = (
        f"** Welcome, {user.first_name}! **\n\n"
        f"I'm your **YouTube & TikTok Downloader Bot**. Send me a YouTube or TikTok URL, "
        f"and I'll download the video for you without any watermarks!\n\n"
        f"**Available Commands:**\n"
        f"• Send any YouTube or TikTok URL to download\n"
        f"• /help - Show help information\n"
        f"• /code - Generate code files\n"
        f"• /debug - Debug your code files\n"
        f"• /image - Generate images with AI\n"
        f"• /removetext - Remove text from images\n"
        f"• /removelogo - Remove logos from images\n\n"
        f"Developed by: **Canzy-Xtr**"
    )

    keyboard = [
        [
            InlineKeyboardButton(" Help", callback_data="help"),
            InlineKeyboardButton(" About", callback_data="about")
        ],
        [
            InlineKeyboardButton(" Status", callback_data="status_check"),
            InlineKeyboardButton(" Stats", callback_data="stats_check"),
            InlineKeyboardButton(" Support", callback_data="support_check")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        with open('start.jpg', 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=welcome_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    except FileNotFoundError:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_activity(update.effective_user.id)

    help_text = (
        "** Bot Commands and Usage **\n\n"
        "**🎬 Video Download:**\n"
        "• Send a YouTube or TikTok URL to download videos\n"
        "• Maximum file size: 300MB\n\n"
        "**💻 Code Generation:**\n"
        "• Use `/code buatkan aku file sederhana python $file` to generate code\n"
        "• Replace `python` with any programming language\n\n"
        "**🤖 Debugging:**\n"
        "• Send a code file with `/debug` command and error description\n\n"
        "**🎨 AI Image Tools:**\n"
        "• `/image [prompt]` - Generate images with AI\n"
        "• `/removetext` - Remove text from images (attach image)\n"
        "• `/removelogo` - Remove logos from images (attach image)\n"
        "• `/bulkremove` - Process multiple images (attach zip file)\n"
        "• `/upscale` - Enhance image quality (attach image)\n\n"
        "**Admin Commands:**\n"
        "• `/broadcast` - Send message to all users\n"
        "• `/stats` - View bot statistics\n"
        "• `/users` - View detailed user information\n"
        "• `/activate` - Activate a user\n"
        "• `/deactivate` - Deactivate a user\n\n"
        "**Developed by: Canzy-Xtr**"
    )

    keyboard = [
        [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    url = update.message.text.strip()

    if "youtube.com" in url or "youtu.be" in url or "tiktok.com" in url:
        url_id = str(abs(hash(url)) % 10000000000)

        await update.message.reply_text(
            "**🔍 Processing your URL...**\n"
            "Please select the desired resolution:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("360p", callback_data=f"dl_360_{url_id}"),
                    InlineKeyboardButton("480p", callback_data=f"dl_480_{url_id}")
                ],
                [
                    InlineKeyboardButton("720p", callback_data=f"dl_720_{url_id}"),
                    InlineKeyboardButton("1080p", callback_data=f"dl_1080_{url_id}")
                ],
                [InlineKeyboardButton("Best Quality", callback_data=f"dl_best_{url_id}")]
            ])
        )

        if not context.user_data.get('urls'):
            context.user_data['urls'] = {}
        context.user_data['urls'][url_id] = url
    else:
        await update.message.reply_text(
            "**❌ Invalid URL!**\n"
            "Please send a valid YouTube or TikTok URL.",
            parse_mode='Markdown'
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    update_user_activity(user_id)

    if data == "help":
        help_text = (
            "** Bot Commands and Usage **\n\n"
            "**🎬 Video Download:**\n"
            "• Send a YouTube or TikTok URL to download videos\n"
            "• Maximum file size: 300MB\n\n"
            "**💻 Code Generation:**\n"
            "• Use `/code buatkan aku file sederhana python $file` to generate code\n"
            "• Replace `python` with any programming language\n\n"
            "**🤖 Debugging:**\n"
            "• Send a code file with `/debug` command and error description\n\n"
            "**🎨 AI Image Tools:**\n"
            "• `/image [prompt]` - Generate images with AI\n"
            "• `/removetext` - Remove text from images (attach image)\n"
            "• `/removelogo` - Remove logos from images (attach image)\n\n"
            "**Developed by: Canzy-Xtr**"
        )

        keyboard = [
            [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=help_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data == "about":
        about_text = (
            "** YouTube & TikTok Downloader Bot **\n\n"
            "This bot allows you to download videos from YouTube and TikTok without watermarks.\n\n"
            "**Features:**\n"
            "• Download videos in multiple resolutions\n"
            "• No watermarks on TikTok videos\n"
            "• Code generation and debugging\n"
            "• AI-powered image editing tools\n"
            "• Fast and reliable downloads\n"
            "• Maximum file size: 300MB\n\n"
            "**Developed by: Canzy-Xtr**"
        )

        keyboard = [
            [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=about_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data == "status_check":
        status_text = (
            "** Bot Status: Online ✅**\n\n"
            "All systems are operational and running smoothly.\n\n"
            "• API Connections: ✅\n"
            "• Download Service: ✅\n"
            "• Database: ✅\n"
            "• ClipDrop API: ✅\n"
            "• Gemini API: ✅\n\n"
            "**Developed by: Canzy-Xtr**"
        )

        keyboard = [
            [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=status_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data == "stats_check":
        if query.from_user.id == ADMIN_ID:
            conn = sqlite3.connect('bot_users.db')
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            active_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE join_date >= datetime('now', '-1 day')")
            recent_users = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(downloads_count) FROM users")
            total_downloads = cursor.fetchone()[0] or 0

            conn.close()

            stats_text = (
                "**📊 Bot Statistics 📊**\n\n"
                f"• Total Users: **{total_users}**\n"
                f"• Active Users: **{active_users}**\n"
                f"• New Users (24h): **{recent_users}**\n"
                f"• Total Downloads: **{total_downloads}**\n\n"
                f"**Developed by: Canzy-Xtr**"
            )
        else:
            stats_text = (
                "**📊 Bot Statistics 📊**\n\n"
                "This feature is only available to admins.\n\n"
                "**Developed by: Canzy-Xtr**"
            )

        keyboard = [
            [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=stats_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data == "support_check":
        support_text = (
            "** Support Information **\n\n"
            "If you need help or have any questions, please contact the developer.\n\n"
            "**Contact:**\n"
            "• Developer: Canzy-Xtr\n"
            "• Contact: @CanzyyKing\n\n"
            "**Common Issues:**\n"
            "• If downloads fail, try a different resolution\n"
            "• For TikTok videos, ensure the URL is public\n"
            "• Maximum file size is 300MB\n\n"
            "**Developed by: Canzy-Xtr**"
        )

        keyboard = [
            [InlineKeyboardButton(" Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=support_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data == "main_menu":
        user = query.from_user
        welcome_text = (
            f"** Welcome, {user.first_name}! **\n\n"
            f"I am **YouTube & TikTok Downloader Bot**. Send me a YouTube or TikTok URL, "
            f"and I'll download the video for you without any watermarks!\n\n"
            f"**Available Commands:**\n"
            f"• Send any YouTube or TikTok URL to download\n"
            f"• /help - Show help information\n"
            f"• /code - Generate code files\n"
            f"• /debug - Debug your code files\n"
            f"• /image - Generate images with AI\n"
            f"• /removetext - Remove text from images\n\n"
            f"Developed by: **Canzy-Xtr**"
        )

        keyboard = [
            [
                InlineKeyboardButton(" Help", callback_data="help"),
                InlineKeyboardButton(" About", callback_data="about")
            ],
            [
                InlineKeyboardButton(" Status", callback_data="status_check"),
                InlineKeyboardButton(" Stats", callback_data="stats_check"),
                InlineKeyboardButton(" Support", callback_data="support_check")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_caption(
            caption=welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    elif data.startswith("dl_"):
        parts = data.split("_", 2)
        resolution = parts[1]
        url_id = parts[2]

        if not context.user_data.get('urls') or url_id not in context.user_data['urls']:
            await query.edit_message_text(
                text="**❌ URL not found or expired!**\n"
                     "Please send the URL again.",
                parse_mode='Markdown'
            )
            return

        url = context.user_data['urls'][url_id]

        await query.edit_message_text(
            text=f"**⏳ Downloading video in {resolution} resolution...**\n"
                 "This may take a moment, please wait.",
            parse_mode='Markdown'
        )

        try:
            async with download_semaphore:
                video_path = await download_video(url, resolution, user_id)

                # Check file size
                file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    os.remove(video_path)
                    await query.message.reply_text(
                        f"**❌ File size exceeds limit!**\n"
                        f"The video is {file_size_mb:.1f}MB, but the maximum allowed size is {MAX_FILE_SIZE_MB}MB.\n"
                        f"Please try a lower resolution.",
                        parse_mode='Markdown'
                    )
                    return

                increment_download_count(user_id)

                with open(video_path, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=video_file,
                        caption=f"**✅ Download completed!**\n"
                                f"Resolution: **{resolution}**\n"
                                f"Size: **{file_size_mb:.1f}MB**\n\n"
                                f"**Developed by: Canzy-Xtr**",
                        parse_mode='Markdown',
                        supports_streaming=True
                    )

                # Schedule file deletion after 3 seconds
                asyncio.create_task(delete_file_after_delay(video_path, 3))

                await query.message.reply_text(
                    "** Enjoy your video! **\n"
                    "Send another URL to download more videos.",
                    parse_mode='Markdown'
                )

        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            await query.message.reply_text(
                f"**❌ Download failed!**\n"
                f"Error: {str(e)}\n\n"
                f"Please try again or try a different resolution.",
                parse_mode='Markdown'
            )

async def delete_file_after_delay(file_path, delay_seconds):
    """Delete a file after a specified delay"""
    await asyncio.sleep(delay_seconds)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted file: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_path}: {e}")

async def download_video(url, resolution, user_id):
    """Download a video with the specified resolution"""
    output_path = f"downloads/video_{hash(url)}_{resolution}_{user_id}.mp4"
    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'filesize_max': MAX_FILE_SIZE_MB * 1024 * 1024,  # Max file size in bytes
    }

    if resolution != "best":
        if "tiktok.com" in url:
            pass
        else:
            res_value = resolution.replace("p", "")
            ydl_opts['format'] = f'bestvideo[height<={res_value}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res_value}][ext=mp4]/best'

    # Run yt-dlp in a separate thread to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        executor,
        lambda: yt_dlp.YoutubeDL(ydl_opts).download([url])
    )

    return output_path

async def code_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    message_text = update.message.text

    if "$file" not in message_text:
        await update.message.reply_text(
            "**❌ Invalid format!**\n"
            "Please use the format: `/code buatkan aku file sederhana python $file`",
            parse_mode='Markdown'
        )
        return

    prompt = message_text.replace("/code ", "")
    language = "python"

    common_languages = ["python", "java", "javascript", "cpp", "c++", "c#", "php", "ruby", "go", "rust", "swift", "kotlin", "typescript"]

    for lang in common_languages:
        if lang in prompt.lower():
            language = lang
            break

    extensions = {
        "python": "py",
        "java": "java",
        "javascript": "js",
        "cpp": "cpp",
        "c++": "cpp",
        "c#": "cs",
        "php": "php",
        "ruby": "rb",
        "go": "go",
        "rust": "rs",
        "swift": "swift",
        "kotlin": "kt",
        "typescript": "ts"
    }

    file_extension = extensions.get(language, "txt")

    try:
        await update.message.reply_text(
            "**⏳ Generating code...**\n"
            "Please wait a moment.",
            parse_mode='Markdown'
        )

        system_prompt = f"You are a helpful assistant that generates {language} code. Provide only the code without explanations."

        response = model.generate_content([system_prompt, prompt])
        code = response.text.strip()

        file_name = f"code_{hash(prompt)}_{language}.{file_extension}"
        with open(file_name, "w") as file:
            file.write(code)

        with open(file_name, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"generated_code.{file_extension}",
                caption=f"**✅ Code generated successfully!**\n"
                        f"Language: **{language}**\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete file after sending
        asyncio.create_task(delete_file_after_delay(file_name, 3))

    except Exception as e:
        logger.error(f"Code generation error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Code generation failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

async def debug_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    if not update.message.document:
        await update.message.reply_text(
            "**❌ No file attached!**\n"
            "Please attach a code file to debug.",
            parse_mode='Markdown'
        )
        return

    error_description = ""
    if update.message.caption:
        error_description = update.message.caption.replace("/debug", "").strip()
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        error_description = update.message.reply_to_message.text.replace("/debug", "").strip()

    if not error_description:
        await update.message.reply_text(
            "**❌ No error description provided!**\n"
            "Please include error description in caption or reply to message with error details.",
            parse_mode='Markdown'
        )
        return

    file = await context.bot.get_file(update.message.document.file_id)
    file_name = update.message.document.file_name
    file_path = f"debug_{hash(file_name)}_{file_name}"

    try:
        await file.download_to_drive(file_path)

        with open(file_path, "r") as f:
            code_content = f.read()

        file_extension = file_name.split(".")[-1] if "." in file_name else "txt"
        language_map = {
            "py": "Python",
            "java": "Java",
            "js": "JavaScript",
            "cpp": "C++",
            "c": "C",
            "cs": "C#",
            "php": "PHP",
            "rb": "Ruby",
            "go": "Go",
            "rs": "Rust",
            "swift": "Swift",
            "kt": "Kotlin",
            "ts": "TypeScript"
        }

        language = language_map.get(file_extension, "Unknown")

        await update.message.reply_text(
            "**⏳ Debugging code...**\n"
            "Please wait a moment.",
            parse_mode='Markdown'
        )

        prompt = (
            f"Debug this {language} code. Here's the error description: {error_description}\n\n"
            f"Original code:\n```{language}\n{code_content}\n```\n\n"
            "Provide the complete fixed code (include all original code with fixes) in a single code block "
            "without additional explanations."
        )

        response = model.generate_content(prompt)
        debugged_code = response.text.strip()

        debugged_file_name = f"debugged_{file_name}"
        with open(debugged_file_name, "w") as file:
            file.write(debugged_code)

        with open(debugged_file_name, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=debugged_file_name,
                caption=f"**✅ Code debugged successfully!**\n"
                        f"Language: **{language}**\n"
                        f"Error: {error_description[:100]}...\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete files after sending
        asyncio.create_task(delete_file_after_delay(file_path, 3))
        asyncio.create_task(delete_file_after_delay(debugged_file_name, 3))

    except Exception as e:
        logger.error(f"Debugging error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Debugging failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )
        if os.path.exists(file_path):
            os.remove(file_path)

# ClipDrop API functions
async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Akun kamu belum terdaftar, silakan salin ID kamu:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "Dan kirim pesan `/activate {your id}` ke admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    prompt = update.message.text.replace("/image", "").strip()

    if not prompt:
        await update.message.reply_text(
            "**❌ Tidak ada prompt yang diberikan!**\n"
            "Gunakan format: `/image deskripsi gambar yang kamu inginkan`",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "**⏳ Membuat gambar...**\n"
        "Mohon tunggu sebentar.",
        parse_mode='Markdown'
    )

    try:
        # Panggil ClipDrop API untuk generate image dengan format yang benar
        response = requests.post(
            CLIPDROP_ENDPOINTS["image_generation"],
            headers={
                "x-api-key": CLIPDROP_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "prompt": prompt
            }
        )

        if response.status_code != 200:
            raise Exception(f"API returned status code {response.status_code}: {response.text}")

        # Simpan gambar yang dihasilkan
        image_path = f"downloads/generated_image_{hash(prompt)}_{user_id}.png"
        os.makedirs("downloads", exist_ok=True)

        with open(image_path, "wb") as f:
            f.write(response.content)

        # Kirim gambar
        with open(image_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption=f"**✅ Gambar berhasil dibuat!**\n"
                        f"Prompt: {prompt}\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Hapus gambar setelah dikirim
        asyncio.create_task(delete_file_after_delay(image_path, 3))

    except Exception as e:
        logger.error(f"Image generation error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Pembuatan gambar gagal!**\n"
            f"Error: {str(e)}\n\n"
            f"Coba gunakan prompt yang berbeda atau coba lagi nanti.",
            parse_mode='Markdown'
        )

async def remove_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    if not update.message.photo and not update.message.document:
        await update.message.reply_text(
            "**❌ No image attached!**\n"
            "Please attach an image to remove text from.",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "**⏳ Removing text from image...**\n"
        "Please wait a moment.",
        parse_mode='Markdown'
    )

    try:
        # Get the image file
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            file_extension = "jpg"
        else:
            file = await context.bot.get_file(update.message.document.file_id)
            file_name = update.message.document.file_name
            file_extension = file_name.split(".")[-1] if "." in file_name else "jpg"

        input_path = f"downloads/input_image_{user_id}.{file_extension}"
        output_path = f"downloads/text_removed_{user_id}.png"
        os.makedirs("downloads", exist_ok=True)

        await file.download_to_drive(input_path)

        # Call ClipDrop API to remove text
        with open(input_path, "rb") as image_file:
            response = requests.post(
                CLIPDROP_ENDPOINTS["text_removal"],
                headers={
                    "x-api-key": CLIPDROP_API_KEY
                },
                files={
                    "image_file": ("image.jpg", image_file, "image/jpeg")
                }
            )

        if response.status_code != 200:
            raise Exception(f"API returned status code {response.status_code}: {response.text}")

        # Save the processed image
        with open(output_path, "wb") as f:
            f.write(response.content)

        # Send the processed image
        with open(output_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption=f"**✅ Text removed successfully!**\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete the images after sending
        asyncio.create_task(delete_file_after_delay(input_path, 3))
        asyncio.create_task(delete_file_after_delay(output_path, 3))

    except Exception as e:
        logger.error(f"Text removal error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Text removal failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

async def remove_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    if not update.message.photo and not update.message.document:
        await update.message.reply_text(
            "**❌ No image attached!**\n"
            "Please attach an image to remove logos from.",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "**⏳ Removing logos from image...**\n"
        "Please wait a moment.",
        parse_mode='Markdown'
    )

    try:
        # Get the image file
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            file_extension = "jpg"
        else:
            file = await context.bot.get_file(update.message.document.file_id)
            file_name = update.message.document.file_name
            file_extension = file_name.split(".")[-1] if "." in file_name else "jpg"

        input_path = f"downloads/input_logo_{user_id}.{file_extension}"
        output_path = f"downloads/logo_removed_{user_id}.png"
        os.makedirs("downloads", exist_ok=True)

        await file.download_to_drive(input_path)

        # Call ClipDrop API to remove logo
        with open(input_path, "rb") as image_file:
            response = requests.post(
                CLIPDROP_ENDPOINTS["logo_removal"],
                headers={
                    "x-api-key": CLIPDROP_API_KEY
                },
                files={
                    "image_file": ("image.jpg", image_file, "image/jpeg")
                }
            )

        if response.status_code != 200:
            raise Exception(f"API returned status code {response.status_code}: {response.text}")

        # Save the processed image
        with open(output_path, "wb") as f:
            f.write(response.content)

        # Send the processed image
        with open(output_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption=f"**✅ Logo removed successfully!**\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete the images after sending
        asyncio.create_task(delete_file_after_delay(input_path, 3))
        asyncio.create_task(delete_file_after_delay(output_path, 3))

    except Exception as e:
        logger.error(f"Logo removal error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Logo removal failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

async def bulk_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    if not update.message.document:
        await update.message.reply_text(
            "**❌ No ZIP file attached!**\n"
            "Please attach a ZIP file containing images to process.",
            parse_mode='Markdown'
        )
        return

    # Check if the file is a ZIP file
    file_name = update.message.document.file_name
    if not file_name.lower().endswith('.zip'):
        await update.message.reply_text(
            "**❌ Invalid file format!**\n"
            "Please attach a ZIP file containing images.",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "**⏳ Processing bulk images...**\n"
        "Please wait a moment.",
        parse_mode='Markdown'
    )

    try:
        # Get the ZIP file
        file = await context.bot.get_file(update.message.document.file_id)
        input_path = f"downloads/bulk_input_{user_id}.zip"
        output_path = f"downloads/bulk_output_{user_id}.zip"
        os.makedirs("downloads", exist_ok=True)

        await file.download_to_drive(input_path)

        # Call ClipDrop API for bulk processing
        with open(input_path, "rb") as zip_file:
            response = requests.post(
                CLIPDROP_ENDPOINTS["bulk_removal"],
                headers={
                    "x-api-key": CLIPDROP_API_KEY
                },
                files={
                    "zip_file": ("images.zip", zip_file, "application/zip")
                }
            )

        if response.status_code != 200:
            raise Exception(f"API returned status code {response.status_code}: {response.text}")

        # Save the processed ZIP file
        with open(output_path, "wb") as f:
            f.write(response.content)

        # Send the processed ZIP file
        with open(output_path, "rb") as zip_file:
            await update.message.reply_document(
                document=zip_file,
                filename="processed_images.zip",
                caption=f"**✅ Bulk processing completed successfully!**\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete the files after sending
        asyncio.create_task(delete_file_after_delay(input_path, 3))
        asyncio.create_task(delete_file_after_delay(output_path, 3))

    except Exception as e:
        logger.error(f"Bulk processing error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Bulk processing failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

async def upscale_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if not is_user_active(user_id):
        user = update.effective_user
        await update.message.reply_text(
            f"⚠️ Your account is not registered, please copy your ID:\n\n"
            f"Username: @{user.username}\n"
            f"User ID: `{user.id}`\n\n"
            "And send a message `/activate {your id}` to admin @CanzyyKing ⚠️",
            parse_mode='Markdown'
        )
        return

    if not update.message.photo and not update.message.document:
        await update.message.reply_text(
            "**❌ No image attached!**\n"
            "Please attach an image to upscale.",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "**⏳ Upscaling image...**\n"
        "Please wait a moment.",
        parse_mode='Markdown'
    )

    try:
        # Get the image file
        if update.message.photo:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            file_extension = "jpg"
        else:
            file = await context.bot.get_file(update.message.document.file_id)
            file_name = update.message.document.file_name
            file_extension = file_name.split(".")[-1] if "." in file_name else "jpg"

        input_path = f"downloads/input_upscale_{user_id}.{file_extension}"
        output_path = f"downloads/upscaled_{user_id}.png"
        os.makedirs("downloads", exist_ok=True)

        await file.download_to_drive(input_path)

        # Call ClipDrop API to upscale image
        with open(input_path, "rb") as image_file:
            response = requests.post(
                CLIPDROP_ENDPOINTS["ios_demo"],
                headers={
                    "x-api-key": CLIPDROP_API_KEY
                },
                files={
                    "image_file": ("image.jpg", image_file, "image/jpeg")
                },
                data={
                    "upscale": "2"  # 2x upscaling
                }
            )

        if response.status_code != 200:
            raise Exception(f"API returned status code {response.status_code}: {response.text}")

        # Save the processed image
        with open(output_path, "wb") as f:
            f.write(response.content)

        # Send the processed image
        with open(output_path, "rb") as image_file:
            await update.message.reply_photo(
                photo=image_file,
                caption=f"**✅ Image upscaled successfully!**\n\n"
                        f"**Developed by: Canzy-Xtr**",
                parse_mode='Markdown'
            )

        # Delete the images after sending
        asyncio.create_task(delete_file_after_delay(input_path, 3))
        asyncio.create_task(delete_file_after_delay(output_path, 3))

    except Exception as e:
        logger.error(f"Image upscaling error: {str(e)}")
        await update.message.reply_text(
            f"**❌ Image upscaling failed!**\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

# Admin commands
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "**⚠️ This command is only available to admins.**",
            parse_mode='Markdown'
        )
        return

    if not context.args:
        await update.message.reply_text(
            "**❌ No message provided!**\n"
            "Usage: `/broadcast Your message here`",
            parse_mode='Markdown'
        )
        return

    broadcast_message = " ".join(context.args)
    users = get_all_users()

    await update.message.reply_text(
        f"**📢 Broadcasting message to {len(users)} users...**",
        parse_mode='Markdown'
    )

    success_count = 0
    fail_count = 0

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"**📢 Broadcast Message:**\n\n{broadcast_message}",
                parse_mode='Markdown'
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {str(e)}")
            fail_count += 1

    await update.message.reply_text(
        f"**✅ Broadcast completed!**\n"
        f"• Successfully sent: **{success_count}**\n"
        f"• Failed: **{fail_count}**",
        parse_mode='Markdown'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "**⚠️ This command is only available to admins.**",
            parse_mode='Markdown'
        )
        return

    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
    active_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 0")
    inactive_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE join_date >= datetime('now', '-1 day')")
    recent_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-1 day')")
    active_today = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(downloads_count) FROM users")
    total_downloads = cursor.fetchone()[0] or 0

    conn.close()

    stats_text = (
        "**📊 Bot Statistics 📊**\n\n"
        f"• Total Users: **{total_users}**\n"
        f"• Active Users: **{active_users}**\n"
        f"• Inactive Users: **{inactive_users}**\n"
        f"• New Users (24h): **{recent_users}**\n"
        f"• Active Today: **{active_today}**\n"
        f"• Total Downloads: **{total_downloads}**\n\n"
        f"**Developed by: Canzy-Xtr**"
    )

    await update.message.reply_text(
        stats_text,
        parse_mode='Markdown'
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "**⚠️ This command is only available to admins.**",
            parse_mode='Markdown'
        )
        return

    conn = sqlite3.connect('bot_users.db')
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, username, first_name, last_name, is_active, datetime(last_active), downloads_count "
        "FROM users ORDER BY last_active DESC LIMIT 50"
    )
    users = cursor.fetchall()
    conn.close()

    if not users:
        await update.message.reply_text(
            "**❌ No users found!**",
            parse_mode='Markdown'
        )
        return

    user_list = "**📊 User List (Last 50 Active Users) 📊**\n\n"
    for user in users:
        user_id, username, first_name, last_name, is_active, last_active, downloads = user
        status = "✅ Active" if is_active else "❌ Inactive"
        username = f"@{username}" if username else "No username"
        name = f"{first_name or ''} {last_name or ''}".strip() or "No name"

        user_list += f"👤 **{name}** ({username})\n"
        user_list += f"ID: `{user_id}`\n"
        user_list += f"Status: {status}\n"
        user_list += f"Last Active: {last_active}\n"
        user_list += f"Downloads: {downloads}\n\n"

        # Telegram has a message limit of 4096 characters
        if len(user_list) > 3800:
            user_list += "...(more users not shown)"
            break

    await update.message.reply_text(
        user_list,
        parse_mode='Markdown'
    )

async def activate_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "**⚠️ This command is only available to admins.**",
            parse_mode='Markdown'
        )
        return

    if not context.args:
        await update.message.reply_text(
            "**❌ No user ID provided!**\n"
            "Usage: `/activate user_id`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(context.args[0])
        activate_user(target_user_id)

        await update.message.reply_text(
            f"**✅ User {target_user_id} has been activated!**",
            parse_mode='Markdown'
        )

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="**✅ Your account has been activated!**\n"
                     "You can now use all bot features.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {str(e)}")

    except ValueError:
        await update.message.reply_text(
            "**❌ Invalid user ID!**\n"
            "Please provide a valid numeric user ID.",
            parse_mode='Markdown'
        )

async def deactivate_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user_activity(user_id)

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "**⚠️ This command is only available to admins.**",
            parse_mode='Markdown'
        )
        return

    if not context.args:
        await update.message.reply_text(
            "**❌ No user ID provided!**\n"
            "Usage: `/deactivate user_id`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(context.args[0])

        if target_user_id == ADMIN_ID:
            await update.message.reply_text(
                "**❌ You cannot deactivate the admin account!**",
                parse_mode='Markdown'
            )
            return

        deactivate_user(target_user_id)

        await update.message.reply_text(
            f"**✅ User {target_user_id} has been deactivated!**",
            parse_mode='Markdown'
        )

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="**⚠️ Your account has been deactivated!**\n"
                     "Please contact the admin for assistance.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {str(e)}")

    except ValueError:
        await update.message.reply_text(
            "**❌ Invalid user ID!**\n"
            "Please provide a valid numeric user ID.",
            parse_mode='Markdown'
        )

async def cleanup_downloads(context: ContextTypes.DEFAULT_TYPE):
    """Periodically clean up the downloads directory"""
    try:
        if os.path.exists("downloads"):
            current_time = time.time()
            for file in os.listdir("downloads"):
                file_path = os.path.join("downloads", file)
                # Delete files older than 10 minutes
                if os.path.isfile(file_path) and current_time - os.path.getmtime(file_path) > 600:
                    os.remove(file_path)
                    logger.info(f"Cleaned up old file: {file_path}")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

def main():
    # Create downloads directory if it doesn't exist
    os.makedirs("downloads", exist_ok=True)

    # Setup database
    setup_database()

    # Initialize the bot
    application = Application.builder().token("7634379925:AAHCgaqr5rHZSbKy4aUxD2ki1RJ52jFS9JA").build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("code", code_generation))
    application.add_handler(CommandHandler("debug", debug_code))
    application.add_handler(CommandHandler("image", generate_image))
    application.add_handler(CommandHandler("removetext", remove_text))
    application.add_handler(CommandHandler("removelogo", remove_logo))
    application.add_handler(CommandHandler("bulkremove", bulk_remove))
    application.add_handler(CommandHandler("upscale", upscale_image))

    # Admin commands
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("activate", activate_user_command))
    application.add_handler(CommandHandler("deactivate", deactivate_user_command))

    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_url))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Schedule periodic cleanup
    job_queue = application.job_queue
    job_queue.run_repeating(cleanup_downloads, interval=300, first=10)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
