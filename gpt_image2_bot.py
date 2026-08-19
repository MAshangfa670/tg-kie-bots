import time
import requests
import json
import base64
import threading
import os
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# -------------------------- 从环境变量读取配置 --------------------------
KIE_API_KEY = os.getenv("KIE_API_KEY", "Bearer YOUR_KIE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_TOKEN")

API_BASE = "https://api.kie.ai"
CREATE_TASK_URL = f"{API_BASE}/api/v1/jobs/createTask"
GET_TASK_URL = f"{API_BASE}/api/v1/jobs/recordInfo"
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"

HEADERS = {
    "Authorization": KIE_API_KEY,
    "Content-Type": "application/json"
}

tg_bot = Bot(token=TELEGRAM_BOT_TOKEN)

def upload_image_to_kie(image_bytes: bytes, filename: str = "telegram_image.jpg"):
    try:
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "base64Data": f"data:image/jpeg;base64,{base64_data}",
            "uploadPath": "images/telegram",
            "fileName": filename
        }
        resp = requests.post(UPLOAD_URL, headers=HEADERS, json=payload, timeout=30)
        result = resp.json()
        if result.get("code") == 200 or result.get("success"):
            data = result.get("data", {})
            return data.get("downloadUrl") or data.get("fileUrl")
        else:
            print(f"上传失败: {result}")
            return None
    except Exception as e:
        print(f"上传图片异常: {e}")
        return None

def create_task(prompt_text, image_url=None):
    if image_url:
        model = "gpt-image-2-image-to-image"
        input_data = {
            "prompt": prompt_text,
            "input_urls": [image_url],
            "aspect_ratio": "auto",
            "nsfw_checker": False
        }
    else:
        model = "gpt-image-2-text-to-image"
        input_data = {
            "prompt": prompt_text,
            "aspect_ratio": "auto",
            "nsfw_checker": False
        }

    payload = {
        "model": model,
        "callBackUrl": "",
        "input": input_data
    }

    try:
        response = requests.post(CREATE_TASK_URL, headers=HEADERS, json=payload, timeout=20)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 200:
            return result["data"]["taskId"]
        else:
            print(f"创建任务失败: {result.get('msg')}")
            return None
    except Exception as e:
        print(f"创建任务出错: {e}")
        return None

def get_task_result(task_id):
    try:
        response = requests.get(f"{GET_TASK_URL}?taskId={task_id}", headers=HEADERS, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"查询任务出错: {e}")
        return None

def process_and_send(chat_id, message_id, task_id):
    if not task_id:
        tg_bot.send_message(chat_id, "创建任务失败，请稍后再试", reply_to_message_id=message_id)
        return

    max_wait = 360
    start_time = time.time()
    check_interval = 3

    while time.time() - start_time < max_wait:
        result = get_task_result(task_id)
        if not result or result.get("code") != 200:
            time.sleep(check_interval)
            continue

        task_data = result.get("data", {})
        state = task_data.get("state")

        if state == "success":
            try:
                result_json = task_data.get("resultJson")
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                urls = result_json.get("resultUrls", []) if result_json else []
                if not urls:
                    tg_bot.send_message(chat_id, "生成成功但未返回图片链接", reply_to_message_id=message_id)
                    return
                img_url = urls[0]
                img_data = requests.get(img_url, timeout=30).content
                tg_bot.send_photo(chat_id, photo=img_data, reply_to_message_id=message_id)
                return
            except Exception as e:
                tg_bot.send_message(chat_id, f"发送失败: {str(e)}", reply_to_message_id=message_id)
                return

        elif state in ["fail", "failed", "error"]:
            fail_msg = task_data.get("failMsg") or "未知错误"
            tg_bot.send_message(chat_id, f"生成失败: {fail_msg}", reply_to_message_id=message_id)
            return

        time.sleep(check_interval)

    tg_bot.send_message(chat_id, "生成超时，请稍后再试", reply_to_message_id=message_id)

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    chat_id = message.chat_id
    message_id = message.message_id

    if message.photo and message.caption:
        prompt = message.caption
        photo = message.photo[-1]
        file = context.bot.get_file(photo.file_id)
        image_bytes = file.download_as_bytearray()

        message.reply_text("正在上传图片并生成，请稍等...")
        kie_image_url = upload_image_to_kie(image_bytes)
        if not kie_image_url:
            message.reply_text("图片上传到 Kie 失败，请稍后再试")
            return

        threading.Thread(
            target=process_and_send,
            args=(chat_id, message_id, create_task(prompt, kie_image_url)),
            daemon=True
        ).start()

    elif message.text:
        prompt = message.text
        message.reply_text("正在生成图片，请稍等...")
        threading.Thread(
            target=process_and_send,
            args=(chat_id, message_id, create_task(prompt)),
            daemon=True
        ).start()

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "机器人已启动\n"
        "• 直接发文字 = 文生图\n"
        "• 发图片 + 描述 = 图生图\n\n"
        "支持并发生成"
    )

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text | Filters.photo, handle_message))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
