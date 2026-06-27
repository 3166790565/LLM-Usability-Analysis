import logging
from typing import Optional, Dict, List, Any

from app.config.providers import ProvidersManager
from app.config.settings import SettingsManager
from app.models.database import get_db

logger = logging.getLogger(__name__)


class RouterService:
    def __init__(self, providers_mgr: ProvidersManager, settings_mgr: SettingsManager):
        self.providers_mgr = providers_mgr
        self.settings_mgr = settings_mgr
        self._key_index: Dict[str, int] = {}

    async def select_best_provider(self, model_alias: str) -> Optional[Dict[str, Any]]:
        """为指定模型别名选择最优中转站"""
        real_model_id = self.providers_mgr.resolve_model_id(model_alias)
        # 同时匹配解析后的 ID 和原始别名（有些中转站用别名作为模型 ID）
        model_ids = [real_model_id]
        if model_alias != real_model_id:
            model_ids.append(model_alias)

        # 从测试结果中查找最新成功记录，按延迟排序
        for mid in model_ids:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT t1.* FROM test_results t1
                    INNER JOIN (
                        SELECT provider_id, model_id, key_id, MAX(tested_at) as latest
                        FROM test_results
                        WHERE model_id = ? AND success = 1
                        GROUP BY provider_id, model_id, key_id
                    ) t2 ON t1.model_id = t2.model_id
                        AND t1.key_id = t2.key_id
                        AND t1.tested_at = t2.latest
                        AND t1.provider_id = t2.provider_id
                    ORDER BY t1.latency_ms ASC
                    LIMIT 1""",
                    (mid,)
                )
                row = await cursor.fetchone()
                if row:
                    provider = self.providers_mgr.get_provider(row["provider_id"])
                    if provider:
                        return {
                            "provider": provider,
                            "model_id": row["model_id"],
                            "latency_ms": row["latency_ms"]
                        }

        # 没有成功测试记录 → 检查哪些中转站最近一次测试不是失败
        bad_providers = set()
        for mid in model_ids:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT provider_id FROM test_results
                       WHERE model_id = ? AND success = 0
                         AND (provider_id, key_id, tested_at) IN (
                             SELECT provider_id, key_id, MAX(tested_at)
                             FROM test_results
                             WHERE model_id = ?
                             GROUP BY provider_id, key_id
                         )""",
                    (mid, mid)
                )
                rows = await cursor.fetchall()
                for row in rows:
                    bad_providers.add(row["provider_id"])

        for p in self.providers_mgr.get_all_providers():
            if p["id"] in bad_providers:
                continue
            for m in p.get("models", []):
                if m["id"] in model_ids and m.get("enabled", False):
                    if p.get("api_keys"):
                        return {
                            "provider": p,
                            "model_id": m["id"],
                            "latency_ms": None
                        }
        return None

    def select_key(self, provider: Dict) -> Optional[Dict]:
        """轮询选择一个 key"""
        keys = provider.get("api_keys", [])
        if not keys:
            return None
        pid = provider["id"]
        if pid not in self._key_index:
            self._key_index[pid] = 0
        idx = self._key_index[pid]
        self._key_index[pid] = (idx + 1) % len(keys)
        return keys[idx]

    async def get_all_combos_for_model(self, model_alias: str) -> List[Dict[str, Any]]:
        """获取指定模型所有 (中转站, key) 组合，已测试失败的排最后"""
        real_model_id = self.providers_mgr.resolve_model_id(model_alias)
        model_ids = [real_model_id]
        if model_alias != real_model_id:
            model_ids.append(model_alias)
        combos = []

        # 获取测试延迟数据（合并所有候选 model_id）
        latency_map = {}
        failed_combos = set()
        for mid in model_ids:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT provider_id, key_id, MIN(latency_ms) as best_latency
                       FROM test_results
                       WHERE model_id = ? AND success = 1
                       GROUP BY provider_id, key_id""",
                    (mid,)
                )
                for row in await cursor.fetchall():
                    latency_map[(row["provider_id"], row["key_id"])] = row["best_latency"]

                # 找出最近一次测试失败的组合
                cursor2 = await db.execute(
                    """SELECT provider_id, key_id FROM test_results
                       WHERE model_id = ? AND success = 0
                         AND (provider_id, key_id, tested_at) IN (
                             SELECT provider_id, key_id, MAX(tested_at)
                             FROM test_results
                             WHERE model_id = ?
                             GROUP BY provider_id, key_id
                         )""",
                    (mid, mid)
                )
                for row in await cursor2.fetchall():
                    failed_combos.add((row["provider_id"], row["key_id"]))

        for p in self.providers_mgr.get_all_providers():
            for m in p.get("models", []):
                if m["id"] in model_ids and m.get("enabled", False):
                    for k in p.get("api_keys", []):
                        is_failed = (p["id"], k["id"]) in failed_combos
                        combos.append({
                            "provider_id": p["id"],
                            "provider_name": p["name"],
                            "url": p["url"],
                            "key": k["key"],
                            "key_id": k["id"],
                            "service_type": p.get("service_type", "openai"),
                            "real_model_id": real_model_id,
                            "latency_ms": latency_map.get((p["id"], k["id"])),
                            "is_failed": is_failed
                        })

        # 排序：成功(按延迟升序) → 未测试 → 测试失败
        combos.sort(key=lambda x: (
            x["is_failed"],
            x["latency_ms"] if x["latency_ms"] is not None else float('inf')
        ))
        return combos
