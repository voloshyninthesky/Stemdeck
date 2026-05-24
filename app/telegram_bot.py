"""Stemdeck Telegram Bot.

Accepts audio files or YouTube links, runs stem separation through the existing
Celery pipeline, and sends back the separated tracks with a mixer WebApp button.

Run:  python -m app.telegram_bot
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import html
from pathlib import Path
from typing import BinaryIO, Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from app import config, db, storage
from app.tasks import process_job
from app.processing import convert_wav_to_mp3

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("stemdeck.bot")

YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]+",
    re.IGNORECASE,
)

ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
    ".mp4", ".mkv", ".avi", ".mov",
}

MAX_TELEGRAM_FILE_SIZE = 20 * 1024 * 1024  # Telegram bot API download limit


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """Sanitize filename by replacing directory separators and other unsafe characters."""
    # Replace slashes and other unsafe symbols with hyphens
    sanitized = re.sub(r'[\\/*?:"<>|]', "-", name)
    # Remove leading/trailing spaces or dots
    sanitized = sanitized.strip().strip(".")
    return sanitized or "Track"


def _get_or_create_user(chat_id: int) -> dict:
    """Return a DB user for this Telegram chat, creating one if needed."""
    username = f"tg_{chat_id}"
    # Try to find the existing user
    from app.db import _connect, _row_to_dict
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, is_guest, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    user = _row_to_dict(row)
    if user:
        return user

    # Create a new bot user
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_guest, created_at) VALUES (?, '', 1, ?)",
            (username, now),
        )
        row = conn.execute(
            "SELECT id, username, is_guest, created_at FROM users WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    user = _row_to_dict(row)
    if not user:
        raise RuntimeError("Failed to create Telegram bot user")
    return user


def _build_mixer_url(job_id: str) -> str:
    from app.main import generate_mixer_token
    token = generate_mixer_token(job_id)
    return f"{config.TELEGRAM_WEBAPP_BASE_URL}/mixer?job_id={job_id}&token={token}"


def _enqueue_job(job_id: str) -> None:
    """Enqueue via Celery, fall back to synchronous execution."""
    import threading
    try:
        process_job.delay(job_id)
    except Exception:
        logger.warning("Celery unavailable, running job %s synchronously", job_id)
        thread = threading.Thread(target=process_job.run, args=(job_id,), daemon=True)
        thread.start()


def _translate_detail(detail: str, lang: str) -> str:
    """Translate dynamic task logging details into Ukrainian if language matches."""
    if lang != "uk":
        return detail
    translations = {
        "Downloading audio from YouTube": "Завантаження аудіо з YouTube",
        "Your file is processing. You can close this page.": "Ваш файл обробляється. Ви можете закрити цю сторінку.",
        "Converting to WAV": "Конвертація у WAV",
        "Running Demucs quality separation": "Запуск високоякісного розділення Demucs",
        "Uploading vocals to storage": "Завантаження вокалу у сховище",
        "Uploading instrumental to storage": "Завантаження інструменталу у сховище",
        "Uploading stems to storage": "Завантаження розділених треків у сховище",
        "Ready": "Готово",
        "Failed": "Помилка обробки",
    }
    return translations.get(detail, detail)


async def _poll_job(status_msg, job_id: str, user_id: int, timeout: int = 600, lang: str = "en") -> dict:
    """Poll the DB until the job is done or failed, updating the Telegram status message."""
    elapsed = 0
    interval = 3
    last_text = ""
    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval
        job = db.get_job(job_id, user_id)
        if not job:
            raise RuntimeError("Job disappeared from DB")
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            error_msg = job.get("error") or "Separation failed"
            if lang == "uk":
                error_msg = "Помилка розділення"
            raise RuntimeError(error_msg)

        # Format status message using HTML
        if job["status"] == "queued":
            pos = db.queue_position(job_id)
            if lang == "uk":
                pos_text = f" (Позиція в черзі: #{pos})" if pos else ""
                text = f"⏳ <b>Очікування в черзі…</b>{pos_text}"
            else:
                pos_text = f" (Position in queue: #{pos})" if pos else ""
                text = f"⏳ <b>Waiting in queue…</b>{pos_text}"
        else: # processing
            detail_raw = job.get("message", "Processing...")
            detail = html.escape(_translate_detail(detail_raw, lang))
            if lang == "uk":
                text = (
                    f"🎶 <b>Розділення аудіо…</b>\n\n"
                    f"⏳ <i>{detail}… Будь ласка, зачекайте.</i>"
                )
            else:
                text = (
                    f"🎶 <b>Separating audio…</b>\n\n"
                    f"⏳ <i>{detail}… Please wait.</i>"
                )

        if text != last_text:
            try:
                await status_msg.edit_text(text, parse_mode="HTML")
                last_text = text
            except Exception:
                pass

        # Increase interval after a while to reduce DB load
        if elapsed > 30:
            interval = 5
    raise RuntimeError("Processing timed out after 10 minutes" if lang != "uk" else "Час очікування обробки вичерпано (10 хвилин)")


async def _send_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job: dict,
    lang: str = "en",
) -> None:
    """Send the separated stems and the mixer button."""
    chat_id = update.effective_chat.id

    # Resolve local paths to stem files
    vocals_path = Path(job.get("vocals_path") or "")
    inst_path = Path(job.get("instrumental_path") or "")

    # If local files aren't available but we have object storage keys,
    # download from storage to a temp location
    if not vocals_path.exists() and job.get("vocals_key") and storage.is_object_storage_enabled():
        job_dir = Path(job["job_dir"])
        exports = job_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        suffix = ".mp3" if job["vocals_key"].endswith(".mp3") else ".wav"
        vocals_path = exports / f"vocals{suffix}"
        storage.client().fget_object(config.STORAGE_BUCKET, job["vocals_key"], str(vocals_path))

    if not inst_path.exists() and job.get("instrumental_key") and storage.is_object_storage_enabled():
        job_dir = Path(job["job_dir"])
        exports = job_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        suffix = ".mp3" if job["instrumental_key"].endswith(".mp3") else ".wav"
        inst_path = exports / f"instrumental{suffix}"
        storage.client().fget_object(config.STORAGE_BUCKET, job["instrumental_key"], str(inst_path))

    # Convert to MP3 for compact and native audio Telegram delivery (only if it is a legacy WAV file)
    try:
        vocals_mp3 = convert_wav_to_mp3(vocals_path) if vocals_path.suffix == ".wav" else vocals_path
        inst_mp3 = convert_wav_to_mp3(inst_path) if inst_path.suffix == ".wav" else inst_path
    except Exception as exc:
        logger.error("MP3 conversion failed: %s", exc)
        # Fall back
        vocals_mp3 = vocals_path
        inst_mp3 = inst_path

    track_name = job.get("original_filename", "Track")
    safe_track_name = _sanitize_filename(track_name)

    # Send instrumental as Document (File)
    inst_file = open(str(inst_mp3), "rb")
    await context.bot.send_document(
        chat_id=chat_id,
        document=inst_file,
        filename=f"{safe_track_name} - Instrumental.mp3",
    )

    # Send mixer button
    mixer_url = _build_mixer_url(job["id"])
    button_label = "🎛 Відкрити мікшер" if lang == "uk" else "🎛 Open Mixer"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            button_label,
            web_app=WebAppInfo(url=mixer_url),
        )]
    ])
    safe_track_name_markdown = escape_markdown(track_name, version=2)
    complete_text = f"🎶 *{safe_track_name_markdown}*"

    await context.bot.send_message(
        chat_id=chat_id,
        text=complete_text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


# ──────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = "uk" if update.effective_user and update.effective_user.language_code and update.effective_user.language_code.startswith("uk") else "en"
    if lang == "uk":
        text = (
            "🎵 *Ласкаво просимо до Stepan Audio\\!*\n\n"
            "Надішліть мені:\n"
            "• Аудіофайл \\(MP3, WAV, FLAC, OGG тощо\\)\n"
            "• Посилання на YouTube\n\n"
            "Я розділю його на *вокал* та *інструментал*, "
            "і надам мікшер для їхнього змішування\\! 🎛"
        )
    else:
        text = (
            "🎵 *Welcome to Stepan Audio\\!*\n\n"
            "Send me:\n"
            "• An audio file \\(MP3, WAV, FLAC, OGG, etc\\.\\)\n"
            "• A YouTube link\n\n"
            "I'll separate it into *vocals* and *instrumental* tracks, "
            "and give you a mixer to blend them\\! 🎛"
        )
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
    )


async def audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle audio files, voice messages, and documents with audio extensions."""
    message = update.message
    chat_id = message.chat_id
    lang = "uk" if update.effective_user and update.effective_user.language_code and update.effective_user.language_code.startswith("uk") else "en"

    # Determine the file to download
    if message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        file_size = message.audio.file_size or 0
    elif message.voice:
        file_id = message.voice.file_id
        file_name = "voice.ogg"
        file_size = message.voice.file_size or 0
    elif message.document:
        doc = message.document
        ext = Path(doc.file_name or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            supported = ", ".join(sorted(ALLOWED_EXTENSIONS))
            if lang == "uk":
                err_text = f"❌ Непідтримуваний тип файлу `{ext}`.\nПідтримуються: {supported}"
            else:
                err_text = f"❌ Unsupported file type `{ext}`.\nSupported: {supported}"
            await message.reply_text(err_text, parse_mode="Markdown")
            return
        file_id = doc.file_id
        file_name = doc.file_name or "file"
        file_size = doc.file_size or 0
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        file_size = message.video.file_size or 0
    else:
        return

    if file_size > MAX_TELEGRAM_FILE_SIZE:
        if lang == "uk":
            err_size = (
                "❌ Файл занадто великий. Telegram дозволяє ботам завантажувати файли лише до 20 МБ.\n"
                "Будь ласка, надішліть посилання на YouTube або стисніть файл."
            )
        else:
            err_size = (
                "❌ File is too large. Telegram allows bots to download files up to 20 MB.\n"
                "Please use a YouTube link instead, or compress the file."
            )
        await message.reply_text(err_size)
        return

    status_text = "⏳ Завантажую ваш файл…" if lang == "uk" else "⏳ Downloading your file…"
    status_msg = await message.reply_text(status_text)

    try:
        db.init_db()
        user = _get_or_create_user(chat_id)

        # Check rate limit: 2 separations per 5 minutes
        job_count = db.count_user_jobs_since(user["id"], minutes=5)
        if job_count >= 2:
            if lang == "uk":
                await status_msg.edit_text(
                    "❌ Досягнуто ліміту запитів: дозволено не більше 2 розділень на 5 хвилин.\n"
                    "Будь ласка, зачекайте кілька хвилин перед наступною спробою."
                )
            else:
                await status_msg.edit_text(
                    "❌ Rate limit exceeded: maximum 2 separations per 5 minutes are allowed.\n"
                    "Please wait a few minutes before trying again."
                )
            return
        import uuid
        job_id = str(uuid.uuid4())
        job_dir = config.JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        # Download from Telegram
        tg_file = await context.bot.get_file(file_id)
        local_path = input_dir / Path(file_name).name
        await tg_file.download_to_drive(str(local_path))

        # Store input in object storage
        input_key = storage.put_file(local_path, f"{job_id}/input/{local_path.name}")

        job = db.create_job(
            job_id=job_id,
            user_id=user["id"],
            original_filename=Path(file_name).stem,
            input_path=local_path,
            job_dir=job_dir,
            input_key=input_key,
            separation_mode="quality",
        )

        separating_text = "🎶 Розділяю вокал та інструментал… Це може зайняти кілька хвилин." if lang == "uk" else "🎶 Separating vocals and instrumental… This may take a few minutes."
        await status_msg.edit_text(separating_text)
        _enqueue_job(job_id)

        done_job = await _poll_job(status_msg, job_id, user["id"], lang=lang)
        await status_msg.delete()
        await _send_results(update, context, done_job, lang=lang)

    except Exception as exc:
        logger.exception("Audio processing failed for chat %s", chat_id)
        fail_text = "❌ Обробка файлу завершилась помилкою" if lang == "uk" else f"❌ Processing failed: {exc}"
        try:
            await status_msg.edit_text(fail_text)
        except Exception:
            await message.reply_text(fail_text)


async def youtube_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages containing YouTube links."""
    message = update.message
    chat_id = message.chat_id
    text = message.text or ""
    lang = "uk" if update.effective_user and update.effective_user.language_code and update.effective_user.language_code.startswith("uk") else "en"

    match = YOUTUBE_RE.search(text)
    if not match:
        return

    url = match.group(0)
    if not url.startswith("http"):
        url = "https://" + url

    status_text = "⏳ Завантажую з YouTube…" if lang == "uk" else "⏳ Downloading from YouTube…"
    status_msg = await message.reply_text(status_text)

    try:
        db.init_db()
        user = _get_or_create_user(chat_id)

        # Check rate limit: 2 separations per 5 minutes
        job_count = db.count_user_jobs_since(user["id"], minutes=5)
        if job_count >= 2:
            if lang == "uk":
                await status_msg.edit_text(
                    "❌ Досягнуто ліміту запитів: дозволено не більше 2 розділень на 5 хвилин.\n"
                    "Будь ласка, зачекайте кілька хвилин перед наступною спробою."
                )
            else:
                await status_msg.edit_text(
                    "❌ Rate limit exceeded: maximum 2 separations per 5 minutes are allowed.\n"
                    "Please wait a few minutes before trying again."
                )
            return
        import uuid
        job_id = str(uuid.uuid4())
        job_dir = config.JOBS_DIR / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        job = db.create_job(
            job_id=job_id,
            user_id=user["id"],
            original_filename="YouTube Video",
            input_path=url,
            job_dir=job_dir,
            input_key="",
            separation_mode="quality",
        )

        separating_text = "🎶 Завантажую та розділяю… Це може зайняти кілька хвилин." if lang == "uk" else "🎶 Downloading & separating… This may take a few minutes."
        await status_msg.edit_text(separating_text)
        _enqueue_job(job_id)

        done_job = await _poll_job(status_msg, job_id, user["id"], lang=lang)
        await status_msg.delete()
        await _send_results(update, context, done_job, lang=lang)

    except Exception as exc:
        logger.exception("YouTube processing failed for chat %s", chat_id)
        fail_text = "❌ Обробка файлу завершилась помилкою" if lang == "uk" else f"❌ Processing failed: {exc}"
        try:
            await status_msg.edit_text(fail_text)
        except Exception:
            await message.reply_text(fail_text)


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized text messages."""
    text_raw = (update.message.text or "").strip()
    if not text_raw:
        return

    # Don't respond to YouTube links (handled by youtube_handler)
    if YOUTUBE_RE.search(text_raw):
        return

    lang = "uk" if update.effective_user and update.effective_user.language_code and update.effective_user.language_code.startswith("uk") else "en"
    if lang == "uk":
        reply = (
            "🤔 Я не зрозумів цього повідомлення.\n\n"
            "Надішліть мені аудіофайл або посилання на YouTube, "
            "і я розділю його на вокал та інструментал!"
        )
    else:
        reply = (
            "🤔 I didn't understand that.\n\n"
            "Send me an audio file or a YouTube link, "
            "and I'll separate it into vocal and instrumental tracks!"
        )

    await update.message.reply_text(reply)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Exiting.")
        sys.exit(1)

    db.init_db()
    storage.ensure_bucket()

    app = ApplicationBuilder().token(token).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))

    # Audio files — audio, voice, video, and documents
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.VIDEO | filters.Document.ALL,
        audio_handler,
    ))

    # YouTube links in text messages
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(YOUTUBE_RE),
        youtube_handler,
    ))

    # Fallback for unknown text
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        unknown_handler,
    ))

    logger.info("Stemdeck Telegram bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
