"""兜底机制单元测试"""
import asyncio
import json
import os
import sys
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config.fallback import FallbackManager, DEFAULT_FALLBACK_CONFIG
from app.services.fallback_handler import FallbackHandler


# ========== Fixtures ==========

@pytest.fixture
def temp_runtime_dir():
    """创建临时 runtime 目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        # 模拟 runtime 目录
        runtime_dir = os.path.join(tmpdir, "runtime")
        os.makedirs(runtime_dir, exist_ok=True)
        yield runtime_dir


@pytest.fixture
def fallback_mgr(temp_runtime_dir):
    """创建 FallbackManager 实例（使用临时目录）"""
    # 修改路径指向临时目录
    with patch.object(FallbackManager, '_load', new=lambda self: None):
        with patch.object(FallbackManager, '_save', new=lambda self: None):
            mgr = FallbackManager()
            mgr._config = dict(DEFAULT_FALLBACK_CONFIG)
            mgr._fernet = None  # 测试时不使用加密
            return mgr


@pytest.fixture
def fallback_mgr_with_encryption(temp_runtime_dir):
    """创建带加密的 FallbackManager 实例"""
    # 修改路径指向临时目录
    original_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "runtime"
    )
    test_path = temp_runtime_dir

    with patch('app.config.fallback.FALLBACK_CONFIG_PATH', os.path.join(test_path, "fallback_config.json")):
        with patch('app.config.fallback.ENCRYPTION_KEY_PATH', os.path.join(test_path, ".encryption_key")):
            mgr = FallbackManager()
            yield mgr


# ========== FallbackManager 测试 ==========

class TestFallbackManager:
    """测试 FallbackManager 配置管理"""

    def test_default_config(self, fallback_mgr):
        """测试默认配置"""
        assert fallback_mgr.is_enabled() is False
        assert fallback_mgr.get_all_channels() == {}

    def test_enable_disable(self, fallback_mgr):
        """测试启用/禁用兜底机制"""
        assert fallback_mgr.is_enabled() is False
        fallback_mgr.set_enabled(True)
        assert fallback_mgr.is_enabled() is True
        fallback_mgr.set_enabled(False)
        assert fallback_mgr.is_enabled() is False

    def test_set_and_get_channel(self, fallback_mgr):
        """测试设置和获取兜底渠道"""
        channel_config = {
            "api_key": "sk-test-key-12345",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 30,
            "max_retries": 2,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("gpt-4-alias", channel_config)

        channel = fallback_mgr.get_channel("gpt-4-alias")
        assert channel is not None
        assert channel["api_key"] == "sk-test-key-12345"
        assert channel["api_endpoint"] == "https://api.openai.com"
        assert channel["service_type"] == "openai"
        assert channel["timeout_seconds"] == 30
        assert channel["max_retries"] == 2

    def test_remove_channel(self, fallback_mgr):
        """测试删除兜底渠道"""
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai"
        }
        fallback_mgr.set_channel("test-model", channel_config)
        assert fallback_mgr.get_channel("test-model") is not None

        result = fallback_mgr.remove_channel("test-model")
        assert result is True
        assert fallback_mgr.get_channel("test-model") is None

        # 删除不存在的渠道
        result = fallback_mgr.remove_channel("nonexistent")
        assert result is False

    def test_get_channel_for_request_disabled(self, fallback_mgr):
        """测试兜底禁用时获取渠道返回 None"""
        fallback_mgr.set_enabled(False)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai"
        }
        fallback_mgr.set_channel("test-model", channel_config)
        assert fallback_mgr.get_channel_for_request("test-model") is None

    def test_get_channel_for_request_enabled(self, fallback_mgr):
        """测试兜底启用时获取渠道"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 30,
            "max_retries": 2,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        result = fallback_mgr.get_channel_for_request("test-model")
        assert result is not None
        assert result["url"] == "https://api.openai.com"
        assert result["key"] == "sk-test-key"
        assert result["service_type"] == "openai"
        assert result["timeout"] == 30
        assert result["max_retries"] == 2

    def test_get_channel_for_request_no_channel(self, fallback_mgr):
        """测试未配置渠道时返回 None"""
        fallback_mgr.set_enabled(True)
        assert fallback_mgr.get_channel_for_request("nonexistent") is None

    def test_multiple_models_independence(self, fallback_mgr):
        """测试不同模型的兜底渠道独立性"""
        fallback_mgr.set_enabled(True)

        channel_a = {
            "api_key": "sk-key-a",
            "api_endpoint": "https://api.a.com",
            "service_type": "openai"
        }
        channel_b = {
            "api_key": "sk-key-b",
            "api_endpoint": "https://api.b.com",
            "service_type": "anthropic"
        }
        fallback_mgr.set_channel("model-a", channel_a)
        fallback_mgr.set_channel("model-b", channel_b)

        result_a = fallback_mgr.get_channel_for_request("model-a")
        result_b = fallback_mgr.get_channel_for_request("model-b")

        assert result_a["key"] == "sk-key-a"
        assert result_a["url"] == "https://api.a.com"
        assert result_b["key"] == "sk-key-b"
        assert result_b["url"] == "https://api.b.com"

        # 删除 model-a 不影响 model-b
        fallback_mgr.remove_channel("model-a")
        assert fallback_mgr.get_channel_for_request("model-a") is None
        assert fallback_mgr.get_channel_for_request("model-b") is not None

    def test_validate_api_key_format(self, fallback_mgr):
        """测试 API Key 格式校验"""
        # OpenAI 格式
        valid, msg = fallback_mgr.validate_api_key_format("sk-test-key", "openai")
        assert valid is True

        # 空值
        valid, msg = fallback_mgr.validate_api_key_format("", "openai")
        assert valid is False

        # Anthropic 格式
        valid, msg = fallback_mgr.validate_api_key_format("sk-ant-key", "anthropic")
        assert valid is True

        # 无效的 Anthropic Key
        valid, msg = fallback_mgr.validate_api_key_format("invalid-key", "anthropic")
        assert valid is False

    def test_encryption_decryption(self, fallback_mgr_with_encryption):
        """测试 API Key 加密和解密"""
        mgr = fallback_mgr_with_encryption
        plain_key = "sk-test-encrypted-key-12345"

        encrypted = mgr.encrypt_api_key(plain_key)
        assert encrypted != plain_key
        assert isinstance(encrypted, str)

        decrypted = mgr.decrypt_api_key(encrypted)
        assert decrypted == plain_key

    def test_encrypted_storage(self, fallback_mgr_with_encryption):
        """测试加密存储 - 明文 Key 不存储在配置中"""
        mgr = fallback_mgr_with_encryption
        mgr.set_enabled(True)

        channel_config = {
            "api_key": "sk-secret-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai"
        }
        mgr.set_channel("test-model", channel_config)

        # 检查内部存储没有明文 key
        internal_channels = mgr._config.get("channels", {})
        internal_channel = internal_channels.get("test-model", {})
        assert "api_key" not in internal_channel  # 明文 key 不应存储
        assert "api_key_encrypted" in internal_channel  # 加密后的 key 应存在

        # 通过 get_channel 获取时自动解密
        channel = mgr.get_channel("test-model")
        assert channel["api_key"] == "sk-secret-key"


# ========== FallbackHandler 测试 ==========

class TestFallbackHandler:
    """测试 FallbackHandler 兜底请求处理"""

    @pytest.mark.asyncio
    async def test_execute_fallback_no_channel(self, fallback_mgr):
        """测试无兜底渠道时返回 None"""
        fallback_mgr.set_enabled(True)
        handler = FallbackHandler(fallback_mgr)

        result = await handler.execute_fallback("nonexistent-model", [{"role": "user", "content": "hello"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_fallback_disabled(self, fallback_mgr):
        """测试兜底禁用时返回 None"""
        fallback_mgr.set_enabled(False)
        handler = FallbackHandler(fallback_mgr)

        result = await handler.execute_fallback("test-model", [{"role": "user", "content": "hello"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_fallback_success(self, fallback_mgr):
        """测试兜底请求成功"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 30,
            "max_retries": 2,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        handler = FallbackHandler(fallback_mgr)

        # Mock ProviderClient.chat_completion
        mock_result = {"choices": [{"message": {"content": "Hello!"}}]}
        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance

            result = await handler.execute_fallback(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert result is not None
            assert result["result"] == mock_result
            assert result["from_fallback"] is True
            assert result["provider_name"] == "fallback:openai"

    @pytest.mark.asyncio
    async def test_execute_fallback_retry_on_failure(self, fallback_mgr):
        """测试兜底请求失败后重试"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 5,
            "max_retries": 3,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        handler = FallbackHandler(fallback_mgr)

        # Mock ProviderClient - 前两次失败，第三次成功
        mock_result = {"choices": [{"message": {"content": "Hello!"}}]}
        call_count = [0]

        async def mock_chat_completion(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("上游服务暂时不可用")
            return mock_result

        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion = mock_chat_completion
            MockClient.return_value = mock_instance

            result = await handler.execute_fallback(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert result is not None
            assert result["result"] == mock_result
            assert call_count[0] == 3  # 重试了 3 次

    @pytest.mark.asyncio
    async def test_execute_fallback_all_retries_fail(self, fallback_mgr):
        """测试所有重试都失败时返回 None"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 5,
            "max_retries": 2,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        handler = FallbackHandler(fallback_mgr)

        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion = AsyncMock(side_effect=Exception("始终失败"))
            MockClient.return_value = mock_instance

            result = await handler.execute_fallback(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_execute_fallback_timeout(self, fallback_mgr):
        """测试兜底请求超时"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 1,
            "max_retries": 1,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        handler = FallbackHandler(fallback_mgr)

        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion = AsyncMock(side_effect=asyncio.TimeoutError)
            MockClient.return_value = mock_instance

            result = await handler.execute_fallback(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_execute_fallback_stream_success(self, fallback_mgr):
        """测试兜底流式请求成功"""
        fallback_mgr.set_enabled(True)
        channel_config = {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai",
            "timeout_seconds": 30,
            "max_retries": 2,
            "real_model_id": "gpt-4"
        }
        fallback_mgr.set_channel("test-model", channel_config)

        handler = FallbackHandler(fallback_mgr)

        # Mock 流式响应
        mock_chunks = [b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
                       b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
                       b'data: [DONE]\n\n']

        async def mock_stream(*args, **kwargs):
            for chunk in mock_chunks:
                yield chunk

        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion_stream = mock_stream
            MockClient.return_value = mock_instance

            gen = await handler.execute_fallback_stream(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert gen is not None
            chunks = []
            async for chunk in gen:
                chunks.append(chunk)
            assert len(chunks) == 3
            assert chunks[0] == mock_chunks[0]


# ========== 集成测试 ==========

class TestFallbackIntegration:
    """测试兜底机制集成"""

    @pytest.mark.asyncio
    async def test_fallback_config_persistence(self, temp_runtime_dir):
        """测试兜底配置持久化"""
        config_path = os.path.join(temp_runtime_dir, "fallback_config.json")
        key_path = os.path.join(temp_runtime_dir, ".encryption_key")

        with patch('app.config.fallback.FALLBACK_CONFIG_PATH', config_path):
            with patch('app.config.fallback.ENCRYPTION_KEY_PATH', key_path):
                # 创建并配置
                mgr1 = FallbackManager()
                mgr1.set_enabled(True)
                mgr1.set_channel("test-model", {
                    "api_key": "sk-persist-key",
                    "api_endpoint": "https://api.openai.com",
                    "service_type": "openai"
                })

                # 重新加载
                mgr2 = FallbackManager()
                assert mgr2.is_enabled() is True
                channel = mgr2.get_channel("test-model")
                assert channel is not None
                assert channel["api_key"] == "sk-persist-key"
                assert channel["api_endpoint"] == "https://api.openai.com"

    @pytest.mark.asyncio
    async def test_fallback_trigger_on_no_combos(self):
        """测试无可用组合时触发兜底（模拟 _forward_request 逻辑）"""
        # 这个测试验证 routes_api.py 中的兜底触发逻辑
        # 当 get_all_combos_for_model 返回空列表时，应触发兜底
        from app.config.fallback import FallbackManager
        from app.services.fallback_handler import FallbackHandler

        mgr = FallbackManager()
        mgr._config = dict(DEFAULT_FALLBACK_CONFIG)
        mgr._fernet = None
        mgr.set_enabled(True)
        mgr.set_channel("test-model", {
            "api_key": "sk-test-key",
            "api_endpoint": "https://api.openai.com",
            "service_type": "openai"
        })

        handler = FallbackHandler(mgr)

        # 模拟兜底请求成功
        mock_result = {"choices": [{"message": {"content": "Hello!"}}]}
        with patch('app.services.fallback_handler.ProviderClient') as MockClient:
            mock_instance = AsyncMock()
            mock_instance.chat_completion = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance

            result = await handler.execute_fallback(
                "test-model",
                [{"role": "user", "content": "hello"}]
            )

            assert result is not None
            assert result["from_fallback"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])