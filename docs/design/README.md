# 설계 문서 (Design)

이 폴더는 **설계 기록**이다. 무엇을 *왜* 그렇게 정했는지의 근거가 여기 있다.

| 파일 | 내용 |
|------|------|
| [`01-design-notes.md`](01-design-notes.md) | **1차 설계 논의 정리본 (원본, 정본).** 문제의식부터 첫 바퀴 시뮬레이션·사상적 검토·미해결 과제까지 전체 논리. |
| [`02-unified-recursion.md`](02-unified-recursion.md) | **2차 정리 — 통합 재귀 노드 모델.** 두 프로토타입을 한 노드 종류·한 모듈로 합치고 재귀시킨 기획 + 4단계 컷오버. |
| [`glossary.md`](glossary.md) | 핵심 용어집 (허브/권위/포크/잠복/색인재고/암묵지). |
| [`lineage.md`](lineage.md) | 설계 진화 계보 (256 → 391 → 새 설계 → 통합 재귀). |

파생 산출물은 상위 폴더에 있다:

- 실행 계획 → [`../roadmap.md`](../roadmap.md)
- 적대적 재검 → [`../critique.md`](../critique.md)
- 설계↔코드 대응 → [`../prototype.md`](../prototype.md)

> **읽는 순서 권장:** `01-design-notes.md`(정본) → `../prototype.md`(코드로 본
> 구현) → `../critique.md`(약점) → `../roadmap.md`(다음 할 일).
