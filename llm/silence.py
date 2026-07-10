from __future__ import annotations

from ..core.state import CompanionState


class SilenceMechanism:
    def __init__(self, energy_threshold: int = 25, boundary_threshold: int = 60) -> None:
        self.energy_threshold = energy_threshold
        self.boundary_threshold = boundary_threshold

    def check(self, state: CompanionState) -> str | None:
        if state.boundary_pressure >= max(75, self.boundary_threshold + 15):
            return "strong_boundary"
        if state.boundary_pressure >= self.boundary_threshold:
            return "defensive"
        if state.energy < self.energy_threshold:
            if state.mood in ("疲惫", "低落"):
                return "tired_low"
            return "low_energy"
        return None

    def build_silence_intent(self, state: CompanionState, mode: str) -> str:
        stance = state.boundary_stance()

        if mode == "strong_boundary":
            return "强边界策略：完整处理本轮必要事项，只答核心；不追问、不延伸、不暧昧，平静克制。"
        if mode == "defensive":
            return f"边界收敛({stance})：先答核心，减少铺陈；不主动延伸、不追问，保持礼貌稳定。"
        if mode == "tired_low":
            return "低余裕策略：完整回答核心后自然收束；语气温和，少铺陈，不开启新话题。"
        return "低余裕策略：完整回答核心，减少寒暄、重复解释、额外建议和非必要追问；不要声称或暗示 bot 困倦、受伤或需要休息。"

    def should_inject_silence(self, state: CompanionState) -> tuple[bool, str]:
        mode = self.check(state)
        if mode is None:
            return False, ""
        return True, self.build_silence_intent(state, mode)
