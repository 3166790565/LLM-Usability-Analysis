import asyncio
import logging
import time
from typing import Dict, Any, Optional, AsyncGenerator

from app.config.fallback import FallbackManager
from app.services.provider_client import ProviderClient

logger = logging.getLogger(__name__)


class FallbackHandler:
    """兜底请求处理器"""

    def __init__(self, fallback_mgr: FallbackManager):
        self.fallback_mgr = fallback_mgr

    async def execute_fallback(
        self,
        model_alias: str,
        messages: list,
        stream: bool = False,
        extra_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """执行兜底请求，成功返回结果，失败返回 None"""
        channel = self.fallback_mgr.get_channel_for_request(model_alias)
        if not channel:
            logger.info(f"模型 {model_alias} 无可用兜底渠道配置")
            return None

        url = channel["url"]
        api_key = channel["key"]
        service_type = channel["service_type"]
        timeout = channel["timeout"]
        max_retries = channel["max_retries"]
        real_model_id = channel["real_model_id"]

        if not url or not api_key:
            logger.warning(f"模型 {model_alias} 兜底渠道配置不完整")
            return None

        kwargs = dict(extra_kwargs or {})
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"兜底请求: 模型={model_alias}, 渠道={url}, 尝试={attempt}/{max_retries}"
                )
                client = ProviderClient(url, api_key, timeout=timeout, service_type=service_type)

                if stream:
                    # 流式请求不适合在兜底中直接返回，这里仅记录日志并返回非流式结果
                    logger.warning("兜底机制不支持流式请求，降级为非流式")
                    result = await asyncio.wait_for(
                        client.chat_completion(messages, real_model_id, **kwargs),
                        timeout=timeout
                    )
                else:
                    result = await asyncio.wait_for(
                        client.chat_completion(messages, real_model_id, **kwargs),
                        timeout=timeout
                    )

                logger.info(f"兜底请求成功: 模型={model_alias}, 渠道={url}")
                return {
                    "result": result,
                    "provider_name": f"fallback:{service_type}",
                    "key_id": "fallback",
                    "from_fallback": True
                }

            except asyncio.TimeoutError:
                last_error = f"兜底请求超时 ({timeout}s)"
                logger.warning(f"{last_error}, 尝试={attempt}/{max_retries}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"兜底请求失败: {e}, 尝试={attempt}/{max_retries}")

            if attempt < max_retries:
                wait = 1.0 * attempt
                await asyncio.sleep(wait)

        logger.error(f"兜底请求全部失败: 模型={model_alias}, 错误={last_error}")
        return None

    async def execute_fallback_stream(
        self,
        model_alias: str,
        messages: list,
        extra_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Optional[AsyncGenerator[bytes, None]]:
        """执行兜底流式请求"""
        channel = self.fallback_mgr.get_channel_for_request(model_alias)
        if not channel:
            return None

        url = channel["url"]
        api_key = channel["key"]
        service_type = channel["service_type"]
        timeout = channel["timeout"]
        max_retries = channel["max_retries"]
        real_model_id = channel["real_model_id"]

        if not url or not api_key:
            return None

        kwargs = dict(extra_kwargs or {})

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"兜底流式请求: 模型={model_alias}, 渠道={url}, 尝试={attempt}/{max_retries}"
                )
                client = ProviderClient(url, api_key, timeout=None, service_type=service_type)
                stream = client.chat_completion_stream(messages, real_model_id, **kwargs)

                # 获取第一个 chunk 验证可用性
                first_chunk = await asyncio.wait_for(
                    stream.__anext__(),
                    timeout=timeout
                )

                first_str = first_chunk.decode("utf-8", errors="replace")
                if '"error"' in first_str:
                    logger.warning(f"兜底流式请求上游返回错误: {first_str[:200]}")
                    continue

                logger.info(f"兜底流式请求成功: 模型={model_alias}")

                async def _gen():
                    yield first_chunk
                    async for chunk in stream:
                        yield chunk

                return _gen()

            except StopAsyncIteration:
                logger.warning(f"兜底流式请求流为空, 尝试={attempt}/{max_retries}")
            except asyncio.TimeoutError:
                logger.warning(f"兜底流式请求超时 ({timeout}s), 尝试={attempt}/{max_retries}")
            except Exception as e:
                logger.warning(f"兜底流式请求失败: {e}, 尝试={attempt}/{max_retries}")

            if attempt < max_retries:
                await asyncio.sleep(1.0 * attempt)

        return None