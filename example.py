from nicegui import ui
import aiofiles

async def handle_upload(event):
    data = await event.read()
    filename = event.name
    print(f"Received {filename} ({len(data)} bytes)")

    async with aiofiles.open(f"/tmp/{filename}", "wb") as f:
        await f.write(data)

    ui.notify(f"{filename} uploaded successfully!")  # ✅ show message in browser

ui.upload(on_upload=handle_upload)
ui.run(host='0.0.0.0', port=8080)
