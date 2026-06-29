import logging
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import os
from datetime import datetime, timedelta

from app.models.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


def _build_filter_clause(
    provider_id: str = "",
    key_id: str = "",
    model_id: str = "",
    start_date: str = "",
    end_date: str = "",
):
    """构建 WHERE 子句和参数"""
    conditions = []
    params = []

    if provider_id:
        conditions.append("t.provider_id = ?")
        params.append(provider_id)
    if key_id:
        conditions.append("t.key_id = ?")
        params.append(key_id)
    if model_id:
        conditions.append("(t.model_id = ? OR t.alias_name = ?)")
        params.extend([model_id, model_id])
    if start_date:
        conditions.append("t.created_at >= ?")
        params.append(f"{start_date} 00:00:00")
    if end_date:
        conditions.append("t.created_at <= ?")
        params.append(f"{end_date} 23:59:59")

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params


# ========== 页面 ==========

@router.get("/ui/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Token 统计页面"""
    return templates.TemplateResponse(
        "stats.html",
        {"request": request}
    )


# ========== 总览数据 ==========

@router.get("/ui/stats/summary")
async def stats_summary(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
):
    """返回总 Token、总请求数、今日 Token、平均 Token/请求"""
    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)

    async with get_db() as db:
        # 总 Token 和总请求
        cursor = await db.execute(
            f"""SELECT COUNT(*) as total_requests,
                       COALESCE(SUM(total_tokens), 0) as total_tokens,
                       COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                       COALESCE(SUM(completion_tokens), 0) as total_completion
                FROM token_usage t{where}""",
            params
        )
        row = await cursor.fetchone()

        # 今日数据
        today = datetime.now().strftime("%Y-%m-%d")
        today_params = [f"{today} 00:00:00"]
        if provider_id:
            today_params.append(provider_id)
        today_where_extra = " AND t.provider_id = ?" if provider_id else ""
        cursor2 = await db.execute(
            f"""SELECT COUNT(*) as today_requests,
                       COALESCE(SUM(total_tokens), 0) as today_tokens
                FROM token_usage t
                WHERE t.created_at >= ?{today_where_extra}""",
            today_params
        )
        today_row = await cursor2.fetchone()

    total_tokens = row["total_tokens"] if row else 0
    total_requests = row["total_requests"] if row else 0
    avg_tokens = round(total_tokens / total_requests, 1) if total_requests > 0 else 0

    return JSONResponse({
        "total_tokens": total_tokens,
        "total_prompt": row["total_prompt"] if row else 0,
        "total_completion": row["total_completion"] if row else 0,
        "total_requests": total_requests,
        "avg_tokens_per_request": avg_tokens,
        "today_tokens": today_row["today_tokens"] if today_row else 0,
        "today_requests": today_row["today_requests"] if today_row else 0,
    })


# ========== 按中转站聚合（饼图） ==========

@router.get("/ui/stats/by-provider")
async def stats_by_provider(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
):
    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)
    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT t.provider_name,
                       COALESCE(SUM(t.total_tokens), 0) as total_tokens,
                       COUNT(*) as request_count
                FROM token_usage t{where}
                GROUP BY t.provider_id
                ORDER BY total_tokens DESC""",
            params
        )
        rows = await cursor.fetchall()
    return JSONResponse({
        "labels": [r["provider_name"] or f"Provider-{i}" for i, r in enumerate(rows)],
        "values": [r["total_tokens"] for r in rows],
        "counts": [r["request_count"] for r in rows],
    })


# ========== 按模型聚合（柱状图） ==========

@router.get("/ui/stats/by-model")
async def stats_by_model(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
):
    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)
    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT COALESCE(t.alias_name, t.model_id) as display_name,
                       COALESCE(SUM(t.total_tokens), 0) as total_tokens,
                       COUNT(*) as request_count
                FROM token_usage t{where}
                GROUP BY display_name
                ORDER BY total_tokens DESC
                LIMIT 20""",
            params
        )
        rows = await cursor.fetchall()
    return JSONResponse({
        "labels": [r["display_name"] for r in rows],
        "values": [r["total_tokens"] for r in rows],
        "counts": [r["request_count"] for r in rows],
    })


# ========== 按 API Key 聚合 ==========

@router.get("/ui/stats/by-key")
async def stats_by_key(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
):
    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)
    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT t.key_id, t.provider_name,
                       COALESCE(SUM(t.total_tokens), 0) as total_tokens,
                       COUNT(*) as request_count
                FROM token_usage t{where}
                GROUP BY t.key_id
                ORDER BY total_tokens DESC""",
            params
        )
        rows = await cursor.fetchall()
    return JSONResponse({
        "keys": [{"key_id": r["key_id"], "provider": r["provider_name"],
                   "tokens": r["total_tokens"], "count": r["request_count"]}
                 for r in rows]
    })


# ========== 按日趋势（折线图） ==========

@router.get("/ui/stats/trend")
async def stats_trend(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    days: int = Query(30),
):
    # 如果未指定日期范围，用 days 参数
    if not start_date and not end_date:
        end = datetime.now()
        start = end - timedelta(days=days)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")

    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)
    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT DATE(t.created_at) as day,
                       COALESCE(SUM(t.total_tokens), 0) as total_tokens,
                       COUNT(*) as request_count
                FROM token_usage t{where}
                GROUP BY DATE(t.created_at)
                ORDER BY day ASC""",
            params
        )
        rows = await cursor.fetchall()
    return JSONResponse({
        "labels": [r["day"] for r in rows],
        "values": [r["total_tokens"] for r in rows],
        "counts": [r["request_count"] for r in rows],
    })


# ========== Token 明细（分页表格） ==========

@router.get("/ui/stats/detail")
async def stats_detail(
    provider_id: str = Query(""),
    key_id: str = Query(""),
    model_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    where, params = _build_filter_clause(provider_id, key_id, model_id, start_date, end_date)
    offset = (page - 1) * per_page
    async with get_db() as db:
        # 总数
        cursor = await db.execute(
            f"SELECT COUNT(*) as total FROM token_usage t{where}", params
        )
        total_row = await cursor.fetchone()
        total = total_row["total"] if total_row else 0

        # 分页数据
        cursor = await db.execute(
            f"""SELECT t.* FROM token_usage t{where}
                ORDER BY t.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset]
        )
        rows = await cursor.fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "provider_name": r["provider_name"],
            "model_id": r["model_id"],
            "alias_name": r["alias_name"],
            "key_id": r["key_id"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "total_tokens": r["total_tokens"],
            "created_at": r["created_at"],
        })

    return JSONResponse({
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })


# ========== 获取筛选选项（供前端下拉框使用） ==========

@router.get("/ui/stats/filters")
async def stats_filters():
    """返回所有可用的中转站列表、模型列表、Key 列表"""
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT DISTINCT provider_id, provider_name FROM token_usage
               ORDER BY provider_name"""
        )
        providers = [{"id": r["provider_id"], "name": r["provider_name"]} for r in await cursor.fetchall()]

        cursor = await db.execute(
            """SELECT DISTINCT key_id FROM token_usage ORDER BY key_id"""
        )
        keys = [r["key_id"] for r in await cursor.fetchall()]

        cursor = await db.execute(
            """SELECT DISTINCT model_id FROM token_usage ORDER BY model_id"""
        )
        models = [r["model_id"] for r in await cursor.fetchall()]

    return JSONResponse({
        "providers": providers,
        "keys": keys,
        "models": models,
    })
