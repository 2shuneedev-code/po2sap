"""규칙엔진(D2) 패키지.

`schema.py` 는 `masters/` 의 YAML(거래처 규칙 · `_base/sap_defaults.yaml`)을
검증하는 Pydantic 모델을 정의한다. `extends` 병합·규칙 실행(7단계 엔진)은
후속 작업(engine.py)에서 다룬다 — 이 패키지의 첫 조각은 스키마 검증뿐이다.
"""

from __future__ import annotations
