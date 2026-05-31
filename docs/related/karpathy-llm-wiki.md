# 외부 레퍼런스: Karpathy의 "LLM Wiki" (2026-04)

**출처:** Andrej Karpathy, GitHub Gist `llm-wiki` (2026-04-04).
**왜 여기 있나:** 거의 *같은 진단*("RAG는 매번 재발견, 축적 없음")에서 출발한
독립 제안. Nightwish의 차별화 근거이자, ① 검색 단계의 구현 참고로 둔다.

> ⚠️ 이 문서는 외부 자료의 요약·해석이다. 원문은 위 Gist를 따른다.

---

## 1. 카파시 LLM Wiki 요약

**문제의식 (RAG 비판).** "LLM이 매 질문마다 지식을 처음부터 재발견한다. **축적이
없다.**" NotebookLM·파일 업로드는 매번 조각을 다시 끌어모을 뿐, 지속적 이해를
쌓지 않는다.

**3층 구조.**

1. **Raw Sources** — 불변(immutable). 단일 진실 원천(논문·기사·이미지·데이터).
2. **The Wiki** — LLM이 *전적으로 소유*하는 마크다운 층: 요약·엔티티 페이지·개념
   페이지·비교·종합. 새 소스가 오면 페이지를 만들고 갱신하고 상호참조를 유지.
3. **The Schema** — `CLAUDE.md`처럼 위키 구조·규약·워크플로를 LLM에게 알려주는 설정.

**분업.** 인간 = 소스 큐레이션·방향 지시·질문. LLM = **북키핑**(요약·교차참조·
일관성 유지). "지식베이스 유지의 고된 부분은 읽기·사고가 아니라 *북키핑*이다."

**소스 통합.** 단순 색인이 아니라 — 읽고 → 핵심 추출 → 기존 위키에 통합 →
엔티티/요약 갱신 → **기존 주장과 모순되는 지점 기록(reconcile)**.

**운영 파일.** `index.md`(내용 카탈로그), `log.md`(append-only 이력).

---

## 2. Nightwish와의 관계 — 같은 문제, 다른 답

두 설계 모두 "RAG = 매번 재발견, 축적 없음"을 비판하고 **지속적·상호연결된
구조에 지식을 컴파일**하자고 한다(설계 §1, §9). 그러나 답이 갈린다.

| 축 | 카파시 LLM Wiki | Nightwish |
|----|----------------|-----------|
| 사용자 | **단일 사용자** (개인 지식베이스) | **다중 사용자** (사람 간 온톨로지) |
| 평가 | **없음** | 허브/권위 + 포인트 (평가가 화폐) |
| 경제 | 없음 | UBI·스테이킹·배당·검증 닻 |
| 모순 처리 | **LLM이 조정(reconcile) → 수렴** | **포크로 분기 → 수렴 거부**, 후대가 판정 |
| 판정자 | LLM | **없음** (후속 베팅으로 사후 결정) |
| 진실 닻 | 원본 소스 | **외부 현실**(제조 수율/물성) |
| 노드 단위 | 엔티티/개념 페이지 | 인간Q + AI답 쌍 |

### 2.1 카파시 위키는 설계 §2.3 표의 "Obsidian 칸"에 정확히 들어간다

설계 §2.3:

| 모델 | 소유 | 연결 | 특징 |
|------|----|----|------|
| Obsidian | O | X | 자유롭지만 고립된 죽은 금고 (평가 없음 → 왜곡도 없음) |
| 네이버 | X | O | 가두고 헐값, 노출을 기여로 둔갑 |
| **본 시스템** | O | O | 소유+연결. 그 화폐가 "평가"라서 평가 설계가 전부 |

카파시 LLM Wiki는 Obsidian보다 *연결*이 강하지만(LLM이 상호참조 유지),
**여전히 단일 사용자·평가 없음**이다 → "소유 O, 연결 O, 평가 X". Nightwish는
바로 그 위에 **평가·경제·다중 동의·검증 닻**을 얹은 제3극이다.

### 2.2 결정적 차이: 수렴 vs 수렴 거부

- 카파시 위키: LLM이 모순을 **reconcile**해 *하나의 일관된 위키*로 수렴시킨다.
  소수 의견은 덮인다.
- Nightwish(§4.5): 모순을 **포크**로 분기시키고, 진 가지는 죽지 않고 **잠복**하다
  후대가 **부활**시킨다(갈릴레오 문제). 정답을 박제하지 않는다.

> 한 줄: 카파시 위키는 *진실을 하나로 모으는 도구*, Nightwish는 *진실의 경합을
> 살려두는 시장.*

---

## 3. Nightwish가 차용할 것 / 다르게 할 것

**차용 (그대로 흡수 가능):**
- LLM이 **북키핑**(요약·교차참조·일관성)을 맡는다는 분업 → Nightwish의 노드
  형식화·① 검색 단계의 엔진으로 직결.
- **3층 분리**(불변 raw / LLM 소유 wiki / schema) → 노드의 `answer`(LLM 재료)와
  `question`/스테이킹(사람 층)의 분리와 동형. raw 출처 불변성도 차용.
- `index.md` / `log.md` 운영 패턴 → 온톨로지 카탈로그·감사 로그(네이버 블랙박스의
  정반대인 "감사 가능성" 정체성과 일치).

**다르게 (Nightwish 고유):**
- 위키 층을 **LLM 단독 소유**로 두지 않는다. 모순은 reconcile하지 않고 **포크**.
- 페이지에 **평가·경제**(허브/권위·포인트·배당)를 부착 → 단일 사용자 도구가
  아니라 다중 사용자 시장.
- **외부 현실 닻**(검증된 가지에서만 배당)으로 "동의 담합" 순환을 닫는다.

---

## 4. 코드 연결점 (구현 시)

| 카파시 개념 | Nightwish 코드 연결 |
|-------------|---------------------|
| LLM 북키핑 위키 | `pipeline.QueryPipeline` ① 검색 단계 = "카파시식 위키 조회" |
| 새 소스 통합 | `tree.OntologyTree.contribute` (노드로 통합) |
| 모순 기록(reconcile) | **대체:** `tree.OntologyTree.fork` (조정 대신 분기) |
| `index.md` / `log.md` | 온톨로지 카탈로그 + 원장/감사 로그 (P3 영속성) |
| schema(CLAUDE.md) | 거버넌스 규칙(`governance.Governance`) + 노드 규약 |

> 요약: **Nightwish ≈ "카파시 LLM Wiki + 평가 화폐 + 다중 사용자 + 포크/잠복 +
> 외부 현실 닻".** 카파시 위키를 ① 단계의 *개인 북키핑 엔진*으로 흡수하되,
> 그 위에 평가·경제·경합 보존 층을 얹는 것이 Nightwish의 위치다.

---

## 출처

- Karpathy, `llm-wiki` Gist (원문):
  https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Data Science Dojo, "LLM Wiki by Andrej Karpathy" tutorial:
  https://datasciencedojo.com/blog/llm-wiki-tutorial/
- MindStudio, "What Is Andrej Karpathy's LLM Wiki":
  https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code
- AI Critique, "Karpathy's latest concept 'LLM Wiki'" (2026-05-08):
  https://www.aicritique.org/us/2026/05/08/andrej-karpathys-latest-concept-llm-wiki-and-the-future-of-enterprise-knowledge/
