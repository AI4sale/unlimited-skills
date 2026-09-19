from collections import Counter
import copy
import json
import pytest
from tests.test_fleet_reconciler import FakeAdapter, VALID_DESIRED, sign_desired, reconciler
from unlimited_skills.fleet import RuntimeInventory


class IndependentFake(FakeAdapter):
    def __init__(self):
        super().__init__()
        self.fail = 'pack_250'
        self.calls = Counter()
        self.active = {}
        self.generation = 'generation_before'

    def discover(self):
        return RuntimeInventory(self.generation,dict(self.active),'sha256:'+'d'*64)

    def install_revision(self,item):
        self.calls[item['pack_id']] += 1
        if item['pack_id'] == self.fail: raise OSError('temporary verification source unavailable')
        return super().install_revision(item)

    def activate_independent(self,item):
        self.active[item['pack_id']] = item['release_id']

    def attest_independent(self,item):
        self.generation='generation_fixture_02'
        return self.attest_runtime(item,activation_nonce=item['activation_nonce'])


def large_desired():
    desired=copy.deepcopy(VALID_DESIRED)
    first=desired['items'][0]
    desired['items']=[{**first,'attempt_id':f'attempt_{i}','pack_id':f'pack_{i}',
        'release_id':f'release_{i}','activation_nonce':f'nonce_{i}'} for i in range(500)]
    desired['required_extensions']=['paged-inventory-v1','independent-items-v1']
    return sign_desired(desired)


def test_500_packages_one_failure_499_active_restart_retries_only_one(tmp_path):
    adapter=IndependentFake()
    desired=large_desired()
    first=reconciler(tmp_path,adapter).reconcile(desired)
    assert len(adapter.active)==499
    assert sum(r['event_type']=='FAILED_RETRYABLE' for r in first.receipts)==1
    assert sum(r['event_type']=='RUNTIME_ATTESTED' for r in first.receipts)==499
    # Recreate the controller to prove progress comes from durable state.
    adapter.fail=''
    before=adapter.calls.copy()
    second=reconciler(tmp_path,adapter).reconcile(desired)
    assert len(adapter.active)==500
    assert adapter.calls-before==Counter({'pack_250':1})
    assert len(second.receipts)==6


def test_real_adapter_preserves_peer_and_previous_version_on_collision(tmp_path):
    from tests.test_fleet_codex_adapter import PackClient,archive,adapter as make_adapter,item
    client=PackClient({'pack_a':('1',archive('alpha')),'pack_b':('1',archive('beta'))})
    adapter=make_adapter(tmp_path,client)
    a=item(client,'pack_a','nonce_a');b=item(client,'pack_b','nonce_b')
    for current in (a,b):
        adapter.install_revision(current)
        adapter.activate_independent(current)
    state=json.loads((adapter.state_root/'active.json').read_text())
    assert len(state['active_packs'])==2
    client.packs['pack_b']=('2',archive('alpha'))
    bad=item(client,'pack_b','nonce_b2')
    adapter.install_revision(bad)
    with pytest.raises(Exception,match='managed_skill_collision'):
        adapter.activate_independent(bad)
    assert json.loads((adapter.state_root/'active.json').read_text())==state
    inventory=adapter.discover()
    assert inventory.active_revisions=={'pack_a':a['release_id'],'pack_b':b['release_id']}


def test_unreadable_selected_package_does_not_block_peer_or_new_activation(tmp_path, monkeypatch):
    from tests.test_fleet_codex_adapter import PackClient, archive, adapter as make_adapter, item
    from unlimited_skills.fleet import managed_runtime
    client=PackClient({key:('1',archive(name)) for key,name in [('a','alpha'),('b','beta'),('c','gamma')]})
    adapter=make_adapter(tmp_path,client)
    for key in ('a','b'):
        current=item(client,key,'nonce_'+key)
        adapter.install_revision(current);adapter.activate_independent(current)
    state=json.loads((adapter.state_root/'active.json').read_text())
    damaged=next(p['skill_directory'] for p in state['active_packs'] if p['pack_id']=='a')
    real=managed_runtime._tree_digest
    def unreadable(path):
        if damaged in path.parts:raise PermissionError('unreadable package')
        return real(path)
    monkeypatch.setattr(managed_runtime,'_tree_digest',unreadable)
    assert set(adapter.discover().active_revisions)=={'b'}
    current=item(client,'c','nonce_c')
    adapter.install_revision(current);adapter.activate_independent(current)
    assert set(adapter.discover().active_revisions)=={'b','c'}


def test_attestation_io_failure_continues_with_other_packages(tmp_path):
    adapter=IndependentFake();adapter.fail=''
    original=adapter.attest_independent
    def attest(item):
        if item['pack_id']=='pack_0':raise OSError('temporary read error')
        return original(item)
    adapter.attest_independent=attest
    desired=large_desired();desired['items']=desired['items'][:3]
    desired=sign_desired(desired)
    result=reconciler(tmp_path,adapter).reconcile(desired)
    assert len(adapter.active)==3
    assert sum(r['event_type']=='FAILED_RETRYABLE' for r in result.receipts)==1
    assert sum(r['event_type']=='RUNTIME_ATTESTED' for r in result.receipts)==2
