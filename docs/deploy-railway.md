# Railway 배포 가이드 — 검증된 소셜 위키 (MVS)

Postgres + API 서버 구성으로 Railway에 배포한다. 코드 변경 없이 환경변수만으로
SQLite(로컬) ↔ Postgres(배포)가 전환된다.

---

## 구성 요약

```
GitHub repo ──push──▶ Railway
                        ├─ Web 서비스 (uvicorn, Nixpacks 빌드)
                        │    · /        HTML 위키 UI
                        │    · /api/*   JSON API
                        │    · /api/health  헬스체크
                        └─ Postgres 플러그인 ──DATABASE_URL──▶ Web 서비스
```

- **빌드:** Nixpacks가 `requirements.txt`(`-e .[service]`)로 패키지+의존성 설치.
- **시작:** `uvicorn nightwish.webapp.app:app --host 0.0.0.0 --port $PORT`
  (`Procfile`·`railway.json` 둘 다 지정).
- **DB 초기화:** 앱 시작 시 `init_db()`가 테이블을 `create_all`(MVS, Alembic 없음).
- **영속성:** `DATABASE_URL`이 있으면 Postgres, 없으면 `./nightwish.db`(SQLite).

---

## 단계

1. **저장소 푸시** (이 브랜치).

2. **Railway 프로젝트 생성** → *New Project* → *Deploy from GitHub repo* →
   이 저장소/브랜치 선택. Nixpacks가 자동 감지·빌드한다.

3. **Postgres 추가** → 프로젝트에서 *New* → *Database* → *Add PostgreSQL*.
   Railway가 웹 서비스에 **`DATABASE_URL`을 자동 주입**한다. (구형 `postgres://`
   접두사는 앱이 `postgresql://`로 자동 정규화.)

4. **환경변수 설정** (웹 서비스 → *Variables*). `.env.example` 참고:
   - `ANTHROPIC_API_KEY` — 실제 LLM 북키핑을 켤 때. 없으면 stub 북키퍼로 폴백.
   - `NIGHTWISH_LLM_MODEL` — (선택) 기본 `claude-opus-4-8`. 비용↓ 원하면 `claude-haiku-4-5`.
   - `DATABASE_URL` — Postgres 플러그인이 자동 주입하므로 보통 직접 설정 불필요.
   - `PORT` — Railway가 자동 주입.

5. **배포 확인:** 도메인 생성 후 `GET https://<도메인>/api/health` → `{"status":"ok"}`.

---

## API 사용 (배포 후)

```bash
BASE=https://<도메인>

# 페이지 생성 (X-User 헤더로 사용자 식별; 신규면 자동 생성 + 초기 포인트)
curl -s -X POST $BASE/api/pages -H 'Content-Type: application/json' \
  -H 'X-User: Json' \
  -d '{"title":"무도장 하이그로시","body":"소재·금형 3축. [[금형 온도]]","shared":true}'

# 인증 (외부 측정)
curl -s -X POST $BASE/api/pages/무도장-하이그로시/verify -H 'Content-Type: application/json' \
  -d '{"metric":"불량률","baseline":8,"observed":2,"direction":"lower_better","min_rel_improvement":0.2}'

# 인증 투자 (검증된 페이지면 선행 투자자에게 일부가 흐름)
curl -s -X POST $BASE/api/pages/무도장-하이그로시/invest -H 'Content-Type: application/json' \
  -H 'X-User: User-C' -d '{"amount":50}'

# 피드 / 단건 조회
curl -s $BASE/api/feed
curl -s $BASE/api/pages/무도장-하이그로시
```

---

## 주의 / 한계 (MVS)

- **인증 없음:** 사용자 식별이 `X-User` 헤더(이름)뿐이다. 공개 배포 시 실제 인증을
  반드시 추가할 것. (범위 밖 — 로드맵 P3.)
- **마이그레이션 없음:** 스키마 변경 시 `create_all`만으로는 부족하다. 컬럼 추가 등은
  Alembic 도입 필요(P3).
- **LLM 비용:** 키를 설정하면 페이지 생성/편집마다 LLM 호출이 일어난다. 비용이
  걱정되면 `NIGHTWISH_LLM_MODEL=claude-haiku-4-5` 로 낮추거나 키를 빼서 stub 사용.
- **Python 버전:** 코드가 3.10+ 문법을 쓴다. Nixpacks 기본 Python이 3.10 미만이면
  `NIXPACKS_PYTHON_VERSION=3.11` 변수를 설정.
