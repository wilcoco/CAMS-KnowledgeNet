# 설계 문서 (Design)

이 폴더는 **설계 기록**이다. 무엇을 *왜* 그렇게 정했는지의 근거가 여기 있다.

> **미션:** [`../MISSION.md`](../MISSION.md) — *AI 생성·활용의 비효율을 개선한다("덜 쓰고 더 나은 지식").*
> **제1원리:** [`00-epigraph.md`](00-epigraph.md) — *踏雪野中去 不須胡亂行 / 今日我行跡 遂作後人程.*
> 어떤 기능을 더하든 늘 이 한 수로 돌아와 묻는다: *"어지러이 걷는 길인가, 뒷사람의 길이 되는 걸음인가."*

| 파일 | 내용 |
|------|------|
| [`00-epigraph.md`](00-epigraph.md) | **제1원리(Epigraph).** 답설야중거 — 함부로 걷지 말 것(많이가 아니라 두루), 오늘 내 자취가 뒷사람의 길이 됨(정직·독립·가시성). 모든 설계의 맨 앞. |
| [`01-design-notes.md`](01-design-notes.md) | **1차 설계 논의 정리본 (원본, 정본).** 문제의식부터 첫 바퀴 시뮬레이션·사상적 검토·미해결 과제까지 전체 논리. |
| [`02-unified-recursion.md`](02-unified-recursion.md) | **2차 정리 — 통합 재귀 노드 모델.** 두 프로토타입을 한 노드 종류·한 모듈로 합치고 재귀시킨 기획 + 4단계 컷오버 + 평가=저작(§2.5). |
| [`03-decisions-log.md`](03-decisions-log.md) | **결정·대화 기록.** 세션에서 무엇을 왜 정했는지, 고친 버그(원인→조치→커밋), 미해결 과제. |
| [`04-positioning.md`](04-positioning.md) | **포지셔닝 — 이것이 무엇인가.** 위키피디아와의 근본 차이, 분권의 두 층위(권위=분권 / 인프라=아직 중앙), AI↔인간 역할. |
| [`05-private-public-endorse.md`](05-private-public-endorse.md) | **사적/공적 구별과 연동 — 다중통화 endorse.** 개념=공용 앵커 / 사적=층, 공통 코인+그룹 코인(비호환·자유발행·비태환·단방향), 검색=공통 prior+사적 오버레이. |
| [`06-search.md`](06-search.md) | **검색 — 하이브리드 색인(엣지).** 쓰기 시점 역색인(BM25,CJK)+임베딩, 검색은 O(매칭), 권위·그룹 사적 endorse로 재정렬(그룹마다 다른 순위). |
| [`07-dual-ontology.md`](07-dual-ontology.md) | **이중 온톨로지.** (a)보편 개념 / (b)맥락 펼침. ⚠️ UX는 08로 대체 — 기계장치만 기질로 잔류. |
| [`08-one-gesture.md`](08-one-gesture.md) | **단일 재귀 제스처.** slug든 드래그든 = 가리키면 우측에 주제가 열림 → 이미 정리됐으면 읽고, 부족하면 그 자리서 물어 가지치기. 재귀. slug/승격은 emergent. (a)/(b) 분기 폐기. |
| [`09-tree-explorer.md`](09-tree-explorer.md) | **좌측 IDE 트리 탐색기.** Root→서브 디렉토리로 위치를 비춤(클릭=이동, 어디든 현재 위치 강조). 계위(§2.5): 기여(보강/정정/후속/펼침)=펼침 가지, 드래그/슬러그=루트 밑 `→` 참조 잎. slug ⟂ 계위. |
| [`10-navigation-session.md`](10-navigation-session.md) | **내비게이션 세션 — 결정·로드맵·미결(살아있는 문서).** 이 세션 규칙·기획 보존. RAG 미배선 발견, 워크스트림 A(보강 RAG)·B(개인 대시보드/내보내기)·C(내비), 열린 결정. |
| [`11-llm-wiki-comparison.md`](11-llm-wiki-comparison.md) | **Karpathy "LLM Wiki" 대조.** 같은 공간 검증. 겹침(복리·위키링크·옵시디안·모순=fork) / 차별(커먼즈+경제+평가=저작+다인·자체IDE) / 흡수할 결핍(Ingest+raw층, Lint, log). 원문은 [`../refs/karpathy-llm-wiki.md`](../refs/karpathy-llm-wiki.md). |
| [`12-alignment-complexity.md`](12-alignment-complexity.md) | **정렬 복잡도 — LLM Wiki의 벽과 우회(핵심 포지셔닝).** 전역 일관성 = 초선형(≈제곱) 정렬 비용. 우리는 쓰기시점 slug 주소화(O(1) dedup)+모순 공존(fork)+점증 랭킹+사람 샤딩으로 국소·점증·emergent화. 불변식 4개. |
| [`13-footprint-economy.md`](13-footprint-economy.md) | **발자국 경제(초안).** 저자 영구 50% + 나머지 50%는 선행 발자국 지분 배당(선점=안목 보상). 가중치 w=f(L/M) track record, 규정타석 N>n 발동, 오목·clamp·정정환수 가드레일. 미정 knob: 무료/비용·f파라미터·저자감쇠. |
| [`14-human-centered-grounding.md`](14-human-centered-grounding.md) | **사람 중심 · 근거와 종합(분기 숙고).** LLM Wiki=사람크롤러+AI저자 vs 우리=사람판단+AI횃불. 출처=근거/발자국=판단(직교). 지형 따라 라우팅, 종합=이견보존 지형도, 콜드스타트는 웹→내부RAG. 커먼즈-우선 유지·덜짓고 더굴리기. |
| [`glossary.md`](glossary.md) | 핵심 용어집 (허브/권위/포크/잠복/색인재고/암묵지). |
| [`lineage.md`](lineage.md) | 설계 진화 계보 (256 → 391 → 새 설계 → 통합 재귀). |

파생 산출물은 상위 폴더에 있다:

- 실행 계획 → [`../roadmap.md`](../roadmap.md)
- 적대적 재검 → [`../critique.md`](../critique.md)
- 설계↔코드 대응 → [`../prototype.md`](../prototype.md)

> **읽는 순서 권장:** `01-design-notes.md`(정본) → `../prototype.md`(코드로 본
> 구현) → `../critique.md`(약점) → `../roadmap.md`(다음 할 일).
