from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VoiceProvider(ABC):
    """后续接入本地语音模型时实现此类即可。"""

    @abstractmethod
    def synthesize(self, text: str, out_path: Path, **kwargs: Any) -> Path:
        raise NotImplementedError


class DisabledVoiceProvider(VoiceProvider):
    def synthesize(self, text: str, out_path: Path, **kwargs: Any) -> Path:
        raise RuntimeError("语音未启用。请在 config.yaml 打开 voice.enabled，并接入本地语音模型。")


def get_voice_provider(cfg: dict[str, Any]) -> VoiceProvider:
    voice = cfg.get("voice") or {}
    if not voice.get("enabled"):
        return DisabledVoiceProvider()
    # 预留：后续在此按 provider 分支返回 LocalVoiceProvider 等
    raise NotImplementedError(
        f"语音 provider={voice.get('provider')!r} 尚未实现，请按 app/voice/base.py 接入。"
    )