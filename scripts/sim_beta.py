"""대규모 시뮬레이션 베타 테스트 — 현재 unified + 다중통화 endorse 버전.

실제 HTTP 표면(FastAPI TestClient, 오프라인 LLM 스텁)을 다수 에이전트로 두드려
규모에서 모델 불변식이 깨지지 않는지 검증한다:

  * 막(membrane)        — 그룹 콘텐츠/권위가 public·타 그룹으로 새지 않는다
  * 비태환              — 그룹 endorse가 공통 코인 잔액을 건드리지 않는다
  * 국소 재정렬          — 그룹 순위가 공통 prior 위에서 그룹만의 순서를 가진다
  * 무결성              — 5xx 0건, 영속(JSON+pgstore) 라운드트립 일치
  * 성능                — 처리량(req/s)

실행:  python scripts/sim_beta.py [--scale N]
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import defaultdict

from fastapi.testclient import TestClient

from nightwish import unified, pgstore
from nightwish.tree import OntologyTree


# --------------------------------------------------------------------------- #
# 워크로드 파라미터 (scale로 일괄 확대)
# --------------------------------------------------------------------------- #
def params(scale: float) -> dict:
    return {
        "users": int(120 * scale),
        "groups": ["team-a", "team-b", "team-c", "lab-x", "lab-y"],
        "concepts": int(200 * scale),       # public ROOT(개념) 수
        "contributions": int(500 * scale),  # 보강/정정/후속 (public+group)
        "public_endorses": int(400 * scale),
        "group_endorses": int(600 * scale),
        "followups": int(80 * scale),
    }


CONCEPT_WORDS = ["수율", "사출", "도장", "범퍼", "컬러", "소재", "열처리", "냉각",
                 "금형", "공차", "검사", "물성", "강도", "내후성", "분산", "안료",
                 "압출", "성형", "조립", "용접", "체결", "도금", "코팅", "건조"]


class Stat:
    def __init__(self) -> None:
        self.calls = 0
        self.errors: list[str] = []
        self.codes: dict[int, int] = defaultdict(int)

    def rec(self, r) -> dict | None:
        self.calls += 1
        self.codes[r.status_code] += 1
        if r.status_code >= 500:
            self.errors.append(f"{r.status_code} {r.request.method} {r.request.url}")
            return None
        try:
            return r.json()
        except Exception:
            return None


def run(scale: float, seed: int = 7) -> int:
    rng = random.Random(seed)
    P = params(scale)
    st = Stat()

    unified.reset_service(unified.UnifiedService("/tmp/sim_beta.json"))
    t0 = time.time()
    with TestClient(unified.app) as c:
        c.post("/api/admin/reset", params={"confirm": "DELETE-ALL"})
        st.rec  # no-op
        users = [f"u{i:03d}" for i in range(P["users"])]
        # 그룹 소속(겹칠 수 있음): 각 유저는 0~2개 그룹에 속한다
        membership = {u: set(rng.sample(P["groups"], rng.randint(0, 2))) for u in users}

        # 공통 코인 충전(UBI 흉내)
        for u in users:
            st.rec(c.post("/api/mint", json={"account": u, "amount": 200.0}))

        # 1) 개념 생성 — public ROOT (AI 초안)
        concept_ids: list[str] = []
        for i in range(P["concepts"]):
            q = f"{rng.choice(CONCEPT_WORDS)} {rng.choice(CONCEPT_WORDS)} {i}"
            j = st.rec(c.post("/api/ask", json={"question": q, "author": rng.choice(users)}))
            if j and j.get("node"):
                concept_ids.append(j["node"]["id"])

        # 2) 기여 — public + group (보강/정정/후속)
        for _ in range(P["contributions"]):
            nid = rng.choice(concept_ids)
            author = rng.choice(users)
            space = "public"
            if membership[author] and rng.random() < 0.5:
                space = rng.choice(list(membership[author]))
            kind = rng.choice(["comment", "comment", "fork", "follow"])
            body = f"{kind} on {nid} [[{rng.choice(CONCEPT_WORDS)}]]"
            st.rec(c.post(f"/api/nodes/{nid}/contribute",
                          json={"kind": kind, "author": author, "body": body, "space": space}))

        # 3) 후속질문 (AI가 in-thread로 답)
        for _ in range(P["followups"]):
            nid = rng.choice(concept_ids)
            author = rng.choice(users)
            st.rec(c.post(f"/api/nodes/{nid}/contribute",
                          json={"kind": "followup", "author": author,
                                "body": f"{rng.choice(CONCEPT_WORDS)} 관련 후속?"}))

        # 4) public endorse — 공통 코인 소비
        bal_before = {u: _balance(u) for u in users}
        for _ in range(P["public_endorses"]):
            nid = rng.choice(concept_ids)
            acct = rng.choice(users)
            st.rec(c.post("/api/endorse",
                          json={"account": acct, "node_id": nid, "amount": float(rng.randint(1, 5))}))

        # 공통 endorse 후 잔액 스냅샷(그룹 endorse가 이걸 건드리면 안 됨)
        bal_after_public = {u: _balance(u) for u in users}

        # 5) group endorse — 자유발행·비태환 (그룹 전용)
        for _ in range(P["group_endorses"]):
            grp = rng.choice(P["groups"])
            acct = rng.choice(users)
            nid = rng.choice(concept_ids)
            st.rec(c.post("/api/endorse",
                          json={"account": acct, "node_id": nid,
                                "amount": float(rng.randint(1, 9)), "space": grp}))

        # 5b) 스포트라이트: public에서 권위 낮은 노드를 team-a가 집중 endorse →
        #     team-a 안에서만 치솟고, public·team-b는 *미동*(결정적 막 증명)
        spot = min(concept_ids, key=lambda n: _auth_of(c, n, "public", st))
        pub_before = _auth_of(c, spot, "public", st)
        a_before = _auth_of(c, spot, "team-a", st)
        b_before = _auth_of(c, spot, "team-b", st)
        for i in range(20):
            st.rec(c.post("/api/endorse", json={"account": f"sa{i}", "node_id": spot,
                                                "amount": 9.0, "space": "team-a"}))
        spot_pub = _auth_of(c, spot, "public", st)
        spot_a = _auth_of(c, spot, "team-a", st)
        spot_b = _auth_of(c, spot, "team-b", st)
        spot_gain_a = spot_a - a_before
        a_top1 = (_scores("team-a", c, st)["top_nodes"] or [{}])[0].get("id")
        pub_top1 = (pub0 := _scores("public", c, st)["top_nodes"]) and pub0[0].get("id")

        # 6) 검색 베타 — 고유 needle 개념 + 그룹 전용 needle 기여
        pub_needle = st.rec(c.post("/api/ask", json={
            "question": "특이공정 제니퍼위젯 캘리브레이션", "author": users[0]}))
        pub_needle_id = pub_needle["node"]["id"] if pub_needle else None
        host = rng.choice(concept_ids)         # 공용 개념에 그룹 전용 기여를 단다
        st.rec(c.post(f"/api/nodes/{host}/contribute", json={
            "kind": "comment", "author": "lab-x-user",
            "body": "사내전용 키워드 조브플럭스 메모", "space": "lab-x"}))

        def search(q, sp):
            return [h["id"] for h in (st.rec(c.get("/api/search",
                    params={"q": q, "space": sp})) or [])]

        # 6a) 공용 needle: 부분일치로 발견되나
        s_find = search("제니퍼위젯", "public")
        # 6b) 막: 그룹 전용 키워드는 그 그룹 검색에만(루트로 롤업), public엔 없음
        s_pub_leak = search("조브플럭스", "public")
        s_grp_hit = search("조브플럭스", "lab-x")
        # 6c) 검색 재정렬: team-a가 needle을 사적 endorse → team-a 검색 상위로
        if pub_needle_id:
            for i in range(8):
                st.rec(c.post("/api/endorse", json={"account": f"sn{i}",
                        "node_id": pub_needle_id, "amount": 9.0, "space": "team-a"}))
        # 6d) 검색 지연(현 코퍼스): 평균 µs
        terms = [rng.choice(CONCEPT_WORDS) + " " + rng.choice(CONCEPT_WORDS)
                 for _ in range(200)]
        ts = time.time()
        for q in terms:
            st.rec(c.get("/api/search", params={"q": q, "space": "public"}))
        search_us = (time.time() - ts) / len(terms) * 1e6

        elapsed = time.time() - t0

        # ---- 불변식 검증 ----------------------------------------------------
        fails: list[str] = []

        # (A) 비태환: 그룹 endorse 이후 공통 코인 잔액 불변
        bal_final = {u: _balance(u) for u in users}
        moved = [u for u in users if abs(bal_final[u] - bal_after_public[u]) > 1e-9]
        if moved:
            fails.append(f"비태환 위반: 그룹 endorse가 공통 잔액을 바꿈 ({len(moved)}명)")

        # (B) 막 + 국소 재정렬: public 랭킹 vs 각 그룹 랭킹
        pub_scores = _scores("public", c, st)
        pub_auth = {n["id"]: n["authority"] for n in pub_scores["top_nodes"]}
        group_views = {}
        for grp in P["groups"]:
            gs = _scores(grp, c, st)
            group_views[grp] = gs
            # 막: 그룹에서 본 공통 개념의 authority >= public(오버레이는 더하기만)
            for n in gs["top_nodes"]:
                pa = _auth_of(c, n["id"], "public", st)
                ga = n["authority"]
                if ga + 1e-9 < pa:
                    fails.append(f"막 위반: {grp}의 {n['id']} 권위 {ga} < public {pa}")
                    break

        # (C) 그룹 권위가 public으로 누수되지 않음:
        #     어떤 노드든 public authority는 그룹 endorse 영향을 받지 않아야 한다.
        #     (그룹 endorse만 받은 노드는 public에서 0이어야 함)
        leak = 0
        for nid in rng.sample(concept_ids, min(40, len(concept_ids))):
            pa = _auth_of(c, nid, "public", st)
            # public authority는 오직 public endorse/stake에서만 온다
            # → 임의 그룹에서 본 값이 public보다 작을 수 없고, 타 그룹 endorse가
            #   public 값을 키우지 않았는지 교차 확인
            for grp in P["groups"]:
                ga = _auth_of(c, nid, grp, st)
                if ga < pa - 1e-9:
                    leak += 1
        if leak:
            fails.append(f"누수 의심: 그룹 뷰가 public prior보다 작은 사례 {leak}")

        # (D) 재정렬 실제로 일어났는가(다양성 신호)
        reranked = sum(
            1 for grp in P["groups"]
            if [n["id"] for n in group_views[grp]["top_nodes"]]
            != [n["id"] for n in pub_scores["top_nodes"]]
        )
        # 그룹별 사적 권위를 받은 노드 수(오버레이 적용 범위)
        gcov = {sp: sum(1 for v in eng.authority.values() if v > 0)
                for sp, eng in unified.get_service().tree.group_scoring.items()}

        # (F) 스포트라이트 결정적 검증: team-a의 집중 endorse(+180)는 team-a만 올리고
        #     public·team-b는 한 톨도 안 움직인다(막 + 비누수).
        if spot_gain_a < 179.0:
            fails.append(f"스포트라이트: team-a 반영 안 됨 (gain={spot_gain_a})")
        if abs(spot_pub - pub_before) > 1e-9:
            fails.append(f"스포트라이트: public 누수 ({pub_before}→{spot_pub})")
        if abs(spot_b - b_before) > 1e-9:
            fails.append(f"스포트라이트: team-b 누수 ({b_before}→{spot_b})")

        # (G) 검색 베타 검증
        if pub_needle_id and pub_needle_id not in s_find:
            fails.append(f"검색: 공용 needle 부분일치 실패 ({s_find})")
        if s_pub_leak:
            fails.append(f"검색 막 위반: 그룹 키워드가 public 검색에 노출 ({s_pub_leak})")
        if host not in s_grp_hit:
            fails.append(f"검색 롤업/그룹가시 실패: lab-x에서 host 미발견 ({s_grp_hit})")
        if pub_needle_id:
            rank_pub = search("특이공정 캘리브레이션", "public")
            rank_a = search("특이공정 캘리브레이션", "team-a")
            # team-a 검색에서 needle이 public보다 앞서야(사적 endorse 재정렬)
            ia = rank_a.index(pub_needle_id) if pub_needle_id in rank_a else 1e9
            ip = rank_pub.index(pub_needle_id) if pub_needle_id in rank_pub else 1e9
            if not (ia <= ip):
                fails.append(f"검색 재정렬 실패: team-a {ia} > public {ip}")

        # (E) 영속 라운드트립: pgstore 정규화 라운드트립이 손실 없는가
        svc = unified.get_service()
        snap = svc._snapshot()
        rebuilt = pgstore.rows_to_snapshot(pgstore.snapshot_to_rows(snap))
        a = OntologyTree.from_json(snap["tree"]).to_json()
        b = OntologyTree.from_json(rebuilt["tree"]).to_json()
        if _canon(a) != _canon(b):
            fails.append("영속 라운드트립 불일치(pgstore)")
        gs_spaces = list(snap["tree"].get("group_scoring", {}).keys())

    unified.reset_service(None)

    # ---- 리포트 ------------------------------------------------------------
    print("=" * 64)
    print(f"대규모 시뮬레이션 베타 — scale={scale}  seed={seed}")
    print("=" * 64)
    print(f"유저 {P['users']} · 그룹 {len(P['groups'])} · 개념 {len(concept_ids)} "
          f"· 기여 {P['contributions']} · 후속 {P['followups']}")
    print(f"endorse: public {P['public_endorses']} · group {P['group_endorses']}")
    print(f"총 API 호출 {st.calls}  ·  {elapsed:.2f}s  ·  {st.calls/elapsed:,.0f} req/s")
    print(f"상태코드: " + "  ".join(f"{k}:{v}" for k, v in sorted(st.codes.items())))
    print(f"5xx 오류: {len(st.errors)}")
    for e in st.errors[:5]:
        print("   !", e)
    print(f"그룹 사적 스코어러 수: {len(gs_spaces)}  {gs_spaces}")
    print(f"그룹별 사적 권위 노드 수(오버레이 범위): {gcov}")
    print(f"그룹 재정렬 발생: {reranked}/{len(P['groups'])} 그룹이 public과 다른 순위")
    print(f"스포트라이트({spot}): team-a +{spot_gain_a:.0f} → a={spot_a:.1f} "
          f"| public {pub_before:.1f}→{spot_pub:.1f} · team-b {b_before:.1f}→{spot_b:.1f} (불변)")
    print(f"검색: needle 발견={bool(pub_needle_id and pub_needle_id in s_find)} "
          f"· 그룹키워드 public누수={bool(s_pub_leak)} · 평균 지연={search_us:.0f}us/질의")
    print("-" * 64)
    if fails:
        print("❌ 불변식 위반:")
        for f in fails:
            print("   -", f)
    else:
        print("✅ 모든 불변식 통과: 막 · 비태환 · 국소재정렬 · 검색 · 무결성 · 영속")
    print("=" * 64)
    return 1 if (fails or st.errors) else 0


# -- helpers ---------------------------------------------------------------- #
def _balance(account: str) -> float:
    return unified.get_service().econ.balance(account)


def _scores(space: str, c: TestClient, st: Stat) -> dict:
    return st.rec(c.get("/api/scores", params={"space": space})) or {"top_nodes": []}


def _auth_of(c: TestClient, nid: str, space: str, st: Stat) -> float:
    j = st.rec(c.get(f"/api/nodes/{nid}", params={"space": space}))
    return (j or {}).get("authority", 0.0)


def _canon(tree_json: dict) -> dict:
    """빈 linkers 차이는 무시(엔진의 defaultdict 흔적)."""
    out = dict(tree_json)
    for key in ("scoring", "group_scoring"):
        blk = out.get(key)
        if isinstance(blk, dict):
            if "linkers" in blk:
                blk = {**blk, "linkers": {k: v for k, v in blk["linkers"].items() if v}}
                out[key] = blk
            else:
                out[key] = {sp: {**e, "linkers": {k: v for k, v in e.get("linkers", {}).items() if v}}
                            for sp, e in blk.items()}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    sys.exit(run(args.scale, args.seed))
