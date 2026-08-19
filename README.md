# Telegram Kie.ai Bots

Private repository containing two Telegram bots for Kie.ai image generation.

## Bots included

1. **seedream5pro_bot.py** - Seedream 5 Pro (Text-to-Image + Image-to-Image)
2. **gpt_image2_bot.py** - GPT Image 2 (Text-to-Image + Image-to-Image with official file upload)

## How to deploy (Railway / Render)

1. Connect this GitHub repository to Railway or Render
2. Set environment variables:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `KIE_API_KEY` = Bearer your_kie_key
3. Set the start command to the bot you want, for example:
   - `python seedream5pro_bot.py`
   - or `python gpt_image2_bot.py`

## Notes

- Both bots support concurrent generation
- GPT Image 2 bot uploads images to Kie official file server before image-to-image
- Do not commit real tokens into the code. Use environment variables.
