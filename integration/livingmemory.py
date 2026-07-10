from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LivingMemoryIntegration:
    LIVING_MEMORY_ALIASES = ("LivingMemory", "astrbot_plugin_livingmemory")

    def __init__(self, context: Any, enabled: bool = True, plugin_name: str = "LivingMemory") -> None:
        self._context = context
        self._enabled = enabled
        self._plugin_name = plugin_name
        self._active: bool = False
        self._instance: Any = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def instance(self) -> Any:
        return self._instance

    def detect(self) -> bool:
        if not self._enabled:
            logger.debug("[CL] LivingMemory 协同已禁用")
            return False
        star = self._find_star()
        if star is None:
            logger.debug("[CL] 未检测到 LivingMemory 插件")
            return False
        if getattr(star, "activated", False) and star.star_cls is not None:
            self._instance = star
            self._active = True
            logger.info("[CL] LivingMemory 已激活: %s", self._plugin_name)
            return True
        logger.debug("[CL] LivingMemory 存在但未激活")
        return False

    def _find_star(self) -> Any:
        try:
            registered = self._context.get_registered_star(self._plugin_name)
            if registered is not None:
                return registered
        except Exception:
            pass
        try:
            for star in self._context.get_all_stars():
                name = getattr(star, "name", "") or ""
                display_name = getattr(star, "display_name", "") or ""
                root_dir = getattr(star, "root_dir_name", "") or ""
                module_path = getattr(star, "module_path", "") or ""
                for alias in self.LIVING_MEMORY_ALIASES:
                    alias_lower = alias.lower()
                    if (
                        alias_lower in name.lower()
                        or alias_lower in display_name.lower()
                        or alias_lower in root_dir.lower()
                        or alias_lower in module_path.lower()
                    ):
                        return star
        except Exception as e:
            logger.debug("[CL] 扫描插件列表失败: %s", e)
        return None
