import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from app.models.schemas import (
    ChatCompletionRequest, ChatMessage, ModelList, ModelInfo,
    ResponsesRequest, AnthropicRequest, GeminiRequest
)
from app.services.router import RouterService
from app.services.provider_client import ProviderClient
from app.config.providers import ProvidersManager
from app.config.settings import SettingsManager

logger = logging.getLogger(__name__)

router = APIRouter()
_router_service: RouterService = None
_providers_mgr: ProvidersManager = None
_settings_mgr: SettingsManager = None


def init(
    router_service: RouterService,
    providers_mgr: ProvidersManager,
    settings_mgr: SettingsManager
):
    global _router_service, _providers_mgr, _settings_mgr
    _router_service = router_service
    _providers_mgr = providers_mgr
    _settings_mgr = settings_mgr


# ========== 辅助函数 ==========

async def _forward_request(
    model_alias: str,
    messages: List[Dict[str, str]],
    stream: bool = False,
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """通用转发逻辑：解析别名 → 竞速模式调用上游"""
    kwargs = dict(extra_kwargs or {})

    # 流式请求使用原有的单路转发
    if stream:
        best = await _router_service.select_best_provider(model_alias)
        if not best:
            raise HTTPException(status_code=503, detail=f"模型 {model_alias} 当前无可用中转站")
        provider = best["provider"]
        key_info = _router_service.select_key(provider)
        if not key_info:
            raise HTTPException(status_code=503, detail=f"中转站 {provider['name']} 无可用 API Key")
        client = ProviderClient(provider["url"], key_info["key"], timeout=None,
                                service_type=provider.get("service_type", "openai"))
        return StreamingResponse(
            client.chat_completion_stream(messages, best["model_id"], **kwargs),
            media_type="text/event-stream"
        )

    # --- 非流式请求：竞速模式 ---
    combos = await _router_service.get_all_combos_for_model(model_alias)
    if not combos:
        raise HTTPException(status_code=503, detail=f"模型 {model_alias} 当前无可用中转站")

    race_timeout = _settings_mgr.get("race_timeout_seconds", 0)

    async def _do_request(combo: Dict) -> Dict:
        """对单个 (中转站, key) 发起请求"""
        req_timeout = _settings_mgr.get("request_timeout_seconds", 30)
        client = ProviderClient(combo["url"], combo["key"], timeout=req_timeout,
                                service_type=combo["service_type"])
        result = await client.chat_completion(messages, combo["real_model_id"], **kwargs)
        return {"result": result, "provider_name": combo["provider_name"], "key_id": combo["key_id"]}

    # 先尝试首个最优组合
    first_error = None
    if race_timeout > 0:
        try:
            data = await asyncio.wait_for(_do_request(combos[0]), timeout=race_timeout)
            return JSONResponse(content=data["result"])
        except asyncio.TimeoutError:
            first_error = f"首个中转站超时 ({race_timeout}s)"
            logger.info(first_error)
        except Exception as e:
            first_error = str(e)
            logger.warning(f"首个中转站请求失败: {e}")
    else:
        try:
            data = await _do_request(combos[0])
            return JSONResponse(content=data["result"])
        except Exception as e:
            first_error = str(e)
            logger.warning(f"首个中转站请求失败: {e}")

    # 首个失败 → 竞速所有组合
    if len(combos) == 1:
        raise HTTPException(status_code=502, detail=f"转发请求失败: {first_error or '未知错误'}")

    logger.info(f"启动竞速模式，共 {len(combos)} 个组合")
    tasks = [asyncio.create_task(_do_request(c)) for c in combos]
    errors = []

    while tasks:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            try:
                data = t.result()
                for p in pending:
                    p.cancel()
                logger.info(f"竞速成功: {data['provider_name']} / key={data['key_id']}")
                return JSONResponse(content=data["result"])
            except Exception as ex:
                errors.append(str(ex))
        tasks = list(pending)

    error_detail = "; ".join(errors[:3]) or "所有中转站均请求失败"
    logger.error(f"竞速结果: 全部失败 - {error_detail}")
    raise HTTPException(status_code=502, detail=f"所有中转站均请求失败: {error_detail}")


def _convert_input_to_messages(input_data: Any) -> List[Dict[str, str]]:
    """将 OpenAI Responses 的 input 字段转为标准 messages"""
    if isinstance(input_data, str):
        return [{"role": "user", "content": input_data}]
    elif isinstance(input_data, list):
        messages = []
        for item in input_data:
            if isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content", "")
                # content 可能是一个列表（多模态）
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                    content = " ".join(text_parts)
                messages.append({"role": role, "content": content})
            else:
                messages.append({"role": "user", "content": str(item)})
        return messages
    return [{"role": "user", "content": str(input_data)}]


def _convert_anthropic_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Anthropic 格式转标准 messages"""
    result = []
    for m in messages:
        result.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    return result


def _convert_gemini_contents(contents: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Gemini contents 转标准 messages"""
    messages = []
    for c in contents:
        role = c.get("role", "user")
        parts = c.get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
        messages.append({"role": role, "content": text})
    return messages


# ========== 模型列表接口 ==========

@router.get("/v1/models")
async def list_models():
    aliases = _providers_mgr.get_all_aliases()
    models = []
    for alias_name in aliases:
        models.append(ModelInfo(
            id=alias_name,
            created=int(time.time())
        ))
    # 也返回没有别名的已启用模型
    for p in _providers_mgr.get_all_providers():
        for m in p.get("models", []):
            if m.get("enabled", False):
                alias = _providers_mgr.get_alias(m["id"])
                model_id = alias or m["id"]
                if not any(mo.id == model_id for mo in models):
                    models.append(ModelInfo(
                        id=model_id,
                        created=int(time.time())
                    ))
    return ModelList(data=models)


# ========== OpenAI Chat Completions API ==========

@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    kwargs = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.frequency_penalty is not None:
        kwargs["frequency_penalty"] = request.frequency_penalty
    if request.presence_penalty is not None:
        kwargs["presence_penalty"] = request.presence_penalty
    if request.stop is not None:
        kwargs["stop"] = request.stop
    return await _forward_request(request.model, messages, request.stream, kwargs)


# ========== OpenAI Responses API ==========

@router.post("/v1/responses")
async def responses_api(request: ResponsesRequest):
    messages = _convert_input_to_messages(request.input)
    kwargs = {}
    if request.max_output_tokens is not None:
        kwargs["max_tokens"] = request.max_output_tokens
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    return await _forward_request(request.model, messages, request.stream, kwargs)


# ========== Anthropic Messages API ==========

@router.post("/v1/messages")
async def anthropic_messages(request: AnthropicRequest):
    messages = _convert_anthropic_messages([m.dict() for m in request.messages])
    kwargs = {}
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.stop_sequences is not None:
        kwargs["stop"] = request.stop_sequences
    return await _forward_request(request.model, messages, request.stream, kwargs)


# ========== Gemini Generate Content API ==========

@router.post("/v1beta/models/{model}:generateContent")
async def gemini_generate_content(model: str, request: GeminiRequest):
    messages = _convert_gemini_contents([c.dict() for c in request.contents])
    kwargs = {}
    if request.generationConfig:
        if "temperature" in request.generationConfig:
            kwargs["temperature"] = request.generationConfig["temperature"]
        if "maxOutputTokens" in request.generationConfig:
            kwargs["max_tokens"] = request.generationConfig["maxOutputTokens"]
        if "topP" in request.generationConfig:
            kwargs["top_p"] = request.generationConfig["topP"]
        if "stopSequences" in request.generationConfig:
            kwargs["stop"] = request.generationConfig["stopSequences"]
    return await _forward_request(model, messages, stream=False, extra_kwargs=kwargs)
