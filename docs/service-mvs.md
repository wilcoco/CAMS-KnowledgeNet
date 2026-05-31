# 최소 동작 서비스 (MVS) — 검증된 소셜 위키

> "카파시/옵시디안식 위키 **+ 소셜 쉐어링 + 인증 투자**만" — 사용자 요청대로
> 풀 Nightwish가 아니라 *최소 가치 서비스*만 구현한다.

도메인 코어(`verification` 등)를 재사용하고, 그 위에 위키·소셜·투자 레이어를
얹는다. **영속성(Postgres/SQLite) · JSON API · 실 LLM 북키핑**을 갖춘 배포 가능한
구성이다. 배포는 [`deploy-railway.md`](deploy-railway.md) 참조.

---

## 무엇을 넣었나 (IN)

| 기능 | 출처 개념 | 구현 |
|------|----------|------|
| **마크다운 위키 + `[[위키링크]]`** | 옵시디안 / 카파시 wiki 층 | `wiki/models.py`, `webapp/render.py` |
| **LLM 북키핑** (요약·엔티티·링크) | 카파시 "LLM이 북키핑" | `wiki/bookkeeper.py` — 실 Claude(`LLMBookkeeper`, ANTHROPIC_API_KEY) / 키 없으면 stub 폴백 |
| **영속성** (재시작해도 유지) | 우리 추가 | `wiki/db.py` — SQLAlchemy(로컬 SQLite ↔ Railway Postgres, `DATABASE_URL`) |
| **JSON API 서버** | 우리 추가 | `webapp/api.py` — `/api/*` (피드·페이지·투자·인증), `X-User` 헤더 |
| **백링크** (누가 이 페이지를 링크했나) | 옵시디안 | `WikiService.backlinks` |
| **소셜 쉐어링** (공유·피드·다중 사용자) | 우리 추가 | `WikiService.share` / `feed` |
| **인증** (외부 측정으로 검증) | Nightwish 검증 닻 | `verification.py` 재사용 |
| **투자** (포인트 스테이킹) | Nightwish 스테이킹 | `economy.Ledger` 재사용 |
| **인증 투자 보상** | 둘의 결합 | 검증된 페이지에 한해, 후속 투자의 일부가 *먼저 투자한* 사람에게 |

## 무엇을 뺐나 (OUT — 의도적)

허브/권위 엔진, 거버넌스 자동분권, UBI 발행, 배당 시간붕괴, 포크/잠복/부활,
3단계 질의 라우팅. → 풀 Nightwish의 영역. MVS에는 불필요.

---

## "인증 투자"의 핵심 규칙

1. 누구나 페이지에 포인트를 **투자(스테이킹)**할 수 있다.
2. 페이지는 **외부 측정**(예: 수율 8%→2%)으로 **인증**될 수 있다.
3. 인증된 페이지에 **새 투자가 들어오면**, 그 일부가 **먼저 투자한 사람들**에게
   흐른다(먼저일수록 더 큰 몫). → *검증될 지식을 일찍 알아본 안목*이 보상받는다.
4. **인증 안 된 페이지**는 이 흐름이 없다(투자는 그냥 잠김). → 검증 없는 인기만으론
   보상이 생기지 않는다(폰지 방지의 미니 버전).

> 보존 법칙: 보상 풀은 *새 투자에서 떼어* 분배한다(신규 발행 아님). 총량 보존.

---

## 실행

```bash
pip install -e ".[service]"                  # 서비스 의존성 (코어는 여전히 0)
uvicorn nightwish.webapp.app:app --reload    # http://127.0.0.1:8000
python -m pytest tests/test_wiki_service.py tests/test_webapp.py tests/test_api.py -q
```

- **영속성:** `DATABASE_URL` 미설정 시 `./nightwish.db`(SQLite), 설정 시 그 DB(Postgres 등).
- **LLM:** `ANTHROPIC_API_KEY` 설정 시 실제 Claude로 북키핑(요약·엔티티·링크), 없으면 stub.
- **배포:** Railway + Postgres 가이드는 [`deploy-railway.md`](deploy-railway.md).

화면: 홈(공유 피드 + 내 페이지) · 페이지 보기(요약·백링크·**인증 이력 차트**·
**투자 수익**·투자/인증 폼) · 새 페이지. JSON API는 `/api/*`. 로그인은 이름만
입력하는 최소 형태(MVS).
