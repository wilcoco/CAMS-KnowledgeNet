"""검증된 소셜 위키 (MVS) — 카파시/옵시디안 위키 + 소셜 쉐어링 + 인증 투자.

풀 Nightwish가 아니라 최소 동작 서비스의 도메인 레이어다. 자세한 스코프는
``docs/service-mvs.md`` 참조.
"""

from nightwish.wiki.bookkeeper import Bookkeeper, StubBookkeeper, slugify
from nightwish.wiki.models import User, WikiPage
from nightwish.wiki.service import WikiError, WikiService

__all__ = [
    "Bookkeeper",
    "StubBookkeeper",
    "User",
    "WikiError",
    "WikiPage",
    "WikiService",
    "slugify",
]
