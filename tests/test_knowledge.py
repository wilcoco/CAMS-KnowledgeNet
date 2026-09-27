"""Evidence integrity, isolated retrieval, persistence and failure behaviour."""
import copy
import json
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
                           "source_mode": ('none' if not sources else 'conversation'
                                           if all(s.get('selection')=='conversation' for s in sources)
                                           else 'user_selected'),
                           "background": kwargs.get("background", ""),
                           "focus": kwargs.get("focus"),
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
    n = ask(client, source_ids=[public['id']]).json()["node"]
    assert any(s['id'] == public['id'] for s in received)
    assert not any(s['id'] == private['id'] for s in received)
    assert "공개하면 안 되는" not in str(n["knowledge"])


def test_source_snapshot_does_not_change_with_later_edit(client):
    data = {"title": "독서 모임", "body": "참여자의 실제 경험", "author": "writer"}
    source = client.post('/api/nodes', json=data).json()
    n = ask(client, source_ids=[source['id']]).json()["node"]
    assert n['knowledge']['sources'][0]['excerpt'] == data['body']
    client.post('/api/nodes', json={**data, 'body': '수정된 경험'})
    assert client.get('/api/nodes/'+n['id']).json()['knowledge']['sources'][0]['excerpt'] == data['body']


def test_publishing_answer_does_not_publish_private_source_snapshots(client):
    private = client.post('/api/nodes', json={"title": "독서 모임 비밀 기록", "body": "비공개 자료의 내용",
                                             "author": "writer", "space": "secret"}).json()
    n = ask(client, space='secret', source_ids=[private['id']]).json()['node']
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
    assert k['sources'][0]['selection'] == 'conversation'


def test_search_results_are_not_implicitly_supplied_to_ai(client, monkeypatch):
    question = '카파시의 llm위키를 조직에서 사용하는 방법'
    source = client.post('/api/nodes', json={
        'title':'Odoo ERP를 사용하는 방법', 'body':'무료 ERP 운영 사례', 'author':'writer'}).json()
    # The broad search may list a candidate. That is not permission to send it.
    assert source['id'] in [n['id'] for n in client.get('/api/search',params={'q':question}).json()]
    received=[]
    def capture(q, sources, **kw):
        received.append(sources)
        return fake_generate(q,sources,**kw)
    monkeypatch.setattr(knowledge,'generate',capture)
    r=ask(client,question=question)
    assert r.status_code==200 and r.json()['node']['knowledge']['sources']==[]
    assert received==[[]]


def test_only_selected_sources_are_sent_with_explicit_provenance(client, monkeypatch):
    a=client.post('/api/nodes',json={'title':'독서 모임 A','body':'선택한 경험','author':'a'}).json()
    b=client.post('/api/nodes',json={'title':'독서 모임 B','body':'선택하지 않은 경험','author':'b'}).json()
    received=[]
    def capture(q,sources,**kw):
        received.extend(sources)
        return fake_generate(q,sources,**kw)
    monkeypatch.setattr(knowledge,'generate',capture)
    assert ask(client,source_ids=[a['id'],a['id']]).status_code==200
    assert [s['id'] for s in received]==[a['id']]
    assert received[0]['selection']=='user_selected'
    assert b['id'] not in str(received)


def test_private_selected_source_is_rejected_before_generation(client, monkeypatch):
    p=client.post('/api/nodes',json={'title':'비밀','body':'팀의 경험','author':'a','space':'secret'}).json()
    def fail(*a,**kw): pytest.fail('private document reached the provider')
    monkeypatch.setattr(knowledge,'generate',fail)
    assert ask(client,source_ids=[p['id']]).status_code==404
    assert ask(client,source_ids=['does-not-exist']).status_code==404
    assert ask(client,source_ids=['x']*6).status_code==422


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
        def stream(self, **kwargs):
            seen['answer_request'] = kwargs
            return self
        def get_final_message(self):
            return SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text',text=ANSWER)])
        def parse(self, **kwargs):
            seen.update(kwargs)
            raw = draft()
            if bad_graph:
                raw['relations'][0]['quote'] = '원문에 없는 AI의 바꿔 쓴 구절'
            raw.pop('answer')
            return SimpleNamespace(stop_reason='end_turn', parsed_output=knowledge.MapOnly.model_validate(raw))
    monkeypatch.setattr(anthropic,'Anthropic',FakeClient)
    answer, data = knowledge.generate(QUESTION, [], api_key='not-a-real-key')
    assert answer == ANSWER and data['status'] == 'ai_proposed'
    assert data['source_mode'] == 'none'
    assert seen['output_format'] is knowledge.MapOnly
    assert seen['answer_request']['thinking'] == {'type':'adaptive'}
    assert 'output_format' not in seen['answer_request']
    assert ANSWER in seen['messages'][0]['content']
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


def test_web_opt_in_and_background_reach_only_the_right_stage(client, monkeypatch):
    received=[]
    def capture(q, sources, **kwargs):
        received.append(kwargs)
        return fake_generate(q, sources, **kwargs)
    monkeypatch.setattr(knowledge,'generate',capture)
    n=ask(client, background='제조업 품질팀', web_search=True).json()['node']
    assert received[-1]['web_search'] and received[-1]['background']=='제조업 품질팀'
    assert ask(client, space='secret',web_search=True).status_code==200
    assert not received[-1]['web_search']
    client.post('/api/nodes/'+n['id']+'/contribute',json={
        'kind':'followup','body':'실행 순서는?', 'author':'walker','with_knowledge':True})
    assert received[-1]['background']=='제조업 품질팀'
    assert not received[-1]['web_search']


def test_research_uses_provider_citations_and_handles_pause_without_private_context():
    seen=[]
    class Block:
        def __init__(self, **data): self.data=data
        def model_dump(self): return self.data
    class Client:
        def __init__(self): self.messages=self
        def create(self, **kwargs):
            seen.append(copy.deepcopy(kwargs))
            if len(seen)==1:
                return SimpleNamespace(stop_reason='pause_turn',content=[Block(
                    type='web_search_tool_result',content=[{'type':'web_search_result','encrypted_content':'opaque'}])])
            return SimpleNamespace(stop_reason='end_turn',content=[
                Block(type='text',text='근거 없는 요약',citations=[]),
                Block(type='text',text='원문에서 확인한 내용',citations=[
                    {'type':'web_search_result_location','url':'https://example.org/original',
                     'title':'원저자 문서','cited_text':'확인한 원문'},
                    {'type':'web_search_result_location','url':'javascript:alert(1)','title':'bad'}])])
    result=knowledge.research_question(Client(),QUESTION)
    assert seen[0]['messages']==[{'role':'user','content':QUESTION}]
    assert seen[1]['messages'][1]['content'][0]['content'][0]['encrypted_content']=='opaque'
    assert result['status']=='searched' and len(result['sources'])==1
    assert '근거 없는 요약' not in result['summary']
    linked=knowledge._link_citations('설명 [W1] 그리고 [W9]',result['sources'])
    assert '[W1](<https://example.org/original>)' in linked and '[출처 확인 필요]' in linked


def test_research_error_does_not_claim_verification():
    class Client:
        def __init__(self): self.messages=self
        def create(self, **kwargs): raise TimeoutError()
    result=knowledge.research_question(Client(),QUESTION)
    assert result=={'status':'unavailable','summary':'','sources':[]}


def test_graph_failure_retains_complete_answer_and_private_context_never_enters_search(monkeypatch):
    import anthropic
    research_requests=[]
    answer_requests=[]
    def research(client,q):
        research_requests.append(q)
        return {'status':'unavailable','summary':'','sources':[]}
    monkeypatch.setattr(knowledge,'research_question',research)
    class Client:
        def __init__(self,**kwargs): self.messages=self
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def stream(self,**kwargs):
            answer_requests.append(json.loads(kwargs['messages'][0]['content']))
            return self
        def get_final_message(self):
            return SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text=ANSWER)])
        def parse(self,**kwargs): raise TimeoutError()
    monkeypatch.setattr(anthropic,'Anthropic',Client)
    answer,k=knowledge.generate(QUESTION,[{'id':'p','excerpt':'내부 기록'}],api_key='test',
                               background='팀의 목표',web_search=True)
    assert research_requests==[QUESTION]
    assert answer_requests[0]['sources'][0]['excerpt']=='내부 기록'
    assert answer_requests[0]['background']=='팀의 목표'
    assert answer==ANSWER and k['concepts']==[] and k['notice']
    assert k['research_status']=='unavailable'


def map_target(node, purpose='condition', kind='concept', target_id='club'):
    return {'kind':kind,'id':target_id,'purpose':purpose,'revision':node['knowledge_revision']}


def test_structured_human_addition_is_persisted_without_changing_the_ai_map(client):
    n=ask(client).json()['node']
    r=client.post('/api/nodes/'+n['id']+'/contribute',json={
        'author':'현장 사용자','kind':'comment','body':'야간 근무자에게는 온라인 참여가 필요했습니다.',
        'map_target':map_target(n)})
    assert r.status_code==200, r.text
    updated=r.json(); c=updated['thread'][-1];target=c['knowledge_target']
    assert target['label']=='독서 모임' and target['quote']==QUESTION
    assert target['purpose']=='condition' and target['node_id']==n['id']
    assert not c['has_knowledge'] and not c['frozen']
    assert updated['knowledge']==n['knowledge'] and updated['staked']==n['staked']
    snap=pgstore.rows_to_snapshot(pgstore.snapshot_to_rows(client.svc._snapshot()))
    tree=OntologyTree.from_json(snap['tree'])
    assert tree.nodes[c['id']].knowledge['contribution_target']==target
    fresh=client.get('/api/nodes/'+n['id']).json()
    assert fresh['thread'][-1]['knowledge_target']==target


def test_relation_followup_uses_exact_focus_and_only_visible_matching_human_additions(client, monkeypatch):
    n=ask(client).json()['node']
    route='/api/nodes/'+n['id']+'/contribute'
    for body,purpose,kind,tid,space in [
        ('우리 모임에서는 교대근무가 중요한 조건입니다.','condition','relation','0','public'),
        ('관계와 무관한 다른 개념의 경험','evidence','concept','people','public'),
        ('공개하면 안 되는 그룹의 경험','counterexample','relation','0','secret')]:
        assert client.post(route,json={'author':'참여자','kind':'comment','body':body,'space':space,
            'map_target':map_target(n,purpose,kind,tid)}).status_code==200
    captured=[]
    def generate(q,sources,**kw):
        captured.append((sources,kw))
        return fake_generate(q,sources,**kw)
    monkeypatch.setattr(knowledge,'generate',generate)
    r=client.post(route,json={'author':'질문자','kind':'followup','body':'실제 적용 방법은?',
        'map_target':map_target(n,'question','relation','0')})
    assert r.status_code==200,r.text
    sources,kw=captured[0]
    assert kw['focus']['label']=='독서 모임 → 관련된다 → 참여자'
    assert kw['focus']['quote']=='독서 모임은 참여자의 경험을 듣고'
    assert any('교대근무' in s['excerpt'] for s in sources)
    assert '다른 개념의 경험' not in str(sources) and '그룹의 경험' not in str(sources)
    question=r.json()['thread'][-1]
    assert question['knowledge_target']['purpose']=='question'
    assert not question['has_knowledge'] and question['replies'][0]['has_knowledge']
    ai=client.get('/api/nodes/'+question['replies'][0]['id']).json()
    assert ai['knowledge']['focus']==kw['focus']


def test_stale_or_forged_targets_fail_before_generation(client, monkeypatch):
    n=ask(client).json()['node']
    def fail(*a,**kw): pytest.fail('invalid target reached model')
    monkeypatch.setattr(knowledge,'generate',fail)
    route='/api/nodes/'+n['id']+'/contribute'
    for target,status in [({**map_target(n,'question'),'revision':'0'*64},409),
                          (map_target(n,'question',target_id='forged'),400),
                          (map_target(n,'question','relation','99'),400)]:
        assert client.post(route,json={'author':'q','kind':'followup','body':'왜?',
                                       'map_target':target}).status_code==status
    assert client.post(route,json={'author':'q','kind':'comment','body':'의견',
                                  'map_target':map_target(n,'question')}).status_code==400


def test_private_target_is_not_available_in_public_space(client):
    n=ask(client,space='secret').json()['node']
    r=client.post('/api/nodes/'+n['id']+'/contribute',json={
        'author':'x','kind':'comment','body':'의견','map_target':map_target(n)})
    assert r.status_code==404
