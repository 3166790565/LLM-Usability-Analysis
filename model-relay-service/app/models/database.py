import aiosqlite
import os
from contextlib import asynccontextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runtime", "test_results.db")


@asynccontextmanager
async def get_db():
    db = aiosqlite.connect(DB_PATH)
    async with db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id TEXT NOT NULL,
                provider_name TEXT,
                model_id TEXT NOT NULL,
                alias_name TEXT,
                key_id TEXT,
                latency_ms REAL,
                success INTEGER DEFAULT 0,
                error_message TEXT,
                request_body TEXT,
                response_body TEXT,
                tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 兼容旧表，新增列
        for col in ["request_body", "response_body"]:
            try:
                await db.execute(f"ALTER TABLE test_results ADD COLUMN {col} TEXT")
            except aiosqlite.OperationalError:
                pass  # 列已存在
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tested_at ON test_results(tested_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_model_id ON test_results(model_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alias_name ON test_results(alias_name)")
        await db.commit()
