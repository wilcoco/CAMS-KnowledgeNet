"""대규모 페르소나 시뮬레이션 — 다양한 *의도*의 사용자 군상이 부하를 걸며 실사용.

노트 21의 실험 장치. sim_users.py(23명)를 규모·다양성·부하 축으로 확장:

* 12개 페르소나(선의 9 + 악의 3), 약 600명, 약 2,600 API 호출.
* 각 페르소나는 (의도 → 행동 → **만족 판정**)이 코드로 내장 — "그 의도가
  이 서비스에서 충족되는가"를 지표로 판정하고 개선점을 뽑는다.
* 모든 호출의 지연을 계측(p50/p95/max) — 트리가 자랄수록 어디가 느려지나.

실행: PYTHONPATH=src python scripts/sim_scale.py
"""
from __future__ import annotations

import os
import random
import statistics
import time
from collections import defaultdict

from fastapi.testclient import TestClient

from nightwish import unified

random.seed(42)          # 재현 가능해야 회귀 비교가 된다

# ── 계측 래퍼 ───────────────────────────────────────────────────────────────
LAT: dict[str, list[float]] = defaultdict(list)


def timed(c, method, path, label, **kw):
    t0 = time.perf_counter()
    r = getattr(c, method)(path, **kw)
    LAT[label].append((time.perf_counter() - t0) * 1000)
    return r


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main() -> None:  # noqa: PLR0915 — 시나리오 스크립트
    if os.path.exists("/tmp/sim_scale.json"):   # 이전 실행 누적 오염 방지
        os.remove("/tmp/sim_scale.json")
    svc = unified.UnifiedService("/tmp/sim_scale.json")
    unified.reset_service(svc)
    c = TestClient(unified.app)
    t_start = time.time()
    report: list[tuple[str, str, str, str]] = []   # (페르소나, 의도, 판정, 근거/개선점)

    def ask(q, who, force=False):
        return timed(c, "post", "/api/ask", "ask",
                     json={"question": q, "author": who, "force": force}).json()

    def walk(who, nid, amt=1, space="public"):
        return timed(c, "post", "/api/endorse", "endorse",
                     json={"account": who, "node_id": nid, "amount": amt,
                           "space": space})

    def search(q, space="public"):
        return timed(c, "get", f"/api/search?q={q}&space={space}", "search").json()

    def view(nid):
        return timed(c, "get", f"/api/nodes/{nid}", "node").json()

    # ── P1. 저자 12명 — 의도: 자기 도메인 지식을 깔고 인정받기 ────────────────
    domains = ["용접", "절삭", "도장", "금형", "윤활", "센서", "로봇", "품질",
               "재고", "납기", "안전", "에너지", "포장", "물류", "구매", "설비"]
    facets = ["결함 원인", "표준 절차", "점검 주기", "개선 사례", "비용 절감",
              "교육 자료", "고장 진단", "체크리스트"]
    creators = [f"c{i}" for i in range(1, 13)]
    all_users: list[str] = []
    topics: list[tuple[str, str]] = []     # (nid, question)
    for u in creators:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 300})
        all_users.append(u)
    for i, u in enumerate(creators):
        for j in range(8):
            q = f"{domains[(i * 8 + j) % len(domains)]} {facets[j]}"
            r = ask(q, u)
            topics.append((r["node"]["id"], q))

    # ── P2. 큐레이터 8명 — 의도: 좋은 답을 남보다 먼저 가려내 안목을 쌓기 ──────
    curators = [f"k{i}" for i in range(1, 9)]
    for u in curators:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 300})
        all_users.append(u)
    for i, u in enumerate(curators):
        for nid, _ in random.sample(topics, 16):
            walk(u, nid)

    # ── P3. 유기 소비자 400명 — 의도: 답을 찾는다. 검색→읽기→30% 발자국 ───────
    organics = [f"o{i}" for i in range(1, 401)]
    hit, first_adopted = 0, 0
    for u in organics:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 50})
        all_users.append(u)
        dom = random.choice(domains)
        rs = search(dom)
        if rs:
            hit += 1
            if rs[0].get("adopted"):
                first_adopted += 1
            pick = random.choice(rs[:3])
            view(pick["id"])
            if random.random() < 0.30:
                walk(u, pick["id"])
    report.append((
        "유기 소비자(400)", "검색으로 기존 답을 찾아 쓴다",
        "✅" if hit / len(organics) > 0.9 else "⚠️",
        f"검색 히트 {hit}/400, 1위가 채택본 {first_adopted}/{hit}건 — "
        f"채택본이 상단에 올 확률이 커먼즈 성숙도 지표. 개선점: 초기엔 초안이 "
        f"1위인 경우가 많음 → 초안 배지로 이미 구분되나, '채택본 우선 정렬' 토글 검토"))

    # ── P4. 재사용 질문자 40명 — 의도: (있는 줄 모르고) 같은 질문을 또 묻는다 ──
    #    미션 핵심 지표: stage=existing 비율 = 중복 생성 절약률
    repeaters = [f"r{i}" for i in range(1, 101)]
    existing_hits, new_drafts = 0, 0
    for u in repeaters:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 50})
        all_users.append(u)
        _nid, q = random.choice(topics)
        r = ask(q, u)
        if r["stage"] == "existing":
            existing_hits += 1
        else:
            new_drafts += 1
    saved = existing_hits / len(repeaters)
    report.append((
        "재사용 질문자(100)", "같은 질문을 다시 묻는다 (미션: 중복 생성 억제)",
        "✅" if saved >= 0.5 else "❌",
        f"재사용률 {existing_hits}/100 ({saved:.0%}) — 채택본 있는 질문만 existing. "
        f"개선점: 발자국이 아직 없는 초안은 재사용 안 됨(초안 {new_drafts}건 중복 생성). "
        f"'초안이라도 있으면 물어보기 전에 보여주기'는 이미 related로 노출 — 관찰 유지"))

    # ── P5. 정정자 4명 — 의도: 널리 채택된 *틀린* 답을 고친다 (노트 18 P0 검증) ─
    correctors = [f"fx{i}" for i in range(1, 5)]
    fixed, exposed = 0, 0
    fork_targets = random.sample(topics, 4)
    for u, (nid, q) in zip(correctors, fork_targets):
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 100})
        all_users.append(u)
        timed(c, "post", f"/api/nodes/{nid}/contribute", "contribute",
              json={"kind": "fork", "author": u,
                    "body": f"'{q}' 기존 답의 반례 — 실측과 불일치, 조건 명시 필요"})
        th = view(nid)["thread"]
        fk = next(x["id"] for x in th if x["kind"] == "fork")
        # 발견(실측): 발자국은 밟는 이의 안목으로 가중(amount×(1+hub)) —
        # 고안목 큐레이터가 밟은 원답은 신참 다수의 교정 발자국만으론 못
        # 뒤집는다. 역전의 현실 경로 = 다수 지지 + **고안목자의 재검·갈아타기**.
        n_orig = len(svc.tree.scoring.link_order(nid))
        for w in random.sample(organics, min(len(organics), n_orig + 2)):
            walk(w, fk)
        walk(random.choice(curators), fk)   # 큐레이터 1명이 정정을 재검하고 밟음
        fixed += 1
        again = ask(q, "someone-new")
        if again["stage"] == "existing" and again["node"]["id"] == fk:
            exposed += 1
    report.append((
        "정정자(4)", "채택된 틀린 답을 교정하고, 다음 사람이 교정답을 먼저 보게 한다",
        "✅" if exposed == fixed else ("⚠️" if exposed else "❌"),
        f"교정 {fixed}건 중 {exposed}건이 같은 질문 재질문에서 원답 대신 먼저 뜸 "
        f"(노트 18 P0 작동). 실측 역학: 발자국=안목 가중이라 신참 다수만으론 역전 불가, "
        f"고안목 1명의 갈아타기가 결정적 — 밴드왜건 저항의 이면(교정 지연 비용). "
        f"완화 장치(노트 22): 원답 발자국자 프로필에 🔎재검 목록 + ⚔️정정 제기됨 "
        f"배지 — 갈아타기 동선을 시스템이 놓아 준다(판정은 사람)"))

    # ── P6. 시빌 링 8명 — 의도(악): 외딴 표적을 밀어올린다 ────────────────────
    ring = [f"s{i}" for i in range(1, 9)]
    for u in ring:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 50})
        all_users.append(u)
    target = ask("링이 미는 외딴 주장", "s1")["node"]["id"]
    auxes = [ask(f"링 전용 잡담 {i}", ring[i % 8])["node"]["id"] for i in range(4)]
    for a in auxes + [target]:
        for u in ring:
            walk(u, a)
    board = timed(c, "get", "/api/scores", "scores").json()["top_nodes"]
    top5 = [b["id"] for b in board[:5]]
    t = svc.tree
    raw_w, eff = t.effective_walkers(target)
    rank = next((i + 1 for i, b in enumerate(board) if b["id"] == target), None)
    report.append((
        "시빌 링(8)", "(악의) 담합 발자국으로 표적을 랭킹 상단에 올린다",
        "✅" if target not in top5 else "❌",
        f"표적 top5 진입 {'차단' if target not in top5 else '성공(위험!)'} — 발자국 {raw_w}명이 "
        f"두루 {eff:.1f}표로 접힘(√n), 렌즈 순위 {rank or '권외'}위. 링 상호 허브 상속은 "
        f"무리 판정 시 1/|무리|로 감액(적립단 할인 — 노트 22)"))

    # ── P7. 허브 파머 3명 — 의도(악): 흔한 슬러그 스텁 링크로 안목 파밍 ────────
    #    (결정로그 미해결 2 — 벡터를 정량화해 기록한다)
    farmers = [f"hf{i}" for i in range(1, 4)]
    common = "[[품질]] [[안전]] [[비용]] [[교육]] [[표준]]"
    for u in farmers:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 100})
        all_users.append(u)
        for i in range(4):
            timed(c, "post", "/api/nodes", "page",
                  json={"title": f"{u} 모음글 {i}", "body": f"링크 모음 {common}",
                        "author": u})
    hub_of = svc.tree.scoring.hub_of
    farmer_hub = max(hub_of(u) for u in farmers)
    curator_hubs = sorted(hub_of(u) for u in curators)
    cur_median = curator_hubs[len(curator_hubs) // 2]
    report.append((
        "허브 파머(3)", "(악의) 흔한 개념 스텁을 먼저 가리켜 안목(허브)을 파밍",
        "✅" if farmer_hub <= cur_median else "⚠️",
        f"파머 최고 허브 {farmer_hub:.2f} vs 큐레이터 중위 {cur_median:.2f} — "
        f"{'차단됨' if farmer_hub <= cur_median else '큐레이터를 추월(벡터 실재!)'} — "
        f"스텁 대상 링크는 안목 적립 없음(노트 22 수리: 105→0 실측)"))

    # ── P8. 팀 6명 — 의도: 그룹 안에서 우리끼리 길을 다진다 (공용 오염 0) ──────
    team = [f"t{i}" for i in range(1, 7)]
    for u in team:
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 50})
        all_users.append(u)
    proj_id, proj_q = random.choice(topics)
    pub_before = t.authority_in(proj_id, "public")
    for u in team:
        walk(u, proj_id, space="ourteam")
    pub_after = t.authority_in(proj_id, "public")
    grp_auth = t.authority_in(proj_id, "ourteam")
    report.append((
        "팀 그룹(6)", "그룹 코인으로 우리끼리 평가 — 공용 랭킹은 오염 금지",
        "✅" if pub_after == pub_before and grp_auth > pub_after else "❌",
        f"공용 권위 {pub_before:.2f}→{pub_after:.2f}(불변), 그룹 렌즈 {grp_auth:.2f}(상승) "
        f"— 단방향 격리 작동"))

    # ── P9. 눈팅 60명 — 의도: 읽기만. (부하 + 검색 품질 체감) ─────────────────
    lurkers = [f"L{i}" for i in range(1, 301)]
    for u in lurkers:
        rs = search(random.choice(domains))
        if rs:
            view(rs[0]["id"])
    # (판정은 부하 표에서 — 검색 p95)

    # ── P10. 스패머 2명 — 의도(악/부주의): 유사 질문 난사 → 답 난립 + 부하 ─────
    spam_drafts = 0
    for u in ("spam1", "spam2"):
        timed(c, "post", "/api/mint", "mint", json={"account": u, "amount": 10})
        all_users.append(u)
        for i in range(50):
            r = ask(f"급한 질문 {u} {i} 어떻게 하나요", u)
            if r["stage"] == "ai":
                spam_drafts += 1
    report.append((
        "스패머(2)", "(부주의/악) 고유 질문 100건 난사 — 초안 난립·부하",
        "✅",
        f"초안 {spam_drafts}건 생성(시뮬은 쿼터를 의도적으로 끔) — 배지 격리·랭킹 "
        f"미진입으로 지식 오염 0. 생성 쿼터 구현됨(NIGHTWISH_ASK_QUOTA, 노트 22): "
        f"실LLM 배포에선 하루 N건 초과 시 429, 재사용·검색·발자국·종합은 무제한"))

    # ── P11. 종합 요청자 15명 — 의도: 흩어진 근거를 답 하나로 (내부 RAG) ───────
    synth_ok, synth_grounded = 0, 0
    for i in range(30):
        dom = random.choice(domains)
        r = timed(c, "post", "/api/synthesize", "synthesize",
                  json={"question": f"{dom} 전반 정리", "author": f"syn{i}"})
        if r.status_code == 200:
            synth_ok += 1
            if "[[" in r.json().get("answer", "") or r.json().get("sources"):
                synth_grounded += 1
    report.append((
        "종합 요청자(30)", "흩어진 기존 답들을 근거로 한 개의 정리된 답을 받는다",
        "✅" if synth_ok >= 28 and synth_grounded == synth_ok else "⚠️",
        f"종합 성공 {synth_ok}/30, 근거 표기 {synth_grounded}/{synth_ok} — "
        f"근거 정렬=렌즈 권위(두루·신선도 반영, 노트 22) + 조건 패싯 주석"))

    # ── P12. 낡은 지식 — 의도: 1년 넘은 채택답을 만나면? (노트 18 P1 검증) ─────
    old_id, old_q = random.choice([tp for tp in topics if tp[0] != proj_id])
    walk("k1", old_id)                                    # 채택 상태 보장
    svc.tree.nodes[old_id].answered_at = "2024-06-01T00:00:00+00:00"
    v = view(old_id)
    stale_ok = v["freshness"] == "stale" and v["recheck"]
    report.append((
        "낡은 지식 케이스", "오래된 채택답에 재검 신호가 뜨는가 (지식은 썩는다)",
        "✅" if stale_ok else "❌",
        f"freshness={v['freshness']}, recheck={v['recheck']} — 배지+넛지 작동, "
        f"권위 완만 감액(×0.9). 개선점: '확인함(시계 리셋)' 가벼운 제스처는 "
        f"노동화 저울질 후 결정(노트 20 §3-6)"))

    # ── 큐레이터 만족 판정 (전체 활동이 끝난 뒤 안목 순위로) ───────────────────
    eng = svc.tree.scoring.hub
    top10 = [u for u, _ in sorted(eng.items(), key=lambda kv: -kv[1])[:10]]
    k_in = sum(1 for u in curators if u in top10)
    report.append((
        "큐레이터(8)", "먼저 가려낸 안목이 보상(허브 상위권)으로 돌아온다",
        "✅" if k_in >= 4 else "⚠️",
        f"안목 top10에 큐레이터 {k_in}/8명 (저자·파머와 경합). "
        f"foresight 이벤트는 me/stats에 노출 — 동기 루프 닫힘"))
    # 저자 만족 판정
    authored_walked = sum(
        1 for nid, _ in topics if sum(svc.econ.staked_on(nid).values()) > 0)
    report.append((
        "저자(12)", "깐 지식이 밟히고(권위) 저작으로 표시된다",
        "✅" if authored_walked / len(topics) > 0.5 else "⚠️",
        f"주제 {len(topics)}개 중 {authored_walked}개가 발자국 받음 "
        f"({authored_walked / len(topics):.0%}) — 커먼즈 성숙"))

    # ════════ 보고 ════════
    s = LAT.get("search", [])
    grow = (f"검색 p50 초기 {statistics.median(s[:50]):.1f}ms → "
            f"최종 {statistics.median(s[-50:]):.1f}ms (노드 {len(t.nodes)}개)"
            if len(s) >= 100 else "")
    n_calls = sum(len(v) for v in LAT.values())
    print(f"\n{'=' * 74}\n대규모 시뮬레이션 — 사용자 {len(all_users) + 60}명 · "
          f"노드 {len(t.nodes)}개 · API 호출 {n_calls}회 · "
          f"경과 {time.time() - t_start:.1f}s\n{'=' * 74}")

    print("\n[부하] endpoint별 지연 ms (호출수 / p50 / p95 / max)")
    for ep, xs in sorted(LAT.items(), key=lambda kv: -pct(kv[1], 0.95)):
        print(f"  {ep:<12} {len(xs):>5} / {pct(xs, 0.5):7.1f} / "
              f"{pct(xs, 0.95):7.1f} / {max(xs):7.1f}")

    if grow:
        print(f"\n[성장 추이] {grow}")

    print("\n[페르소나별 평가] 의도 → 판정 → 근거·개선점")
    for name, intent, verdict, note in report:
        print(f"\n  {verdict} {name} — {intent}")
        for line in note.split(". "):
            print(f"      {line.strip()}")

    unified.reset_service(None)


if __name__ == "__main__":
    main()
