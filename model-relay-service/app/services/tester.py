import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config.providers import ProvidersManager
from app.config.settings import SettingsManager
from app.services.provider_client import ProviderClient
from app.models.database import get_db

logger = logging.getLogger(__name__)


class TesterService:
    def __init__(self, providers_mgr: ProvidersManager, settings_mgr: SettingsManager):
        self.providers_mgr = providers_mgr
        self.settings_mgr = settings_mgr
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._test_lock = asyncio.Lock()
        self._on_status_change: Optional[Callable] = None

    def set_status_callback(self, callback: Callable):
        self._on_status_change = callback

    def is_running(self) -> bool:
        return self._running

    async def start_scheduler(self):
        interval = self.settings_mgr.get("test_interval_seconds", 300)
        self.scheduler.add_job(
            self.run_all_tests,
            "interval",
            seconds=interval,
            id="model_test_job",
            replace_existing=True
        )
        self.scheduler.start()
        logger.info(f"定时测试已启动，间隔 {interval} 秒")

    async def stop_scheduler(self):
        self.scheduler.shutdown(wait=False)
        logger.info("定时测试已停止")

    async def restart_scheduler(self):
        try:
            await self.stop_scheduler()
        except Exception:
            pass
        # 创建新 scheduler 实例替代旧的（shutdown 后不能 restart）
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self.scheduler = AsyncIOScheduler()
        await self.start_scheduler()

    async def run_all_tests(self):
        """对所有启用的模型执行测试"""
        if self._running:
            logger.warning("测试正在进行中，跳过本次触发")
            return

        async with self._test_lock:
            self._running = True
            self._notify_status(True)
            logger.info("开始执行所有模型测试")
            try:
                providers = self.providers_mgr.get_all_providers()
                timeout = self.settings_mgr.get("request_timeout_seconds", 30)
                max_workers = self.settings_mgr.get("max_workers", 5)
                test_prompt = self.settings_mgr.get("test_prompt", "say hello in world")

                async def test_provider(provider):
                    results = []
                    for model_cfg in provider.get("models", []):
                        if not model_cfg.get("enabled", False):
                            continue
                        model_id = model_cfg["id"]
                        alias = self.providers_mgr.get_alias(model_id) or model_id

                        for key_info in provider.get("api_keys", []):
                            client = ProviderClient(provider["url"], key_info["key"], timeout,
                                                     service_type=provider.get("service_type", "openai"))
                            latency, error, request_body, response_body = await client.test_model(model_id, test_prompt)
                            success = error is None
                            results.append({
                                "provider_id": provider["id"],
                                "provider_name": provider["name"],
                                "model_id": model_id,
                                "alias_name": alias,
                                "key_id": key_info["id"],
                                "latency_ms": latency,
                                "success": 1 if success else 0,
                                "error_message": error,
                                "request_body": request_body,
                                "response_body": response_body,
                                "tested_at": datetime.now().isoformat()
                            })
                            logger.info(
                                f"测试完成: {provider['name']}/{model_id} "
                                f"key={key_info['id']} 延迟={latency:.0f}ms "
                                f"{'✓' if success else '✗'}"
                            )
                    return results

                # 使用 asyncio.gather 并行测试不同中转站
                sem = asyncio.Semaphore(max_workers)

                async def bounded_test(provider):
                    async with sem:
                        return await test_provider(provider)

                tasks = [bounded_test(p) for p in providers]
                all_results = await asyncio.gather(*tasks, return_exceptions=True)

                # 保存到 SQLite — 先清空旧结果，再写入本次新结果
                async with get_db() as db:
                    await db.execute("DELETE FROM test_results")
                    for result_group in all_results:
                        if isinstance(result_group, list):
                            for r in result_group:
                                await db.execute(
                                    """INSERT INTO test_results
                                    (provider_id, provider_name, model_id, alias_name, key_id, latency_ms, success, error_message, request_body, response_body, tested_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                    (r["provider_id"], r["provider_name"], r["model_id"],
                                     r["alias_name"], r["key_id"], r["latency_ms"],
                                     r["success"], r["error_message"],
                                     r["request_body"], r["response_body"],
                                     r["tested_at"])
                                )
                    await db.commit()
            finally:
                self._running = False
                self._notify_status(False)
            logger.info("所有模型测试完成")

    def _notify_status(self, running: bool):
        if self._on_status_change:
            self._on_status_change(running)
