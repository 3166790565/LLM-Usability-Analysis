import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

FALLBACK_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "runtime", "fallback_config.json"
)
ENCRYPTION_KEY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "runtime", ".encryption_key"
)

DEFAULT_FALLBACK_CONFIG = {
    "enabled": False,
    "channels": {}  # model_alias -> {api_key_encrypted, api_endpoint, service_type, timeout_seconds, max_retries}
}


def _get_or_create_fernet():
    """获取或创建 Fernet 加密实例"""
    from cryptography.fernet import Fernet
    key_dir = os.path.dirname(ENCRYPTION_KEY_PATH)
    os.makedirs(key_dir, exist_ok=True)
    if os.path.exists(ENCRYPTION_KEY_PATH):
        with open(ENCRYPTION_KEY_PATH, "rb") as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_PATH, "wb") as f:
            f.write(key)
    return Fernet(key)


class FallbackManager:
    """兜底机制配置管理器"""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._fernet = _get_or_create_fernet()
        self._load()

    def _load(self):
        if os.path.exists(FALLBACK_CONFIG_PATH):
            with open(FALLBACK_CONFIG_PATH, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        else:
            self._config = dict(DEFAULT_FALLBACK_CONFIG)
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(FALLBACK_CONFIG_PATH), exist_ok=True)
        with open(FALLBACK_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    # --- 全局开关 ---

    def is_enabled(self) -> bool:
        return self._config.get("enabled", False)

    def set_enabled(self, enabled: bool):
        self._config["enabled"] = enabled
        self._save()

    # --- 加密工具 ---

    def encrypt_api_key(self, plain_key: str) -> str:
        """加密 API Key"""
        return self._fernet.encrypt(plain_key.encode("utf-8")).decode("utf-8")

    def decrypt_api_key(self, encrypted_key: str) -> str:
        """解密 API Key"""
        if not self._fernet:
            return encrypted_key
        try:
            return self._fernet.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.error(f"解密 API Key 失败: {e}")
            return ""

    # --- 渠道管理 ---

    def get_all_channels(self) -> Dict[str, Any]:
        """获取所有兜底渠道配置（解密后的）"""
        channels = self._config.get("channels", {})
        result = {}
        for model_alias, channel in channels.items():
            decrypted = dict(channel)
            if "api_key_encrypted" in decrypted:
                decrypted["api_key"] = self.decrypt_api_key(decrypted.pop("api_key_encrypted"))
            result[model_alias] = decrypted
        return result

    def get_channel(self, model_alias: str) -> Optional[Dict[str, Any]]:
        """获取指定模型的兜底渠道配置（解密后的）"""
        channels = self._config.get("channels", {})
        channel = channels.get(model_alias)
        if not channel:
            return None
        result = dict(channel)
        if "api_key_encrypted" in result:
            result["api_key"] = self.decrypt_api_key(result.pop("api_key_encrypted"))
        return result

    def set_channel(self, model_alias: str, channel_config: Dict[str, Any]):
        """设置/更新指定模型的兜底渠道配置"""
        channels = self._config.setdefault("channels", {})
        # 加密 API Key
        plain_key = channel_config.get("api_key", "")
        if plain_key:
            if self._fernet:
                channel_config["api_key_encrypted"] = self.encrypt_api_key(plain_key)
            else:
                channel_config["api_key_encrypted"] = plain_key
        # 移除明文 key（不存储明文）
        channel_config.pop("api_key", None)
        # 合并已有配置
        existing = channels.get(model_alias, {})
        existing.update(channel_config)
        channels[model_alias] = existing
        self._save()

    def remove_channel(self, model_alias: str) -> bool:
        """删除指定模型的兜底渠道配置"""
        channels = self._config.get("channels", {})
        if model_alias in channels:
            del channels[model_alias]
            self._save()
            return True
        return False

    def get_channel_for_request(self, model_alias: str) -> Optional[Dict[str, Any]]:
        """获取用于发起请求的兜底渠道配置（含解密后的 key 和完整参数）"""
        if not self.is_enabled():
            return None
        channel = self.get_channel(model_alias)
        if not channel:
            return None
        api_key = channel.get("api_key", "")
        if not api_key:
            return None
        return {
            "url": channel.get("api_endpoint", ""),
            "key": api_key,
            "service_type": channel.get("service_type", "openai"),
            "timeout": channel.get("timeout_seconds", 30),
            "max_retries": channel.get("max_retries", 2),
            "real_model_id": channel.get("real_model_id", model_alias)
        }

    def get_all_config(self) -> Dict[str, Any]:
        """获取完整配置（前端展示用，API Key 已解密）"""
        return {
            "enabled": self.is_enabled(),
            "channels": self.get_all_channels()
        }

    def validate_api_key_format(self, api_key: str, service_type: str = "openai") -> tuple[bool, str]:
        """校验 API Key 格式"""
        if not api_key or not api_key.strip():
            return False, "API Key 不能为空"
        api_key = api_key.strip()
        if service_type in ("openai", "openai_responses"):
            if not api_key.startswith("sk-") and not api_key.startswith("fk"):
                return False, "OpenAI 格式的 API Key 应以 'sk-' 或 'fk' 开头"
        elif service_type in ("anthropic", "deepseek"):
            if not api_key.startswith("sk-"):
                return False, f"{service_type} 格式的 API Key 应以 'sk-' 开头"
        return True, ""