"""거래처 카탈로그 — SAP 브랜드 마스터의 **전 고객** + 규칙 설정 여부.

두 목록이 있다.
  · `masters/customers/*.yaml`  — 파싱 규칙이 설정된 거래처 (지금 3곳)
  · `masters/refs/brand_master.csv` — SAP 브랜드 마스터의 전 고객 (430곳)

화면은 **후자를 보여주고 전자를 표시**한다. 규칙이 없는 고객도 목록에 있어야
브랜드 원문 키를 미리 채워둘 수 있고, 어디까지 왔는지 한눈에 보인다.

규칙이 없는 고객은 **파싱할 수 없다.** 프로필로 대충 채우면 빈 필드가 그대로
전송되는데, 그건 아무도 모르게 틀린 오더가 나가는 길이다. `ready` 가 False 면
업로드를 막고 무엇을 해야 하는지 알려준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .masters import CustomerMaster, MasterError, list_customers
from .masters import brands as brand_store

__all__ = ["CatalogEntry", "load_catalog", "find"]


@dataclass
class CatalogEntry:
    kunnr: str
    name: str
    sap_name: str
    code: str = ""
    file_types: list[str] = field(default_factory=list)
    brand_count: int = 0
    mapped_count: int = 0

    @property
    def configured(self) -> bool:
        """이 거래처 전용 규칙 파일(`customers/<code>.yaml`)이 있는가."""
        return bool(self.code)

    @property
    def ready(self) -> bool:
        """업로드해서 파싱할 수 있는가.

        전용 규칙이 없어도 **SAP 에 브랜드가 등록된 고객이면** 공용 프로필
        (`profiles/generic.yaml`)로 읽어낸다 — 브랜드까지는 나온다. 전 거래처
        테스트 배포가 그래야 가능하다.

        모르는 값(출하처 등)은 채우지 않고 검수 화면에서 빨갛게 막는다.
        그럴듯한 기본값을 넣으면 사람이 확인 없이 전송한다.
        """
        return bool(self.code) or self.brand_count > 0

    @property
    def parse_code(self) -> str:
        """파싱에 쓸 거래처 코드. 전용 규칙이 없으면 고객코드 자체를 쓴다."""
        return self.code or self.kunnr

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kunnr})" if self.name else self.kunnr

    def as_dict(self) -> dict:
        """계약 §10.1 응답 모양. 모든 값은 문자열이다 (계약 §0)."""
        return {
            "kunnr": self.kunnr,
            "name": self.name,
            "sap_name": self.sap_name,
            "code": self.code,
            "file_types": self.file_types,
            "brand_count": str(self.brand_count),
            "mapped_count": str(self.mapped_count),
            "configured": "true" if self.configured else "false",
            "ready": "true" if self.ready else "false",
        }


def _configured(settings: Settings) -> dict[str, CustomerMaster]:
    """고객코드 → 규칙이 설정된 거래처."""
    try:
        return {c.customer_no: c for c in list_customers(settings.masters_dir) if c.customer_no}
    except MasterError:
        return {}


def load_catalog(
    settings: Settings,
    *,
    q: str = "",
    scope: str = "all",
    sort: str = "name",
) -> list[CatalogEntry]:
    """검색·필터·정렬된 고객 목록.

    `q` 는 고객명 · SAP 명 · 고객코드 · 거래처코드를 함께 본다. SAP 의 `name1`
    이 축약형인 경우가 있어서(`107525` = `"KL"`) 한쪽만 봐서는 못 찾는다.
    """
    master = brand_store.load_master(settings.masters_dir)
    keys = brand_store.load_keys(settings.masters_dir)
    configured = _configured(settings)

    by_customer: dict[str, list] = {}
    sap_names: dict[str, str] = {}
    for b in master:
        by_customer.setdefault(b.kunnr, []).append(b)
        if b.customer_name:
            sap_names.setdefault(b.kunnr, b.customer_name)

    mapped: set[str] = {f"{k.kunnr}:{k.zbrand}" for k in keys}

    needle = q.strip().lower()
    out: list[CatalogEntry] = []
    for kunnr, brands in by_customer.items():
        cfg = configured.get(kunnr)
        if scope == "configured" and not cfg:
            continue
        if scope == "unconfigured" and cfg:
            continue

        sap_name = sap_names.get(kunnr, "")
        # SAP 에 이름이 비어 있는 고객이 있다 (21000). 빈 이름으로 두면 이름순
        # 정렬에서 맨 앞에 붙고 화면에는 빈 줄로 보인다 — 코드로 대신 부른다.
        display = (cfg.name if cfg and cfg.name else sap_name) or f"({kunnr})"
        entry = CatalogEntry(
            kunnr=kunnr,
            name=display,
            sap_name=sap_name,
            code=cfg.code if cfg else "",
            file_types=list(cfg.file_types) if cfg else [],
            brand_count=len(brands),
            mapped_count=sum(1 for b in brands if f"{kunnr}:{b.zbrand}" in mapped),
        )

        if needle and not any(
            needle in value.lower()
            for value in (entry.name, entry.sap_name, entry.kunnr, entry.code)
            if value
        ):
            continue
        out.append(entry)

    return _sorted(out, sort)


def _sorted(rows: list[CatalogEntry], sort: str) -> list[CatalogEntry]:
    if sort == "kunnr":
        # 고객코드는 자릿수가 달라 문자열 정렬이 어긋난다 (3200 이 100249 보다 뒤).
        return sorted(rows, key=lambda e: e.kunnr.zfill(12))
    if sort == "ready":
        # 업로드 가능한 곳을 위로, 그 안에서 이름순.
        return sorted(rows, key=lambda e: (not e.ready, e.name.lower(), e.kunnr))
    return sorted(rows, key=lambda e: (e.name.lower(), e.kunnr))


def find(entries: list[CatalogEntry], kunnr: str) -> CatalogEntry | None:
    return next((e for e in entries if e.kunnr == kunnr), None)
