"""다양한 사용자 기반 시뮬레이션 — 발자국 경제·두루·안목의 창발 점검 (노트 17).

실제 API(TestClient)를 사용자 군상별 행동 패턴으로 두드리고, 그 결과를
랭킹/두루/안목/탐침 관점에서 검사한다. 목적:

1. 시빌 링의 표적이 *유기적으로 두루 밟힌* 노드를 못 이기는가 (두루 렌즈)
2. 안목(허브) 리더보드에 *일찍·꾸준히* 가려낸 큐레이터가 서는가
3. **오탐**: 진짜 소그룹(같이 일하는 팀)·취향 겹치는 큐레이터·유행 따라 같은
   2개를 밟은 유기 사용자들이 패거리로 접히지는 않는가 ← 정직한 측정
4. foresight(검증 이벤트) 수치가 정확한가

실행: PYTHONPATH=src python scripts/sim_users.py
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from nightwish import unified


def main() -> None:
    svc = unified.UnifiedService("/tmp/sim_users.json")
    unified.reset_service(svc)
    c = TestClient(unified.app)
    t0 = time.time()

    def ask(q, who):
        return c.post("/api/ask", json={"question": q, "author": who}).json()["node"]["id"]

    def walk(who, nid):
        c.post("/api/endorse", json={"account": who, "node_id": nid, "amount": 1})

    # ── P0. 인구: 저자3 · 큐레이터2 · 유기 사용자10 · 시빌 링4 · 팀3 · 정정자1
    creators = [f"c{i}" for i in range(1, 4)]
    curators = ["k1", "k2"]
    organics = [f"o{i}" for i in range(1, 11)]
    ring = [f"s{i}" for i in range(1, 5)]
    team = [f"t{i}" for i in range(1, 4)]
    everyone = creators + curators + organics + ring + team + ["fixer"]
    for u in everyone:
        c.post("/api/mint", json={"account": u, "amount": 100})

    # ── P1. 저자들이 서로 다른 주제 12개를 깐다 (어휘 겹침 최소화한 제목)
    topics = ["용접 변형 관리", "절삭 공구 수명", "도장 표면 결함", "금형 냉각 설계",
              "베어링 윤활 주기", "센서 캘리브레이션", "로봇 티칭 절차", "품질 샘플링 규칙",
              "재고 회전율 개선", "납기 지연 원인", "안전 점검 체크", "에너지 절감 방안"]
    nid = {}
    for i, tpc in enumerate(topics):
        nid[f"T{i+1}"] = ask(tpc, creators[i % 3])

    # ── P2. 큐레이터: 일찍·여러 곳을 가려냄. k1=T1..T6, k2=T4..T9 (취향 3개 겹침 — 오탐 후보)
    for t in ["T1", "T2", "T3", "T4", "T5", "T6"]:
        walk("k1", nid[t])
    for t in ["T4", "T5", "T6", "T7", "T8", "T9"]:
        walk("k2", nid[t])

    # ── P3. 유기 사용자: '좋은 노드' T1~T8을 뒤따라 밟음 (조합 다양, 일부는 같은 짝 — 오탐 후보)
    combos = [("T1", "T2"), ("T1", "T3"), ("T2", "T4"), ("T3", "T5"), ("T4", "T6"),
              ("T5", "T7"), ("T6", "T8"), ("T7", "T1"), ("T8", "T2"), ("T1", "T2")]  # o10=o1과 동일쌍
    for u, (a, b) in zip(organics, combos):
        walk(u, nid[a]); walk(u, nid[b])

    # ── P4. 시빌 링: 외진 노드 3개를 *같이* 밟아 서로 허브를 키운 뒤 표적을 펌핑
    target = ask("링이 미는 외딴 주장", "s1")
    aux1 = ask("링 전용 잡담 하나", "s1")
    aux2 = ask("링 전용 잡담 둘", "s2")
    for a in (aux1, aux2):
        for s in ring:
            walk(s, a)
    for s in ring:
        walk(s, target)

    # ── P5. 진짜 팀: 프로젝트 노드 1개 + 도메인 노드 1개를 *같이* 밟음(겹침 2개 — 오탐 경계),
    #         나머지는 각자 다른 인기 노드를 밟음(독립 활동)
    proj = ask("팀 프로젝트 정리", "t1")
    domain = nid["T10"]
    for t in team:
        walk(t, proj); walk(t, domain)
    walk("t1", nid["T1"]); walk("t2", nid["T2"]); walk("t3", nid["T3"])

    # ── P6. 정정자: 링 표적에 정정(fork) + 유기 사용자 둘이 정정을 지지
    c.post(f"/api/nodes/{target}/contribute",
           json={"kind": "fork", "author": "fixer", "body": "외딴 주장의 반례: 실측과 불일치"})
    # (정정 노드 id는 thread에서)
    th = c.get(f"/api/nodes/{target}").json()["thread"]
    fork_id = [x for x in th if x["kind"] == "fork"][0]["id"]
    walk("o1", fork_id); walk("o2", fork_id)

    # ════════ 보고 ════════
    t = svc.tree
    print(f"\n인구 {len(everyone)}명 · 노드 {len(t.nodes)}개 · 경과 {time.time()-t0:.1f}s")

    def row(label, node_id):
        raw_a = t.scoring.authority_of(node_id)
        lens_a = t.authority_in(node_id)
        raw_w, eff = t.effective_walkers(node_id)
        return (f"  {label:<14} 발자국 {raw_w:>2} → 두루 {eff:4.1f} | "
                f"권위(원시) {raw_a:5.1f} → (렌즈) {lens_a:5.1f}")

    print("\n[1] 표적 vs 유기 노드 — 두루 렌즈")
    print(row("링 표적", target))
    print(row("T1(유기 인기)", nid["T1"]))
    print(row("T4(유기 인기)", nid["T4"]))
    print(row("팀 프로젝트", proj))
    print(row("T10(팀 도메인)", nid["T10"]))

    print("\n[2] 랭킹 top8 (렌즈 적용 권위)")
    board = t.scoreboard("public")[:8]
    for n, a in board:
        raw_w, eff = t.effective_walkers(n.id)
        tag = "⚠️링" if n.id == target else ("팀" if n.id == proj else "")
        label = n.question.strip() or (n.answer or "").strip().replace("\n", " ")[:18]
        print(f"  {a:6.2f}  {label[:18]:<20} 👣{raw_w} 두루{eff:.1f} {tag}")

    print("\n[3] 안목(허브) top8 — 큐레이터가 위인가, 링이 위인가")
    hubs = sorted(t.scoring.hub.items(), key=lambda kv: -kv[1])[:8]
    for u, h in hubs:
        kind = ("큐레이터" if u in curators else "링" if u in ring else
                "팀" if u in team else "유기" if u in organics else "저자")
        print(f"  {h:6.2f}  {u:<5} ({kind})")

    print("\n[4] 무리 판정(오탐 점검) — 같은 무리로 접힌 사용자들")
    clusters = t._walker_clusters()
    from collections import defaultdict
    groups = defaultdict(list)
    for u, root in clusters.items():
        groups[root].append(u)
    for root, members in groups.items():
        if len(members) >= 2:
            kinds = {("링" if m in ring else "팀" if m in team else
                      "큐레이터" if m in curators else "유기") for m in members}
            print(f"  무리 {sorted(members)} ← {kinds}")

    print("\n[5] 안목 검증(foresight) — k1의 '먼저 밟고 따라온' 길")
    m = c.get("/api/me/stats?user=k1").json()
    for f in m["foresight"][:5]:
        print(f"  {f['title'][:16]:<18} {f['pos']}번째 → 그 후 +{f['after']}명")

    print("\n[6] 탐침 의심쌍 (관찰)")
    p = c.get("/api/integrity/probe?min_sim=0.5").json()
    for pair in p["pairs"][:8]:
        print(f"  {pair['a']}~{pair['b']} sim={pair['sim']} 공유 {pair['n_shared']}")

    unified.reset_service(None)


if __name__ == "__main__":
    main()
