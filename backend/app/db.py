from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import BASE_DIR, DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)

# baseline 迁移的 revision（首个）。老库（旧 create_all 建、未纳管 alembic）启动时先标到这里，
# 再 upgrade，避免 baseline 迁移在已存在的表上重复 CREATE 而报错。baseline 永不变，故写死。
BASELINE_REV = "aec98a2da8c1"


# SQLite 并发：开 WAL（读写不互斥、多读一写）+ busy_timeout（写锁竞争时等而非立刻报 locked）。
# M1 缓解 R2「同步阻塞 + SQLite 并发丢写」的一半（另一半是会话级锁，见 D4-5）。
@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    if engine.dialect.name != "sqlite":
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """启动时把库迁到最新（alembic upgrade head），取代裸 create_all。

    三种库都能正确处理：
    - 全新空库 → 跑 baseline + 后续全部迁移，从零建全表。
    - 老库（旧 create_all 建、无 alembic_version）→ 先标到 baseline，再只应用 baseline 之后的迁移
      （如 updated_at），不会在已存在的表上重复建表。
    - 已纳管的库 → 只应用尚未跑过的新迁移。
    alembic 出任何意外 → 退回 create_all 兜底建表，保证服务至少能启动。
    """
    from . import models  # noqa: F401  注册所有表到 Base.metadata
    from sqlalchemy import inspect
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BASE_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
        tables = set(inspect(engine).get_table_names())
        if tables and "alembic_version" not in tables:
            command.stamp(cfg, BASELINE_REV)   # 老库：已含 baseline 的表，标到 baseline
        command.upgrade(cfg, "head")
    except Exception:
        Base.metadata.create_all(engine)       # 兜底：至少把全表建出来，服务能起
