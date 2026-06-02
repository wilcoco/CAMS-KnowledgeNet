# 운영 · 재배포 · 복구 런북 (Operations)

> 이 클라우드 개발 컨테이너는 **임시(ephemeral)** 다 — 비활성 시 회수되고, 다음
> 세션은 git에서 새로 클론한다. 따라서 **재배포·복구에 필요한 모든 것은 git에
> 있어야 한다.** 이 문서가 그 단일 출처다.

## 1. 데이터는 어디 사는가 (가장 중요)

| 대상 | 위치 | 컨테이너 죽으면? |
|------|------|-----------------|
| **소스 코드** | git (`origin/main`) | 안전 — 새로 클론 |
| **운영 데이터**(노드·기여·경제) | **Railway Postgres** (`DATABASE_URL` 설정 시) | **안전** — DB는 별도 영속 |
| 운영 데이터 (DB 미설정 시) | 임시 파일 `data/app.json` | **유실됨** ⚠️ |
| 빌드 캐시·`__pycache__` | 컨테이너 | 재생성됨 (무관) |

핵심: **`DATABASE_URL`이 앱에 연결돼 있어야 데이터가 산다.** 상태줄 🟢/🟡/🔴 또는
`GET /api/state` → `persistence` 로 확인.

### 스키마 (정규화 — 1행 = 1개체)

운영 데이터는 **정규화 테이블**에 들어간다(`pgstore.py`). 노드 하나가 한 행이고
SQL로 조회·인덱싱된다.

| 테이블 | 내용 |
|--------|------|
| `node` | 노드 1개당 1행 (질문·답·author·last_editor·action·space·parent_id…). `id`/`author`/`space`/`parent_id` 인덱스 |
| `node_link` | 위키링크 `[[제목]]` (node→target) |
| `linker` | 평가=저작 순서 (node→evaluator) — 먼저 평가한 사람 우선 |
| `node_authority` / `user_hub` | 노드 권위 / 사용자 안목(hub) |
| `stake` / `endorser` | 노드별 스테이크 / 인도스 순서 |
| `balance` | 계정별 잔액 |
| `meta` | 스칼라(clock·rates·mode·`saved_at`…) |

> 옛 단일행 블롭(`nightwish_state`)은 첫 부팅 때 위 테이블로 **자동 이관**되고
> 원본은 롤백용으로 남는다. `nightwish_probe`는 `/api/dbcheck` 진단용.

조회 예:
```sql
SELECT id, author, question FROM node WHERE author = 'Json';   -- 인덱스 조회
SELECT node_id, evaluator FROM linker ORDER BY node_id, ord;   -- 누가 평가(저작)했나
SELECT account, value FROM user_hub ORDER BY value DESC;        -- 안목 순위
SELECT count(*) FROM node;                                      -- 노드 수
```

## 2. 환경변수

| 변수 | 용도 | 없으면 |
|------|------|--------|
| `DATABASE_URL` | Postgres 영속 (Railway가 주입; 보통 `${{Postgres.DATABASE_URL}}` 레퍼런스를 앱 서비스 Variables에 추가) | 임시 파일 폴백(유실 위험) |
| `NIGHTWISH_DATABASE_URL` | 위 변수 명시적 override | — |
| `NIGHTWISH_APP_DB` | 파일 모드일 때 스냅샷 경로 (기본 `data/app.json`) | 기본값 |
| `NIGHTWISH_ENABLE_LLM` | `1`이면 실제 Claude로 답 생성 | 오프라인 스텁 답 |
| `ANTHROPIC_API_KEY` | LLM 모드 키 | LLM 비활성 |
| `NIGHTWISH_LLM_MODEL` | 모델 override | `claude-opus-4-8` |
| `PORT` | Railway가 주입 | uvicorn 기본 |

## 3. 재배포 (컨테이너/서비스를 새로 띄울 때)

1. Railway에서 이 저장소(브랜치 `main`)에 서비스 연결 → [`nixpacks.toml`](../nixpacks.toml)이
   `uvicorn nightwish.unified:app --host 0.0.0.0 --port $PORT` 로 기동.
2. **Postgres 플러그인**을 프로젝트에 추가.
3. 앱 서비스 **Variables**에 `DATABASE_URL = ${{Postgres.DATABASE_URL}}` 추가.
4. (선택) LLM 쓰려면 `NIGHTWISH_ENABLE_LLM=1`, `ANTHROPIC_API_KEY=…` 추가.
5. 배포 후 `https://<앱>/api/state` 의 `persistence.backend == "postgres"` 확인 →
   상태줄이 🟢 DB저장이면 끝.

로컬에서:

```bash
pip install -e ".[service]"        # fastapi, uvicorn, pydantic, psycopg
nightwish-app                      # = uvicorn nightwish.unified:app
python -m pytest -q                # 전체 테스트
```

## 4. 백업 / 스냅샷 받기

- **Postgres 모드:** 데이터는 `nightwish_state` 테이블의 `id=1` JSONB 한 행. Railway
  Postgres 백업 또는 `SELECT data FROM nightwish_state WHERE id=1` 로 그대로 덤프.
- **앱 통해서:** `GET /api/state`(요약), 전체 스냅샷은 DB 행이 곧 스냅샷이다(스키마
  `unified-1`: `{tree, econ}`). 같은 JSON을 새 인스턴스의 DB/파일에 넣으면 그대로 복원.

## 5. 롤백

- 통합 앱은 기존 `wiki.json`/레거시 스냅샷을 **원본 보존**하며 앞으로 쓴다. 레거시
  `nightwish-mvp`(`nightwish.mvp:app`)로 start 커맨드를 바꾸면 옛 앱으로 되돌아간다.
- 코드는 git 히스토리로 임의 커밋으로 롤백 가능.

## 6. 흔한 증상 → 원인

| 증상 | 원인 | 조치 |
|------|------|------|
| 새로고침하면 글이 사라짐 | 🟡 임시 파일 모드 | `DATABASE_URL` 연결 (§3) |
| 🟢인데도 글·인도스가 안 박힘 | 인스턴스 ≥2가 단일 스냅샷 행을 서로 덮어씀(clobber) | 현재 코드는 매 요청 DB 재로딩 + advisory lock으로 방지. 더 확실히 하려면 **앱 replica 수를 1**로 두거나, 레거시 `mvp`를 **같은 DB에 동시 배포하지 말 것** |
| 인도스/후속질문 404 | 위와 동일(재시작로 노드 유실) | 〃 |
| AI 답이 한참 무응답 | LLM 네트워크 지연 | 상단 "AI 생성 중…" 배너로 진행 표시; 정상 |
| 다른 질문에 옛 답이 나옴 | (구버전) | 현재는 "AI에게 묻기"가 항상 새로 생성 |
