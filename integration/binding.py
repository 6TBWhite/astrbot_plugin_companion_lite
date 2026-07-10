from __future__ import annotations


class BindingManager:
    def __init__(self, user_ids: list[str]) -> None:
        self._user_ids = tuple(str(item).strip() for item in user_ids if str(item).strip())

    @property
    def configured(self) -> bool:
        return bool(self._user_ids)

    @property
    def user_ids(self) -> tuple[str, ...]:
        return self._user_ids

    def is_bound(self, user_id: str) -> bool:
        return bool(user_id) and user_id in self._user_ids

    def primary_user_id(self) -> str:
        return self._user_ids[0] if self._user_ids else ""

    def bind(self, user_id: str) -> bool:
        normalized = str(user_id or "").strip()
        if not normalized or normalized in self._user_ids:
            return False
        self._user_ids = self._user_ids + (normalized,)
        return True

    def unbind(self, user_id: str) -> bool:
        normalized = str(user_id or "").strip()
        if not normalized or normalized not in self._user_ids:
            return False
        self._user_ids = tuple(item for item in self._user_ids if item != normalized)
        return True
