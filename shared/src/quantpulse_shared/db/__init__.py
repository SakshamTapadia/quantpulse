"""Shared DB helpers - DSN builder and health check."""
import asyncpg

async def check_db(dsn: str) -> bool:
    try:
        conn = await asyncpg.connect(dsn)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False
