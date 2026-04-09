"""
FastAPI 應用程式入口
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from taiwan_discounts.api.routes import router, _refresh_cache

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時自動爬取一次
    import asyncio
    asyncio.create_task(_refresh_cache())
    yield


app = FastAPI(
    title="台灣支付優惠聚合器",
    description="自動爬取 Hami Point、悠游付、Line Pay 的高價值優惠",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)

# 靜態檔案
static_dir = os.path.join(os.path.dirname(__file__), "api", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
