import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.providers import ProvidersManager
from app.config.settings import SettingsManager
from app.config.fallback import FallbackManager
from app.services.tester import TesterService
from app.services.router import RouterService
from app.services.fallback_handler import FallbackHandler
from app.models.database import init_db
from app.web.routes_api import router as api_router, init as init_api
from app.web.routes_ui import router as ui_router, init as init_ui
from app.web.routes_stats import router as stats_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# 全局实例
providers_mgr = ProvidersManager()
settings_mgr = SettingsManager()
fallback_mgr = FallbackManager()
tester = TesterService(providers_mgr, settings_mgr)
router_svc = RouterService(providers_mgr, settings_mgr)
fallback_handler = FallbackHandler(fallback_mgr)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    await init_db()
    await tester.start_scheduler()
    logger.info("服务启动完成")
    yield
    # 关闭时
    await tester.stop_scheduler()
    logger.info("服务已关闭")


app = FastAPI(
    title="模型中转服务",
    description="跨平台模型中转服务，支持定时测速和智能路由",
    version="1.0.0",
    lifespan=lifespan
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 初始化路由依赖
init_api(router_svc, providers_mgr, settings_mgr, fallback_handler)
init_ui(providers_mgr, settings_mgr, tester, fallback_mgr)

# 注册路由
app.include_router(api_router)
app.include_router(ui_router)
app.include_router(stats_router)


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/providers")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
