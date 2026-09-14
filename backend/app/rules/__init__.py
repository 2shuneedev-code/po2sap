"""규칙엔진 (D2).

현재 구현된 것은 `expr` 파서뿐이다. 결정표·매핑 규칙·행 생성은 이어서 붙인다.
명세는 masters/SCHEMA.md.
"""

from .expr import ExprError, ExprInfo, FUNCTIONS, analyze, parse

__all__ = ["ExprError", "ExprInfo", "FUNCTIONS", "analyze", "parse"]
