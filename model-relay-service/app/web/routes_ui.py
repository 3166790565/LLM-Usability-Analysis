import logging
import json
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import os
import socket as _socket

from app.config.providers import ProvidersManager
from app.config.settings import SettingsManager
from app.config.fallback import FallbackManager
from app.services.tester import TesterService
from app.models.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

_providers_mgr: ProvidersManager = None
_settings_mgr: SettingsManager = None
_tester: TesterService = None
_fallback_mgr: FallbackManager = None


def init(
    providers_mgr: ProvidersManager,
    settings_mgr: SettingsManager,
    tester: TesterService,
    fallback_mgr: FallbackManager = None
):
    global _providers_mgr, _settings_mgr, _tester, _fallback_mgr
    _providers_mgr = providers_mgr
    _settings_mgr = settings_mgr
    _tester = tester
    _fallback_mgr = fallback_mgr


# --- Provider Management ---
@router.get("/ui/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    providers = _providers_mgr.get_all_providers()
    return templates.TemplateResponse(
        "providers.html",
        {"request": request, "providers": providers}
    )


@router.post("/ui/providers/add")
async def add_provider(
    name: str = Form(...),
    url: str = Form(...),
    service_type: str = Form("openai"),
    remark: str = Form(""),
    api_keys_json: str = Form("[]"),
    models_json: str = Form("[]")
):
    try:
        api_keys = json.loads(api_keys_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="API Keys 格式无效")
    try:
        models = json.loads(models_json)
    except json.JSONDecodeError:
        models = []
    provider = {
        "name": name,
        "url": url,
        "service_type": service_type,
        "api_keys": api_keys,
        "models": models,
        "remark": remark
    }
    result = _providers_mgr.add_provider(provider)
    # 保存别名
    for m in models:
        alias = m.get("alias", "").strip()
        if alias:
            _providers_mgr.set_alias(alias, m["id"])
    return RedirectResponse(url="/ui/providers", status_code=303)


@router.post("/ui/providers/edit/{provider_id}")
async def edit_provider(
    provider_id: str,
    name: str = Form(...),
    url: str = Form(...),
    service_type: str = Form("openai"),
    remark: str = Form(""),
    api_keys_json: str = Form("[]"),
    models_json: str = Form("[]")
):
    try:
        api_keys = json.loads(api_keys_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="API Keys 格式无效")
    try:
        models = json.loads(models_json)
    except json.JSONDecodeError:
        models = []
    updates = {
        "name": name,
        "url": url,
        "service_type": service_type,
        "api_keys": api_keys,
        "models": models,
        "remark": remark
    }
    result = _providers_mgr.update_provider(provider_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="中转站不存在")
    # 更新别名
    for m in models:
        alias = m.get("alias", "").strip()
        if alias:
            _providers_mgr.set_alias(alias, m["id"])
    return RedirectResponse(url="/ui/providers", status_code=303)


@router.post("/ui/providers/delete/{provider_id}")
async def delete_provider(provider_id: str):
    _providers_mgr.delete_provider(provider_id)
    return RedirectResponse(url="/ui/providers", status_code=303)


# --- Model Management ---
@router.get("/ui/models", response_class=HTMLResponse)
async def models_page(request: Request):
    providers = _providers_mgr.get_all_providers()
    provider_groups = []
    seen_providers = {}
    for p in providers:
        if p["id"] not in seen_providers:
            seen_providers[p["id"]] = {
                "provider_id": p["id"],
                "provider_name": p["name"],
                "models": []
            }
            provider_groups.append(seen_providers[p["id"]])
        for m in p.get("models", []):
            alias = _providers_mgr.get_alias(m["id"]) or m.get("alias", "")
            seen_providers[p["id"]]["models"].append({
                "id": m["id"],
                "enabled": m.get("enabled", False),
                "alias": m.get("alias", "") or "",
                "alias_name": alias
            })
    return templates.TemplateResponse(
        "models.html",
        {"request": request, "provider_groups": provider_groups}
    )


@router.post("/ui/models/update/{provider_id}")
async def update_models(provider_id: str, request: Request):
    form = await request.form()
    provider = _providers_mgr.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="中转站不存在")

    enabled_raw = form.getlist("enabled")

    existing = {m["id"]: m for m in provider.get("models", [])}
    new_models = []
    for mid, mcfg in existing.items():
        alias_form_key = f"alias_{mid}"
        alias_val = form.get(alias_form_key, "").strip()
        new_models.append({
            "id": mid,
            "enabled": mid in enabled_raw,
            "alias": alias_val
        })
        if alias_val:
            _providers_mgr.set_alias(alias_val, mid)
    _providers_mgr.update_provider(provider_id, {"models": new_models})
    return RedirectResponse(url="/ui/models", status_code=303)


@router.post("/ui/models/fetch/{provider_id}")
async def fetch_models(provider_id: str):
    """从上游拉取模型列表"""
    provider = _providers_mgr.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="中转站不存在")
    if not provider.get("api_keys"):
        raise HTTPException(status_code=400, detail="请先添加 API Key")

    timeout = _settings_mgr.get("request_timeout_seconds", 30)
    from app.services.provider_client import ProviderClient
    client = ProviderClient(provider["url"], provider["api_keys"][0]["key"], timeout,
                            service_type=provider.get("service_type", "openai"))
    try:
        models = await client.list_models()
        model_ids = [m["id"] for m in models]
        existing = {m["id"]: m.get("enabled", True) for m in provider.get("models", [])}
        new_models = []
        for mid in model_ids:
            new_models.append({
                "id": mid,
                "enabled": existing.get(mid, True)
            })
        _providers_mgr.update_provider(provider_id, {"models": new_models})
        return JSONResponse({"success": True, "models": model_ids})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"拉取模型列表失败: {str(e)}")


@router.post("/ui/providers/inline-fetch-models")
async def inline_fetch_models(request: Request):
    """从临时 URL 和 Key 拉取模型列表（用于添加中转站时）"""
    form = await request.form()
    url = form.get("url", "")
    api_key = form.get("api_key", "")
    if not url or not api_key:
        return JSONResponse({"success": False, "models": [], "error": "请先填写 URL 和 API Key"})
    timeout = _settings_mgr.get("request_timeout_seconds", 30)
    from app.services.provider_client import ProviderClient
    client = ProviderClient(url, api_key, timeout,
                            service_type=form.get("service_type", "openai"))
    try:
        models = await client.list_models()
        model_ids = [m["id"] for m in models]
        return JSONResponse({"success": True, "models": model_ids})
    except Exception as e:
        return JSONResponse({"success": False, "models": [], "error": str(e)})


# --- Alias Management ---
@router.get("/ui/aliases", response_class=HTMLResponse)
async def aliases_page_redirect():
    return RedirectResponse(url="/ui/models")


@router.post("/ui/aliases/add")
async def add_alias_redirect():
    return RedirectResponse(url="/ui/models")


@router.post("/ui/aliases/delete/{alias_name}")
async def delete_alias_redirect():
    return RedirectResponse(url="/ui/models")


# --- Test Control ---
@router.get("/ui/test", response_class=HTMLResponse)
async def test_page(request: Request):
    is_running = _tester.is_running() if _tester else False
    recent_results = []
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT id, provider_name, model_id, alias_name, latency_ms, success, error_message, tested_at
            FROM test_results
            ORDER BY tested_at DESC LIMIT 50"""
        )
        rows = await cursor.fetchall()
        for row in rows:
            recent_results.append({
                "id": row["id"],
                "provider_name": row["provider_name"],
                "model_id": row["model_id"],
                "alias_name": row["alias_name"],
                "latency_ms": row["latency_ms"],
                "success": bool(row["success"]),
                "error_message": row["error_message"],
                "tested_at": row["tested_at"]
            })

    return templates.TemplateResponse(
        "test_history.html",
        {
            "request": request,
            "is_running": is_running,
            "results": recent_results,
            "page": "test"
        }
    )


@router.post("/ui/test/run")
async def run_test():
    if _tester:
        await _tester.run_all_tests()
        return JSONResponse({"success": True, "message": "测试已触发"})
    return JSONResponse({"success": False, "message": "测试服务未初始化"})


@router.get("/ui/test/status")
async def test_status():
    return JSONResponse({"running": _tester.is_running() if _tester else False})


@router.get("/ui/test/detail/{result_id}")
async def test_detail(result_id: int):
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT id, provider_name, model_id, alias_name, latency_ms, success,
                      error_message, request_body, response_body, tested_at
            FROM test_results WHERE id = ?""",
            (result_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="记录不存在")
        return JSONResponse({
            "id": row["id"],
            "provider_name": row["provider_name"],
            "model_id": row["model_id"],
            "alias_name": row["alias_name"],
            "latency_ms": row["latency_ms"],
            "success": bool(row["success"]),
            "error_message": row["error_message"],
            "request_body": row["request_body"],
            "response_body": row["response_body"],
            "tested_at": row["tested_at"]
        })


@router.post("/ui/models/test-single")
async def test_single_model(request: Request):
    """对指定模型执行单次测试"""
    form = await request.form()
    provider_id = form.get("provider_id", "")
    model_id = form.get("model_id", "")

    provider = _providers_mgr.get_provider(provider_id)
    if not provider:
        return JSONResponse({"success": False, "error": "中转站不存在"})

    timeout = _settings_mgr.get("request_timeout_seconds", 30)
    test_prompt = _settings_mgr.get("test_prompt", "say hello in world")
    alias = _providers_mgr.get_alias(model_id) or model_id

    results = []
    for key_info in provider.get("api_keys", []):
        from app.services.provider_client import ProviderClient
        client = ProviderClient(provider["url"], key_info["key"], timeout,
                                service_type=provider.get("service_type", "openai"))
        latency, error, request_body, response_body = await client.test_model(model_id, test_prompt)
        success = error is None

        # 保存结果
        async with get_db() as db:
            cursor = await db.execute(
                """INSERT INTO test_results
                (provider_id, provider_name, model_id, alias_name, key_id, latency_ms, success, error_message, request_body, response_body, tested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (provider_id, provider["name"], model_id, alias, key_info["id"],
                 latency, 1 if success else 0, error,
                 request_body, response_body,
                 __import__('datetime').datetime.now().isoformat())
            )
            await db.commit()
            result_id = cursor.lastrowid

        results.append({
            "id": result_id,
            "provider_name": provider["name"],
            "model_id": model_id,
            "alias_name": alias,
            "key_id": key_info["id"],
            "latency_ms": latency,
            "success": success,
            "error_message": error,
            "request_body": request_body,
            "response_body": response_body
        })

    best = min(results, key=lambda r: r["latency_ms"]) if results else None
    return JSONResponse({
        "success": True,
        "results": results,
        "best": best
    })


# --- Test History ---
@router.get("/ui/history", response_class=HTMLResponse)
async def history_page(request: Request, page: int = 1, model: str = ""):
    per_page = 50
    offset = (page - 1) * per_page
    results = []
    total = 0

    async with get_db() as db:
        if model:
            real_id = _providers_mgr.resolve_model_id(model)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM test_results WHERE model_id = ? OR alias_name = ?",
                (real_id, model)
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await db.execute(
                """SELECT * FROM test_results
                WHERE model_id = ? OR alias_name = ?
                ORDER BY tested_at DESC LIMIT ? OFFSET ?""",
                (real_id, model, per_page, offset)
            )
        else:
            cursor = await db.execute("SELECT COUNT(*) FROM test_results")
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await db.execute(
                "SELECT * FROM test_results ORDER BY tested_at DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            )

        rows = await cursor.fetchall()
        for row in rows:
            results.append({
                "id": row["id"],
                "provider_name": row["provider_name"],
                "model_id": row["model_id"],
                "alias_name": row["alias_name"],
                "latency_ms": row["latency_ms"],
                "success": bool(row["success"]),
                "error_message": row["error_message"],
                "tested_at": row["tested_at"]
            })
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        "test_history.html",
        {
            "request": request,
            "results": results,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "filter_model": model,
            "is_running": False,
            "page_type": "history"
        }
    )


# --- Settings ---
@router.get("/ui/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    settings = _settings_mgr.get_all()
    fallback_config = {"enabled": False, "channels": {}}
    if _fallback_mgr:
        fallback_config = _fallback_mgr.get_all_config()

    # 获取所有去重后的模型 ID（所有中转站中已启用的模型）
    all_models = set()
    for p in _providers_mgr.get_all_providers():
        for m in p.get("models", []):
            if m.get("enabled", False):
                all_models.add(m["id"])
    all_models = sorted(all_models)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "fallback_config": fallback_config,
            "all_models": all_models
        }
    )


@router.post("/ui/settings/update")
async def update_settings(
    test_interval_seconds: int = Form(300),
    request_timeout_seconds: int = Form(30),
    max_workers: int = Form(5),
    test_prompt: str = Form("say hello in world"),
    race_timeout_seconds: int = Form(0)
):
    _settings_mgr.update({
        "test_interval_seconds": test_interval_seconds,
        "request_timeout_seconds": request_timeout_seconds,
        "max_workers": max_workers,
        "test_prompt": test_prompt,
        "race_timeout_seconds": race_timeout_seconds
    })
    if _tester:
        await _tester.restart_scheduler()
    return RedirectResponse(url="/ui/settings", status_code=303)


# ========== 兜底机制 API ==========


@router.get("/ui/fallback/config")
async def get_fallback_config():
    """获取兜底机制完整配置"""
    if not _fallback_mgr:
        return JSONResponse({"enabled": False, "channels": {}})
    return JSONResponse(_fallback_mgr.get_all_config())


@router.post("/ui/fallback/toggle")
async def toggle_fallback(enabled: bool = Form(...)):
    """启用/禁用兜底机制"""
    if not _fallback_mgr:
        raise HTTPException(status_code=400, detail="兜底机制未初始化")
    _fallback_mgr.set_enabled(enabled)
    return JSONResponse({"success": True, "enabled": enabled})


@router.post("/ui/fallback/channel")
async def upsert_fallback_channel(request: Request):
    """设置/更新指定模型的兜底渠道"""
    if not _fallback_mgr:
        raise HTTPException(status_code=400, detail="兜底机制未初始化")
    form = await request.form()
    model_alias = form.get("model_alias", "").strip()
    if not model_alias:
        raise HTTPException(status_code=400, detail="模型别名不能为空")

    api_key = form.get("api_key", "").strip()
    api_endpoint = form.get("api_endpoint", "").strip()
    service_type = form.get("service_type", "openai").strip()
    timeout_seconds = int(form.get("timeout_seconds", 30))
    max_retries = int(form.get("max_retries", 2))
    real_model_id = form.get("real_model_id", model_alias).strip()

    # 校验 API Key 格式
    valid, msg = _fallback_mgr.validate_api_key_format(api_key, service_type)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    if not api_endpoint:
        raise HTTPException(status_code=400, detail="API 端点 URL 不能为空")

    channel_config = {
        "api_key": api_key,
        "api_endpoint": api_endpoint,
        "service_type": service_type,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "real_model_id": real_model_id
    }
    _fallback_mgr.set_channel(model_alias, channel_config)
    return JSONResponse({"success": True, "model_alias": model_alias})


@router.delete("/ui/fallback/channel/{model_alias}")
async def delete_fallback_channel(model_alias: str):
    """删除指定模型的兜底渠道"""
    if not _fallback_mgr:
        raise HTTPException(status_code=400, detail="兜底机制未初始化")
    result = _fallback_mgr.remove_channel(model_alias)
    if not result:
        raise HTTPException(status_code=404, detail="兜底渠道不存在")
    return JSONResponse({"success": True})


@router.get("/ui/fallback/channels")
async def get_fallback_channels():
    """获取所有兜底渠道（设置页面使用）"""
    if not _fallback_mgr:
        return JSONResponse({"channels": {}})
    return JSONResponse({"channels": _fallback_mgr.get_all_channels()})


@router.get("/ui/fallback/models")
async def get_fallback_models():
    """获取所有去重后的模型 ID 列表（设置页面使用）"""
    all_models = set()
    for p in _providers_mgr.get_all_providers():
        for m in p.get("models", []):
            if m.get("enabled", False):
                all_models.add(m["id"])
    return JSONResponse({"models": sorted(all_models)})


def _get_local_ip() -> str:
    """获取本机局域网 IP 地址"""
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return _socket.gethostbyname(_socket.gethostname())
        except Exception:
            return "your-server"


@router.get("/ui/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    base_url = str(request.base_url).rstrip("/")
    local_ip = _get_local_ip()
    return templates.TemplateResponse(
        "docs.html",
        {"request": request, "base_url": base_url, "local_ip": local_ip}
    )
