import json
import os
from typing import List, Dict, Optional
from datetime import datetime

PROVIDERS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runtime", "providers.json")
ALIASES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runtime", "aliases.json")


class ProvidersManager:
    def __init__(self):
        self._providers: List[Dict] = []
        self._aliases: Dict[str, str] = {}
        self._load_providers()
        self._load_aliases()

    # --- Providers CRUD ---
    def _load_providers(self):
        if os.path.exists(PROVIDERS_PATH):
            with open(PROVIDERS_PATH, "r", encoding="utf-8") as f:
                self._providers = json.load(f)
        else:
            self._providers = []
            self._save_providers()

    def _save_providers(self):
        os.makedirs(os.path.dirname(PROVIDERS_PATH), exist_ok=True)
        with open(PROVIDERS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._providers, f, indent=2, ensure_ascii=False)

    def get_all_providers(self) -> List[Dict]:
        return list(self._providers)

    def get_provider(self, provider_id: str) -> Optional[Dict]:
        for p in self._providers:
            if p["id"] == provider_id:
                return p
        return None

    def add_provider(self, provider: Dict) -> Dict:
        provider["id"] = provider.get("id", f"p{len(self._providers) + 1}")
        provider["created_at"] = datetime.now().isoformat()
        provider["updated_at"] = datetime.now().isoformat()
        self._providers.append(provider)
        self._save_providers()
        return provider

    def update_provider(self, provider_id: str, updates: Dict) -> Optional[Dict]:
        for p in self._providers:
            if p["id"] == provider_id:
                updates.pop("id", None)
                updates.pop("created_at", None)
                p.update(updates)
                p["updated_at"] = datetime.now().isoformat()
                self._save_providers()
                return p
        return None

    def delete_provider(self, provider_id: str) -> bool:
        for i, p in enumerate(self._providers):
            if p["id"] == provider_id:
                self._providers.pop(i)
                self._save_providers()
                return True
        return False

    # --- Aliases CRUD ---
    def _load_aliases(self):
        if os.path.exists(ALIASES_PATH):
            with open(ALIASES_PATH, "r", encoding="utf-8") as f:
                self._aliases = json.load(f)
        else:
            self._aliases = {}
            self._save_aliases()

    def _save_aliases(self):
        os.makedirs(os.path.dirname(ALIASES_PATH), exist_ok=True)
        with open(ALIASES_PATH, "w", encoding="utf-8") as f:
            json.dump(self._aliases, f, indent=2, ensure_ascii=False)

    def get_all_aliases(self) -> Dict[str, str]:
        return dict(self._aliases)

    def get_real_model_id(self, alias: str) -> Optional[str]:
        return self._aliases.get(alias)

    def get_alias(self, real_model_id: str) -> Optional[str]:
        for alias, real_id in self._aliases.items():
            if real_id == real_model_id:
                return alias
        return None

    def set_alias(self, alias: str, real_model_id: str):
        self._aliases[alias] = real_model_id
        self._save_aliases()

    def delete_alias(self, alias: str) -> bool:
        if alias in self._aliases:
            del self._aliases[alias]
            self._save_aliases()
            return True
        return False

    def resolve_model_id(self, model_name: str) -> str:
        """解析模型名称：如果是别名则返回真实 ID，否则原样返回"""
        return self._aliases.get(model_name, model_name)

    # --- Helper ---
    def get_all_enabled_models(self) -> List[Dict]:
        """返回所有启用的模型列表，包含 provider 信息和别名"""
        result = []
        for p in self._providers:
            for m in p.get("models", []):
                if m.get("enabled", False):
                    alias = self.get_alias(m["id"])
                    result.append({
                        "provider_id": p["id"],
                        "provider_name": p["name"],
                        "model_id": m["id"],
                        "alias": alias or m["id"]
                    })
        return result
