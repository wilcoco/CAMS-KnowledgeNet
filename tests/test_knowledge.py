"""Evidence integrity, isolated retrieval, persistence and failure behaviour."""
import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nightwish import knowledge, pgstore, unified
from nightwish.tree import OntologyTree


QUESTION = "독서 모임의 참여를 늘리려면?"
ANSWER = "독서 모임은 참여자의 경험을 듣고 운영 방식을 조정할 수 있습니다."


def draft(question=QUESTION):
    return {
        "question": {"intent": "모임 참여 개선", "conditions": [], "unknowns": ["참여자의 경험"]},
        "answer": ANSWER,
        "concepts": [
            {"id": "club", "label": "독서 모임", "kind": "concept", "origin": "question", "quote": question},
            {"id": "people", "label": "참여자", "kind": "actor", "origin": "answer", "quote": "참여자의 경험"},
        ],
        "relations": [{"source": "club", "target": "people", "type": "related_to",
                       "origin": "answer", "quote": "독서 모임은 참여자의 경험을 듣고", "source_id": ""}],
    }


def fake_generate(question, sources, **kwargs):
    result = knowledge.validate_map(draft(question), question, sources)
    return result.answer, {"version": 1, "status": "ai_proposed", "model": "test-map",
                           "question_text": question, **result.model_dump(exclude={"answer"}),
                           "sources": copy.deepcopy(sources)}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setattr(knowledge, "generate", fake_generate)
    svc = unified.UnifiedService(str(tmp_path / "app.json"))
    unified.reset_service(svc)
    with TestClient(unified.app) as c:
        c.svc = svc
        yield c
    unified.reset_service(None)


def ask(client, **kwargs):
    return client.post("/api/ask", json={"question": QUESTION, "author": "walker",
                                        "with_knowledge": True, **kwargs})


@pytest.mark.parametrize("mutation", [
    lambda x: x["concepts"].append(x["concepts"][0]),
    lambda x: x["concepts"][0].update(quote="없는 구절"),
    lambda x: x["relations"][0].update(target="missing"),
    lambda x: x["relations"][0].update(source_id="forged"),
    lambda x: x["relations"][0].update(origin="source", source_id="forged"),
    lambda x: x["relations"][0].update(quote="없는 근거"),
    lambda x: x["relations"][0].update(type="verified_fact"),
])
def test_invalid_graph_rejected(mutation):
    raw = draft()
    mutation(raw)
    with pytest.raises(ValueError):
        knowledge.validate_map(raw, QUESTION, [])


def test_source_quote_must_be_from_allowed_snapshot():
    raw = draft()
    raw["relations"][0].update(origin="source", source_id="s", quote="직접 관찰")
    sources = [{"id": "s", "excerpt": "직접 관찰한 내용입니다."}]
    assert knowledge.validate_map(raw, QUESTION, sources).relations[0].source_id == "s"
    with pytest.raises(ValueError):
        knowledge.validate_map(raw, QUESTION, [{"id": "s", "excerpt": "다른 내용"}])


def test_joint_generation_persists_without_endorsement(client):
    r = ask(client)
    assert r.status_code == 200, r.text
    n = r.json()["node"]
    assert n["knowledge"]["status"] == "ai_proposed"
    assert n["frozen"] and n["model"] == "test-map"
    assert not n["adopted"] and n["staked"] == 0
    assert not client.svc.tree.nodes[n["id"]].link_rels
    # Both production SQL mapping and legacy JSON reload preserve the map.
    snapshot = client.svc._snapshot()
    restored = pgstore.rows_to_snapshot(pgstore.snapshot_to_rows(snapshot))
    tree = OntologyTree.from_json(restored["tree"])
    assert tree.nodes[n["id"]].knowledge == n["knowledge"]
    unified.reset_service(unified.UnifiedService(client.svc.db_path))
    fetched = client.get('/api/nodes/'+n["id"]).json()
    assert fetched["knowledge"] == n["knowledge"]


def test_private_source_not_sent_to_public_generation(client, monkeypatch):
    private = client.post('/api/nodes', json={"title": "독서 모임 비밀", "body": "공개하면 안 되는 경험",
                                             "author": "writer", "space": "secret"}).json()
    public = client.post('/api/nodes', json={"title": "독서 모임", "body": "공개된 모임 경험", "author": "writer"}).json()
    received = []
    def capture(q, sources, **kw):
        received.extend(sources)
        return fake_generate(q, sources, **kw)
    monkeypatch.setattr(knowledge, "generate", capture)
    n = ask(client).json()["node"]
    assert any(s['id'] == public['id'] for s in received)
    assert not any(s['id'] == private['id'] for s in received)
    assert "공개하면 안 되는" not in str(n["knowledge"])


def test_source_snapshot_does_not_change_with_later_edit(client):
    data = {"title": "독서 모임", "body": "참여자의 실제 경험", "author": "writer"}
    client.post('/api/nodes', json=data)
    n = ask(client).json()["node"]
    assert n['knowledge']['sources'][0]['excerpt'] == data['body']
    client.post('/api/nodes', json={**data, 'body': '수정된 경험'})
    assert client.get('/api/nodes/'+n['id']).json()['knowledge']['sources'][0]['excerpt'] == data['body']


def test_publishing_answer_does_not_publish_private_source_snapshots(client):
    private = client.post('/api/nodes', json={"title": "독서 모임 비밀 기록", "body": "비공개 자료의 내용",
                                             "author": "writer", "space": "secret"}).json()
    n = ask(client, space='secret').json()['node']
    assert any(s['id'] == private['id'] for s in n['knowledge']['sources'])
    with client.svc.writing():
        client.svc.tree.nodes[n['id']].knowledge['relations'][0].update(
            origin='source', source_id=private['id'], quote='비공개 자료의 내용')
    published = client.post('/api/nodes/'+n['id']+'/publish', json={'author':'walker','space':'secret'})
    assert published.status_code == 200
    k = client.get('/api/nodes/'+n['id']).json()['knowledge']
    assert not k['sources'] and not k['relations']
    assert '비공개 자료의 내용' not in str(k)


@pytest.mark.parametrize('exc,status', [(knowledge.Unavailable('AI 연결 없음'),503),(ValueError('bad graph'),502)])
def test_failure_has_no_fake_answer_and_refunds_quota(client, monkeypatch, exc, status):
    monkeypatch.setenv('NIGHTWISH_ASK_QUOTA','1')
    count = len(client.svc.tree.nodes)
    def fail(*a, **kw): raise exc
    monkeypatch.setattr(knowledge,'generate',fail)
    assert ask(client).status_code == status
    assert len(client.svc.tree.nodes) == count
    assert unified._quota_left(client.svc,'walker') == 1


def test_followup_generates_a_map_on_its_own_answer(client):
    n = ask(client).json()['node']
    r = client.post('/api/nodes/'+n['id']+'/contribute', json={
        'kind':'followup','body':'독서 모임의 조건은?', 'author':'walker','with_knowledge':True})
    assert r.status_code == 200, r.text
    question = r.json()['thread'][-1]
    answer = question['replies'][0]
    assert answer['has_knowledge']
    k = client.get('/api/nodes/'+answer['id']).json()['knowledge']
    assert k['question_text'] == '독서 모임의 조건은?'
    assert k['sources'][0]['id'] == n['id']


def test_inaccessible_followup_is_rejected_before_provider(client, monkeypatch):
    n = ask(client, space='secret').json()['node']
    def must_not_run(*a, **kw): pytest.fail('private context sent to model')
    monkeypatch.setattr(knowledge, 'generate', must_not_run)
    r = client.post('/api/nodes/'+n['id']+'/contribute', json={
        'kind':'followup','body':'秘密?', 'author':'walker','with_knowledge':True})
    assert r.status_code == 404


@pytest.mark.parametrize('bad_graph', [False, True])
def test_structured_provider_receives_question_sources_and_schema(monkeypatch, bad_graph):
    import anthropic
    seen = {}
    class FakeClient:
        def __init__(self, **kwargs): self.messages = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            seen.update(kwargs)
            raw = draft()
            if bad_graph:
                raw['relations'][0]['quote'] = '원문에 없는 AI의 바꿔 쓴 구절'
            return SimpleNamespace(stop_reason='end_turn', parsed_output=knowledge.AnswerMap.model_validate(raw))
    monkeypatch.setattr(anthropic,'Anthropic',FakeClient)
    answer, data = knowledge.generate(QUESTION, [], api_key='not-a-real-key')
    assert answer == ANSWER and data['status'] == 'ai_proposed'
    assert seen['output_format'] is knowledge.AnswerMap
    assert QUESTION in seen['messages'][0]['content']
    assert 'not-a-real-key' not in str(data)
    if bad_graph:
        assert data['relations'] == [] and data['omitted_count'] == 1
        assert data['notice'] and data['concepts']


def test_bad_concepts_and_sources_are_pruned_without_invented_edges():
    raw = draft()
    raw['concepts'][0]['quote'] = '질문을 바꿔 쓴 구절'
    raw['relations'].append({**raw['relations'][0], 'origin':'source', 'source_id':'forged'})
    data = knowledge.grounded_map(knowledge.AnswerMap.model_validate(raw), QUESTION, [])
    assert [c['id'] for c in data['concepts']] == ['people']
    assert data['relations'] == [] and data['omitted_count'] == 3


def test_answer_survives_when_no_graph_evidence_can_be_verified(client, monkeypatch):
    def partial(q, sources, **kw):
        raw = draft(q)
        for c in raw['concepts']: c['quote'] = '잘못된 구절'
        result = knowledge.AnswerMap.model_validate(raw)
        k = {**fake_generate(q, sources)[1], **knowledge.grounded_map(result,q,sources)}
        return result.answer, k
    monkeypatch.setattr(knowledge, 'generate', partial)
    r = ask(client)
    assert r.status_code == 200
    assert r.json()['node']['answer'] == ANSWER
    k = r.json()['node']['knowledge']
    assert k['concepts'] == [] and k['relations'] == [] and k['notice']
