"""마스터 편집 잠금.

브랜드 매핑을 저장하면 **서버 디스크의 `masters/refs/brand_keys.csv` 가 바뀐다.**
그 서버를 보는 모든 사람의 판정이 그 자리에서 함께 바뀐다 — 되돌리려면 누가
무엇을 고쳤는지부터 알아내야 한다. 그래서 고치기 전에 암호를 받는다.

암호는 `.env` 의 `MASTER_EDIT_PASSWORD` 다. **비어 있으면 잠긴다**(조회는 된다).
`EAI_ENDPOINT` 와 같은 원칙이다 — `.env` 를 깜빡한 채 띄웠을 때 열려 있는 것보다
잠겨 있는 편이 안전하다.

해제는 **브라우저 세션 단위**다. 탭을 닫으면 다시 잠긴다. 사내망 단일 화면이라
계정·권한 체계는 범위 밖이고, 여기서 막는 것은 "지나가다 실수로 고치는 일"이다.
누가 고쳤는지까지 남겨야 하면 CSV 의 Git 이력을 쓴다.
"""

from __future__ import annotations

import hmac

import streamlit as st

_UNLOCKED = "master_unlocked"


def is_unlocked() -> bool:
    return bool(st.session_state.get(_UNLOCKED))


def lock() -> None:
    st.session_state.pop(_UNLOCKED, None)


def gate(password: str, *, what: str) -> bool:
    """잠금 상태를 그려주고 열렸는지 돌려준다. `password` 는 설정값이다."""
    if is_unlocked():
        left, right = st.columns([4, 1])
        left.caption(f"🔓 {what} 편집이 열려 있습니다.")
        if right.button("잠그기", key="master_lock"):
            lock()
            st.rerun()
        return True

    if not password:
        st.warning(
            f"{what} 편집이 잠겨 있습니다 — 서버의 `.env` 에 "
            "`MASTER_EDIT_PASSWORD` 가 지정되지 않았습니다.\n\n"
            "관리자가 `.env` 에 암호를 넣고 화면을 다시 시작하면 열립니다. "
            "지금은 조회만 됩니다.",
            icon="🔒",
        )
        return False

    with st.form("master_unlock", clear_on_submit=True):
        st.caption(f"🔒 {what} 을(를) 고치려면 암호가 필요합니다. 조회는 그대로 됩니다.")
        entered = st.text_input("암호", type="password", label_visibility="collapsed")
        if st.form_submit_button("잠금 해제", type="primary"):
            # compare_digest — 맞는 글자 수만큼 오래 걸리는 비교를 피한다.
            # **바이트로 넘긴다.** 문자열로 주면 한글이 섞이는 순간
            # TypeError 가 나고 화면 전체가 트레이스백이 된다
            # (2026-09-21 브라우저 확인에서 실제로 터졌다).
            if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
                st.session_state[_UNLOCKED] = True
                st.rerun()
            else:
                st.error("암호가 맞지 않습니다.", icon="⛔")
    return False
