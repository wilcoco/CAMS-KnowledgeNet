# Nightwish

> 온톨로지 기반 지식 평가·보상 시스템 — Living-ontology knowledge evaluation & reward system.
>
> **대외비 / Confidential — 미공개 사업 아이디어.**

사람이 AI를 **재료**로 삼아 **검증된 집단 지식 구조(온톨로지)**를 짓고, 그 구조
자체가 다음 질문의 답이 되어 가치를 만든다. 평가의 화폐는 *기여 + 그에 건
확신(포인트)*이며, 인류의 **암묵지(暗默知)를 시장 유인으로 형식지로 끌어내**
영구 보존·재사용하는 것이 최종 목적이다.

기반 자산: 등록특허 **10-0913256**, **10-0952391** (발명자 홍정수, 2005 출원).

---

## 이 저장소에 무엇이 있나

| 영역 | 위치 | 내용 |
|------|------|------|
| **설계 기록** | [`docs/design/`](docs/design/) | 1차 설계 논의 정리본(원본) · 용어집 · 진화 계보 |
| **실행 로드맵** | [`docs/roadmap.md`](docs/roadmap.md) | 부트스트랩(첫 카토 온보딩) · MVP 우선순위 · 검증 닻 · 화폐공학 · 거버넌스 · 법무 |
| **설계 비평/압박 테스트** | [`docs/critique.md`](docs/critique.md) | 화폐공학 균열 · 폰지 방어 · 거버넌스 급소 · 사상적 검토를 적대적으로 재검 |
| **관련 연구/외부 대조** | [`docs/related-work.md`](docs/related-work.md) | 외부 관점(지식그래프≠검색 등)과 일치·차이·빈틈 대조 |
| **프로토타입 매핑** | [`docs/prototype.md`](docs/prototype.md) | 설계 개념 → 코드 1:1 대응표 |
| **동작하는 MVP** | [`src/nightwish/`](src/nightwish/) | 온톨로지 트리 · 허브/권위 엔진 · 포인트 경제 · **검증 닻** · **거버넌스** · 질의 파이프라인 |
| **HTTP 서비스 + 웹 UI** | [`src/nightwish/service.py`](src/nightwish/service.py) · [`static/`](src/nightwish/static/) | FastAPI 백엔드(질문/포크/기여/스테이킹/배당/검증) + 트리를 보고 조작하는 웹 화면. JSON 스냅샷 영속화([`store.py`](src/nightwish/store.py)) |
| **기반 특허 분석** | [`docs/patents/`](docs/patents/) | 등록공보 원문 + 1차 출처 대조 분석(서지·청구항·법적상태) |
| **테스트** | [`tests/`](tests/) | 77개 단위 테스트 (불변식 · 특허 청구항 수치 · 서비스 E2E) |
| **예제** | [`examples/`](examples/) | 첫 바퀴 시뮬레이션 · 배당 라우팅 · **검증 닻 첫 바퀴(P0)** |

---

## MVP 프로토타입 — 4개의 협력 부품

이 프로토타입은 **메커니즘**(생산 엔지니어링이 아니라)을 읽고, 테스트하고,
추론할 수 있게 일부러 작고 의존성 없이 만들었다.

1. **`scoring.py`** — 특허 10-0913256의 **증분 허브/권위 엔진.** 수렴 반복연산을
   *링크 순서*로 치환("링크 순서 가중") → 신규 콘텐츠 실시간 평가. 평가의 화폐는
   *인기*가 아니라 *안목(선행 발견력)*. 허브 산식은 선택 가능: **`count`(청구항 2)
   · `sum`(청구항 3)** = 특허 충실, **`harmonic`** = MVP 변형(기본·부트스트랩 친화).
2. **`tree.py`** — **살아있는 온톨로지 트리.** 노드 = 인간Q + AI답. 행위 =
   계승(follow) · 분기(fork) · 추가 기여(contribute). 핵심 규칙 **"포인트 크기 =
   기여 크기"**. 죽지 않는 가지(잠복·부활).
3. **`economy.py`** — **닫힌 포인트 경제.** UBI 발행 · 스테이킹 ·
   *부가가치로 자격이 걸린* 배당(빈손 노드 우회) · 에스크로 현상금 · 소각 싱크.
4. **`pipeline.py`** — **3단계 질의 흐름** (검색 → AI → 사람).

> **2차 이터레이션** — 비평(`critique.md`)이 지목한 균열을 코드로 닫았다:
> **`verification.py`**(외부 현실 닻 → 검증된 가지에서만 배당) · **`governance.py`**
> (참여자 N명 시 규칙변경권 자동 분권) · 배당 **시간붕괴**(자본증식 차단)와
> **잠복 포인트 회수**(인플레-잠김 딜레마)는 `economy.py`에 추가됨.

`simulation.py`가 이들을 엮어 설계 문서 §7의 **"첫 바퀴" 시뮬레이션**을 재현한다
— 최종 원장이 설계 수치와 정확히 일치하고, **암묵지 병목**(카토의 손끝 지식이
끝내 안 풀림)을 드러낸다.

---

## 빠른 시작

```bash
pip install -e .            # 코어 라이브러리 (의존성 없음)

python -m nightwish.simulation    # §7 "첫 바퀴" 시뮬레이션 리포트
python examples/dividend_demo.py  # 부가가치-게이트 배당 라우팅 데모
python examples/verified_wheel.py # [P0] 검증 닻이 배당을 여는 첫 바퀴

pip install -e ".[dev]"           # + pytest, httpx
python -m pytest -q               # 77개 테스트
```

### ⭐ MVP — 공유 LLM 위키 (Obsidian + LLM, 사용자 간 공유)

설계 §2.3의 **제3극(소유 O + 연결 O)** 을 가장 가볍게 구현한 제품. 마크다운 페이지를
`[[위키링크]]` 로 잇고, LLM이 초안을 거들고, **누가 먼저 좋은 문서를 알아보고 링크했나
(허브/권위 = 특허 10-0913256)** 가 랭킹으로 드러난다.

```bash
pip install -e ".[service]"
nightwish-mvp                     # 또는: uvicorn nightwish.mvp:app
# → http://127.0.0.1:8000/  에서 페이지 작성·[[링크]]·AI 초안·인기문서/안목기여자 랭킹
```

- 상태(위키 + 포인트 경제)는 `$NIGHTWISH_WIKI_DB`(기본 `data/wiki.json`) 단일 스냅샷에 영속화.
- **그래프 뷰**: 상단 🕸 버튼 → 페이지 연결망 시각화(노드 크기=권위, 클릭 시 이동). API: `GET /api/graph`.
- **포인트 경제**: 발행(UBI) → 좋은 문서에 **추천(스테이킹)** → 작성자·선행 추천자에게 **배당**(시간가중) + 소각. API: `POST /api/mint` · `POST /api/endorse` · `GET /api/ledger`.
- **실제 LLM 초안(선택)**: 기본은 오프라인 스텁. `pip install -e ".[llm]"` 후 환경변수
  `NIGHTWISH_ENABLE_LLM=1` + `ANTHROPIC_API_KEY=…` 를 주면 Claude(기본 `claude-opus-4-8`)로 초안 생성. 코드로는 `nightwish.mvp.set_ai(fn)`.
- 엔드포인트: `GET/POST /api/pages`, `/api/search`, `/api/draft`, `/api/scores`, `/api/graph`, `/api/{mint,endorse,ledger}`, `/api/resolve/{title}`.

**Railway 배포:** 이 저장소를 Railway에 연결하면 [`nixpacks.toml`](nixpacks.toml)/[`Procfile`](Procfile)
이 `0.0.0.0:$PORT`로 `nightwish.mvp:app`을 띄운다. **브랜치별로 서비스를 따로 두면** 각
브랜치가 독립 배포·독립 URL을 가진다. 상태 유지는 Railway Volume을 마운트하고
`NIGHTWISH_WIKI_DB=/data/wiki.json` 로 지정.

### 서비스 실행 (온톨로지 엔진 데모 — HTTP API + 웹 UI)

```bash
pip install -e ".[service]"       # + fastapi, uvicorn, pydantic
nightwish-serve                   # 또는: uvicorn nightwish.service:app
# → http://127.0.0.1:8000/  에서 질문→검색/AI/사람, 포크·기여·스테이킹·검증을 직접 조작
```

- 상태는 `data/state.json`(환경변수 `NIGHTWISH_DB`로 변경) 스냅샷에 영속화 — 재시작에도 트리·원장·점수 유지.
- 스테이지 ②의 **AI는 교체 가능**: 기본은 키·네트워크 없이 도는 오프라인 스텁(`offline_ai`),
  실모델은 `nightwish.service.set_ai(fn)`으로 주입. 질문에 `[tacit]`를 넣으면 AI가 사양 → 사람 라우팅(스테이지 ③)을 시연.
- 주요 엔드포인트: `POST /api/ask`, `/api/nodes/{id}/{follow,fork,contribute,verify}`, `POST /api/mint`, `GET /api/{tree,scores,ledger,state}`. OpenAPI 문서는 `/docs`.

### 첫 바퀴 시뮬레이션 출력 (요약)

```
질문: 블랙 하이그로시를 도장 없이 사출만으로?
  #001-a  AI 답(3축 인과)          Json   stake 100  -> 채택, PUBLIC
  #001-b  도요타 사례 링크(약함)     User-B stake  10  -> 발굴
  #002    FORK: MIC 한계/비산석     User-C stake  50  -> 강한 부가가치
  현상금   Json -> User-B 직접 호출   Json   escrow 500 -> 미채택 -> 반환
  #003    포인터: '카토가 있다'      (외부)            -> 잠복(DORMANT)

원장 최종:  Json 가용 900 / 스테이킹 100 | User-B 10 | User-C 50   ← 설계 §7 일치
병목:       깊은 암묵지 질의 -> UNRESOLVED (카토 손끝 지식 끝내 안 풀림)
```

---

## 핵심 설계 명제 (한눈에)

- **인덱스 ≠ 인텔리전스.** RAG의 답변처를 *웹(흔한 색인 재고)* → *사람이 검증한
  온톨로지(비대체 구조)*로 바꾼다.
- **소유 + 연결.** Obsidian(소유O 연결X)도 네이버(소유X 연결O)도 아닌 제3극.
  그래서 **평가 설계가 전부.**
- **수렴을 거부한다.** 256은 하나의 순위로 수렴. 새 설계는 가지치고 잠복하고
  부활하며 정답을 박제하지 않는다.
- **외부 현실(ground truth)만이 유일한 닻.** "부가가치=동의"의 순환은 제조
  도메인(수율·물성)에서만 닫힌다 → 첫 노드는 검증 가능한 현실 문제로.
- **암묵지의 시장 해방.** 로열티 = 지속 배당 → "비법을 숨기는 것보다 푸는 것이
  더 큰 수익"으로 길드의 논리를 뒤집는다.

자세한 내용은 [`docs/design/`](docs/design/)부터 읽으세요.

---

## 권리·법무 주의

기반 두 특허는 2005-04-14 출원 → 존속기간(출원+20년) **2025-04-14 만료**, 현재
공공영역 가능성 높음. **알고리즘 자체는 더 이상 독점 해자가 아니며, 해자는
"무엇을 평가하느냐(적용 도메인)"로 이동한다.** 정확한 권리 상태는 KIPRIS
등록원부 확인 필요(로드맵 §법무 참조).
