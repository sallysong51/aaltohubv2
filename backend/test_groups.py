import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel, PeerChat, Chat, Channel
from app.config import settings
from app.encryption import session_encryption
from supabase import create_client

db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
session_resp = db.table("telethon_sessions").select("session_data").eq("user_id", 1).execute()
session_string = session_encryption.decrypt(session_resp.data[0]["session_data"])

async def main():
    client = TelegramClient(
        StringSession(session_string),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
        use_ipv6=False,
    )
    await client.connect()
    me = await client.get_me()
    print(f"Connected as: {me.first_name}")

    print("\n=== GROUPS/CHANNELS ===")
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Chat, Channel)):
            etype = "channel" if isinstance(entity, Channel) else "chat"
            mega = getattr(entity, "megagroup", False)
            print(f"id={entity.id} type={etype} mega={mega} title={entity.title}")

    for gid in [5166796952, 5045770023]:
        print(f"\n--- gid={gid} ---")
        try:
            e = await client.get_entity(PeerChannel(channel_id=gid))
            print(f"PeerChannel OK: {e.title}")
        except Exception as ex:
            print(f"PeerChannel FAIL: {ex}")

    await client.disconnect()

asyncio.run(main())
