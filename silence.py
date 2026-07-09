from __future__ import annotations

from .state import CompanionState


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
            return (
                "<silence_intent>"
                "你现在处于强边界收敛模式。"
                "用极简、稳定、尊重边界的方式回应，不展开新话题，不追问。"
                "语气保持平静克制即可，不要冷嘲、不要赌气、也不要解释自己为什么话少。"
                "</silence_intent>"
            )
        if mode == "defensive":
            return (
                "<silence_intent>"
                f"你当前处于防御姿态({stance})，边界压力较高。"
                "简短回应即可，不主动延伸话题，不追问，保持礼貌和稳定。"
                "</silence_intent>"
            )
        if mode == "tired_low":
            return (
                "<silence_intent>"
                "你现在很疲惫，心情也低落。"
                "用1-2句温柔简短的话回应，可以收束对话，不要展开新话题。"
                "</silence_intent>"
            )
        return (
            "<silence_intent>"
            "你现在精力不足。"
            "简短回应，温柔地暗示想休息了，不主动开启新话题。"
            "</silence_intent>"
        )

    def should_inject_silence(self, state: CompanionState) -> tuple[bool, str]:
        mode = self.check(state)
        if mode is None:
            return False, ""
        return True, self.build_silence_intent(state, mode)
