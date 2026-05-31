"""테스트 전역 설정 — 웹앱 모듈을 임포트하기 전에 환경을 고정한다.

* 인메모리 SQLite로 영속성 백엔드 고정(파일·Postgres 안 건드림).
* ANTHROPIC_API_KEY 제거 → 결정론적 stub 북키퍼 사용(네트워크 없음).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("ANTHROPIC_API_KEY", None)
