import time
import requests
import json
import random
import re
import threading
import os
from io import BytesIO
from telebot.types import Message
import telebot
from PIL import Image

# ==================== 从环境变量读取凭证 ====================
KIE_API_KEY = os.getenv("KIE_API_KEY", "Bearer YOUR_KIE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_TOKEN")
# ==========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
API_BASE = "https://api.kie.ai/api/v1/jobs"

MODEL = "seedream/5-pro-text-to-image"
MODEL_EDIT = "seedream/5-pro-image-to-image"

VALID_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2"}

def parse_prompt(text: str):
    text = text.strip()
    ratio = "9:16"
    quality = "high"

    found_ratios = re.findall(r'(1:1|3:4|4:3|9:16|16:9|2:3|3:2)', text)
    if found_ratios:
        ratio = found_ratios[-1]
        text = re.sub(r'(1:1|3:4|4:3|9:16|16:9|2:3|3:2)', '', text).strip()

    if re.search(r'标清|basic|low', text, re.IGNORECASE):
        quality = "basic"
        text = re.sub(r'标清|basic|low', '', text, flags=re.IGNORECASE).strip()

    return text, ratio, quality

def create_task(model: str, input_data: dict):
    headers = {
        "Authorization": KIE_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "callBackUrl": "",
        "input": input_data
    }
    resp = requests.post(f"{API_BASE}/createTask", json=payload, headers=headers, timeout=30)
    if resp.status_code == 200:
        return True, resp.json()["data"]["taskId"]
    return False, f"创建失败: {resp.text}"

def get_task_result(task_id: str, max_wait: int = 180):
    headers = {"Authorization": KIE_API_KEY}
    start = time.time()
    while time.time() - start < max_wait:
        try:
            resp = requests.get(f"{API_BASE}/recordInfo?taskId={task_id}", headers=headers, timeout=15)
            data = resp.json().get("data", {})
            state = data.get("state")
            if state == "success":
                result_json = data.get("resultJson")
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                urls = result_json.get("resultUrls", []) if result_json else []
                return True, urls[0] if urls else None
            elif state in ["fail", "failed", "error"]:
                return True, f"生成失败: {data.get('failMsg', '未知错误')}"
            time.sleep(4)
        except Exception as e:
            print(f"[调试] 查询异常: {str(e)}")
            time.sleep(4)
    return True, None

def send_photo_clean(chat_id: int, image_url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(3):
        try:
            img_resp = requests.get(image_url, headers=headers, timeout=40)
            img_resp.raise_for_status()
            img = Image.open(BytesIO(img_resp.content)).convert("RGB")
            max_size = 2048
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.LANCZOS)
            bio = BytesIO()
            img.save(bio, format="JPEG", quality=85, optimize=True)
            bio.seek(0)
            bio.name = "generated.jpg"
            bot.send_photo(chat_id, photo=bio)
            return True
        except Exception as e:
            print(f"[调试] 第{attempt+1}次发送失败: {e}")
            time.sleep(2)
    try:
        bot.send_photo(chat_id, image_url)
        return True
    except Exception as e:
        bot.send_message(chat_id, f"发送失败：{str(e)}")
        return False

def process_text_generation(chat_id, message_id, prompt, ratio, quality):
    wait_msg = bot.send_message(chat_id, "正在生成中...", reply_to_message_id=message_id)
    try:
        input_data = {
            "prompt": prompt,
            "aspect_ratio": ratio,
            "quality": quality,
            "nsfw_checker": False
        }
        success, result = create_task(MODEL, input_data)
        if not success:
            bot.edit_message_text(f"创建失败：{result}", wait_msg.chat.id, wait_msg.message_id)
            return
        success, image_url = get_task_result(result) if isinstance(result, str) else (False, None)
        if image_url:
            send_photo_clean(chat_id, image_url)
            bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        else:
            bot.edit_message_text("生成完成但未获取到图片", wait_msg.chat.id, wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"异常：{str(e)}", wait_msg.chat.id, wait_msg.message_id)

@bot.message_handler(content_types=['text'])
def handle_text(message: Message):
    prompt, ratio, quality = parse_prompt(message.text)
    if not prompt:
        return
    threading.Thread(
        target=process_text_generation,
        args=(message.chat.id, message.message_id, prompt, ratio, quality),
        daemon=True
    ).start()

def process_photo_generation(chat_id, message_id, prompt, ratio, quality, image_url):
    wait_msg = bot.send_message(chat_id, "正在生成中...", reply_to_message_id=message_id)
    try:
        input_data = {
            "prompt": prompt,
            "image_urls": [image_url],
            "aspect_ratio": ratio,
            "quality": quality,
            "nsfw_checker": False
        }
        success, result = create_task(MODEL_EDIT, input_data)
        if not success:
            bot.edit_message_text(f"创建失败：{result}", wait_msg.chat.id, wait_msg.message_id)
            return
        success, result_url = get_task_result(result) if isinstance(result, str) else (False, None)
        if result_url:
            send_photo_clean(chat_id, result_url)
            bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        else:
            bot.edit_message_text("生成完成但未获取到图片", wait_msg.chat.id, wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"图生图失败：{str(e)}", wait_msg.chat.id, wait_msg.message_id)

@bot.message_handler(content_types=['photo'])
def handle_photo(message: Message):
    if not message.caption:
        bot.reply_to(message, "请在图片下方输入描述（Caption）")
        return
    caption = message.caption.strip()
    prompt, ratio, quality = parse_prompt(caption)
    file_info = bot.get_file(message.photo[-1].file_id)
    image_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
    threading.Thread(
        target=process_photo_generation,
        args=(message.chat.id, message.message_id, prompt, ratio, quality, image_url),
        daemon=True
    ).start()

if __name__ == "__main__":
    print("Seedream 5 Pro 机器人已启动")
    bot.infinity_polling()
