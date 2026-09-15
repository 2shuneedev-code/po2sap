"""EAI 전송 — design.md §5 · 계약 §7."""

from .eai_client import EaiClient, SendOutcome
from .payload import build_payload, split_rows

__all__ = ["EaiClient", "SendOutcome", "build_payload", "split_rows"]
