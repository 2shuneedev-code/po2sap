"""모의 EAI 서버 — 전송 구간을 실서버 없이 관통시킨다.

    python scripts/mock_eai_server.py
    python scripts/mock_eai_server.py --fail 500      # 5xx (재시도 확인)
    python scripts/mock_eai_server.py --fail 400      # 4xx (재시도 안 함 확인)
    python scripts/mock_eai_server.py --delay 70      # 타임아웃 확인

받은 페이로드를 storage/mock_eai/ 에 남긴다 — 실제 EAI 규격이 확정되기 전까지
"무엇을 보내고 있는지"를 눈으로 확인하는 용도다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8  # noqa: E402

use_utf8()   # 윈도우(cp949)에서 파이프로 넘길 때 한글·— 가 죽지 않게

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "storage" / "mock_eai"


class Handler(BaseHTTPRequestHandler):
    fail_status = 0
    delay = 0.0

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 규약)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)

        if self.delay:
            time.sleep(self.delay)

        try:
            payload = json.loads(raw.decode("utf-8"))
            rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
            count = len(rows) if isinstance(rows, list) else 0
        except (ValueError, AttributeError):
            payload, count = None, 0

        OUT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        (OUT / f"{stamp}.json").write_bytes(raw)

        status = self.fail_status or 200
        body = (
            {"result": "OK", "received": count}
            if status < 400
            else {"result": "ERROR", "message": f"모의 실패 (HTTP {status})"}
        )
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

        print(f"[{stamp}] {self.path}  {count}행  → HTTP {status}", flush=True)

    def log_message(self, *args: object) -> None:
        pass            # 위에서 직접 찍는다


def main() -> int:
    ap = argparse.ArgumentParser(description="모의 EAI 서버")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--fail", type=int, default=0, help="이 HTTP 상태로 응답 (0 = 정상)")
    ap.add_argument("--delay", type=float, default=0.0, help="응답 전 지연(초)")
    args = ap.parse_args()

    Handler.fail_status = args.fail
    Handler.delay = args.delay

    print(f"모의 EAI 수신 대기: http://127.0.0.1:{args.port}/po2sap/order")
    print(f"받은 페이로드 저장: {OUT}")
    if args.fail:
        print(f"※ 모든 요청에 HTTP {args.fail} 로 응답합니다")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
