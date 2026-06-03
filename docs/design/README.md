# 설계 문서 (Design)

이 폴더는 **설계 기록**이다. 무엇을 *왜* 그렇게 정했는지의 근거가 여기 있다.

| 파일 | 내용 |
|------|------|
| [`01-design-notes.md`](01-design-notes.md) | **1차 설계 논의 정리본 (원본, 정본).** 문제의식부터 첫 바퀴 시뮬레이션·사상적 검토·미해결 과제까지 전체 논리. |
| [`02-unified-recursion.md`](02-unified-recursion.md) | **2차 정리 — 통합 재귀 노드 모델.** 두 프로토타입을 한 노드 종류·한 모듈로 합치고 재귀시킨 기획 + 4단계 컷오버 + 평가=저작(§2.5). |
| [`03-decisions-log.md`](03-decisions-log.md) | **결정·대화 기록.** 세션에서 무엇을 왜 정했는지, 고친 버그(원인→조치→커밋), 미해결 과제. |
| [`04-positioning.md`](04-positioning.md) | **포지셔닝 — 이것이 무엇인가.** 위키피디아와의 근본 차이, 분권의 두 층위(권위=분권 / 인프라=아직 중앙), AI↔인간 역할. |
| [`05-private-public-endorse.md`](05-private-public-endorse.md) | **사적/공적 구별과 연동 — 다중통화 endorse.** 개념=공용 앵커 / 사적=층, 공통 코인+그룹 코인(비호환·자유발행·비태환·단방향), 검색=공통 prior+사적 오버레이. |
| [`06-search.md`](06-search.md) | **검색 — 하이브리드 색인(엣지).** 쓰기 시점 역색인(BM25,CJK)+임베딩, 검색은 O(매칭), 권위·그룹 사적 endorse로 재정렬(그룹마다 다른 순위). |
| [`glossary.md`](glossary.md) | 핵심 용어집 (허브/권위/포크/잠복/색인재고/암묵지). |
| [`lineage.md`](lineage.md) | 설계 진화 계보 (256 → 391 → 새 설계 → 통합 재귀). |

파생 산출물은 상위 폴더에 있다:

- 실행 계획 → [`../roadmap.md`](../roadmap.md)
- 적대적 재검 → [`../critique.md`](../critique.md)
- 설계↔코드 대응 → [`../prototype.md`](../prototype.md)

> **읽는 순서 권장:** `01-design-notes.md`(정본) → `../prototype.md`(코드로 본
> 구현) → `../critique.md`(약점) → `../roadmap.md`(다음 할 일).
