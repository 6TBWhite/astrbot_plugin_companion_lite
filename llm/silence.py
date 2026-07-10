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
            return "强边界收敛：极简回应，不展开不追问，平静克制，不冷嘲不赌气。"
        if mode == "defensive":
            return f"防御姿态({stance})：简短回应，不延伸不追问，保持礼貌稳定。"
        if mode == "tired_low":
            return "疲惫低落：1-2句温柔简短回应，可收束对话，不展开新话题。"
        return "精力不足：简短回应，温柔暗示想休息，不开启新话题。"

    def should_inject_silence(self, state: CompanionState) -> tuple[bool, str]:
        mode = self.check(state)
        if mode is None:
            return False, ""
        return True, self.build_silence_intent(state, mode)
