import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pipeline', ROOT / 'bin/pipeline.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SPEC = '# Spec\n| ID | Acceptance |\n|---|---|\n| A1 | Add two integers |\n'
DESIGN = '# Design\nA1: Python add function and unittest.\n'

class Fake:
    def __init__(self, reviews=None):
        self.calls = []
        self.reviews = list(reviews or [])
    def __call__(self, stage, prompt, **kw):
        self.calls.append(stage)
        if stage in ('spec', 'spec-revise'):
            return {'content': SPEC}
        if stage in ('design', 'design-fix', 'design-revise'):
            return {'content': DESIGN + '\n## 하위 프로젝트 분해\n| Project | IDs | Dependencies | idea |\n|---|---|---|---|\n| calc | A1 | none | Build calculator |\n'}
        if stage == 'review':
            return self.reviews.pop(0) if self.reviews else {'findings': []}
        if stage == 'review-delta':
            return self.reviews.pop(0) if self.reviews else {'resolved':['L-001'], 'unresolved':[], 'new':[]}
        if stage == 'plan':
            return {'content': '# Tasks\n- A1 implement add and test\n'}
        if stage == 'build':
            return {'summary': 'fixture'}
        raise AssertionError(stage)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.fake=Fake(); self.p=m.Pipeline(self.root, invoke=self.fake)
    def tearDown(self): self.tmp.cleanup()
    def start(self, **kw): self.p.start('Add [a|b] and $(literal) <x>', skills='lite', **kw)
    def test_human_waits_and_reject_stays(self):
        self.start(); self.assertEqual(self.p.state['phase'],'spec_pending_approval')
        self.assertEqual(self.fake.calls,['spec'])
        self.p.reject('please clarify'); self.assertEqual(self.p.state['phase'],'spec_pending_approval')
        self.p.approve(); self.assertEqual(self.p.state['phase'],'design_pending_approval')
        self.assertNotIn('build',self.fake.calls)
    def test_foreign_state_is_rejected_without_overwrite(self):
        (self.root/'.mvp').mkdir()
        statefile=self.root/'.mvp/state.json'; statefile.write_text('{"phase":"spec_pending_approval"}')
        before=statefile.read_bytes()
        with self.assertRaises(m.PipelineError): m.Pipeline(self.root)
        self.assertEqual(statefile.read_bytes(),before)

    def test_existing_run_not_overwritten(self):
        self.start(); before=(self.root/'.mvp/state.json').read_bytes()
        with self.assertRaises(m.PipelineError): self.start()
        self.assertEqual(before,(self.root/'.mvp/state.json').read_bytes())
    def test_auto_design_finishes_without_build(self):
        self.start(mode='design',gate='auto')
        self.assertEqual(self.p.state['phase'],'designed'); self.assertNotIn('build',self.fake.calls)
    def test_cli_failure_cannot_reuse_old_spec(self):
        (self.root/'SPEC.md').write_text(SPEC)
        def fail(*a,**kw): raise m.PipelineError('CLI failed')
        self.p.invoke=fail
        with self.assertRaises(m.PipelineError): self.start()
        self.assertEqual(self.p.state['phase'],'spec_failed')
    def test_invalid_review_never_passes(self):
        self.start(); self.fake.reviews=[{'findings':[{'severity':'unknown'}]}]
        self.p.approve(); self.assertEqual(self.p.state['phase'],'design_pending_approval')
        self.assertEqual(self.p.state['review_verdict'],'undetermined')
    def test_contract_changed_before_approval_stops(self):
        self.start(); self.p.approve(); (self.root/'SPEC.md').write_text('changed')
        with self.assertRaises(m.PipelineError): self.p.approve()
        self.assertNotIn('build',self.fake.calls)
    def test_delta_resolution_and_reentry_preserve_ledger(self):
        f={'severity':'must','where':'A1','summary':'missing error handling','why':'contract','fix':'add it'}
        self.fake.reviews=[{'findings':[f]}]
        self.start(); self.p.approve()
        self.assertEqual(self.p.state['review_verdict'],'pass')
        self.assertIn('review-delta',self.fake.calls)
        n=len(self.p.ledger()); self.p.reject('clarify design')
        self.assertGreaterEqual(len(self.p.ledger()),n)
        self.assertEqual(self.p.state['phase'],'design_pending_approval')
    def test_unknown_resolution_is_transactionally_rejected(self):
        self.start()
        with self.assertRaises(m.PipelineError):
            self.p.apply_review({'resolved':['L-999'],'unresolved':[],'new':[]},1,True)
        self.assertEqual(self.p.ledger(),[])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve()
        self.old=os.environ.get('MVP_CODEX_BIN'); os.environ['MVP_CODEX_BIN']=str(ROOT/'tests/fake_codex.py')
        self.p=m.Pipeline(self.root)
    def tearDown(self):
        import os
        if self.old is None: os.environ.pop('MVP_CODEX_BIN',None)
        else: os.environ['MVP_CODEX_BIN']=self.old
        os.environ.pop('MVP_TEST_SCENARIO',None); self.tmp.cleanup()
    def test_real_subprocess_boundary_auto_build(self):
        self.p.start('Add integers',skills='lite',gate='auto',profile='fast')
        self.assertEqual(self.p.state['phase'],'built')
        self.assertTrue((self.root/'add.py').exists())
        self.assertTrue((self.root/'.mvp/test.log').exists())
        self.assertGreaterEqual(len(list((self.root/'.mvp/calls').glob('*/events.jsonl'))),5)
    def test_build_dependencies_survive_until_gate_then_cleanup(self):
        import os
        os.environ['MVP_TEST_SCENARIO']='dependency'
        self.p.start('test',skills='lite',gate='auto',profile='fast')
        self.assertEqual(self.p.state['phase'],'built')
        self.assertFalse((self.root/'node_modules').exists())
        self.assertIsNone(self.p.invoke.build_workspace)

    def test_failures_never_write_spec(self):
        import os
        for scenario in ('exit','missing','invalid','timeout'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as t:
                os.environ['MVP_TEST_SCENARIO']=scenario
                p=m.Pipeline(t)
                with self.assertRaises(m.PipelineError): p.start('test',skills='lite',timeout=1)
                self.assertFalse((Path(t)/'SPEC.md').exists());self.assertEqual(p.state['phase'],'spec_failed')
    def test_build_export_protects_contract_control_and_symlinks(self):
        import os
        for scenario in ('contract','control','symlink'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as t:
                os.environ['MVP_TEST_SCENARIO']=scenario
                p=m.Pipeline(t)
                with self.assertRaises(m.PipelineError): p.start('test',skills='lite',gate='auto',profile='fast')
                self.assertEqual(p.state['phase'],'build_failed')
                self.assertEqual((Path(t)/'SPEC.md').read_text(),SPEC.replace('Add two integers','add(2,3) equals 5'))
                self.assertFalse((Path(t)/'add.py').exists())
    def test_generated_tests_cannot_mutate_approved_contract(self):
        import os
        os.environ['MVP_TEST_SCENARIO']='tests-mutate'
        self.p.start('test',skills='lite',gate='auto',profile='fast')
        self.assertEqual(self.p.state['phase'],'build_incomplete')
        self.assertIn('A1',(self.root/'SPEC.md').read_text())

class GateTests(unittest.TestCase):
    setUp = PipelineTests.setUp
    tearDown = PipelineTests.tearDown
    start = PipelineTests.start
    def test_auto_holds_on_review_budget_exhaustion(self):
        self.fake.reviews=[{'findings':[{'severity':'must','where':'A1','summary':'missing','why':'contract','fix':'add'}]}]
        self.start(gate='auto',profile='fast')
        self.assertEqual(self.p.state['phase'],'design_pending_approval')
        self.assertEqual(self.p.state['review_verdict'],'exhausted')
        self.assertNotIn('build',self.fake.calls)
    def test_deadlock_uses_finding_ids(self):
        f={'severity':'must','where':'A1','summary':'missing','why':'contract','fix':'add'}
        delta={'resolved':[],'unresolved':[{'id':'L-001','note':'still missing'}],'new':[]}
        self.fake.reviews=[{'findings':[f]},delta,delta]
        self.start(); self.p.approve()
        self.assertEqual(self.p.state['review_verdict'],'deadlock')
        self.assertEqual(self.p.state['rounds']['review'],3)
    def test_auto_holds_with_zero_spec_ids(self):
        self.p.invoke=lambda *a,**kw:{'content':'# No acceptance IDs'}
        self.start(gate='auto')
        self.assertEqual(self.p.state['phase'],'spec_pending_approval')
    def test_partial_delta_does_not_close_anything(self):
        self.start(); f={'severity':'must','where':'A1','summary':'missing','why':'contract','fix':'add'}
        self.p.apply_review({'findings':[f,f]},1,False)
        before=self.p.ledger()
        with self.assertRaises(m.PipelineError): self.p.apply_review({'resolved':['L-001'],'unresolved':[],'new':[]},2,True)
        self.assertEqual(self.p.ledger(),before)
    def test_full_design_prompt_is_available(self):
        self.p.start('Modules and features',mode='design',gate='auto')
        self.assertEqual(self.p.state['phase'],'designed')
    def test_existing_design_is_not_reused_for_new_idea(self):
        (self.root/'DESIGN.md').write_text('# Unrelated legacy design\nA1\n')
        self.start(); self.p.approve()
        self.assertIn('design',self.fake.calls)
        self.assertNotIn('Unrelated legacy',(self.root/'DESIGN.md').read_text())

class CLITests(unittest.TestCase):
    def test_multiline_idea_file_and_lock(self):
        import os, subprocess, fcntl
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); idea=root/'idea.txt'; idea.write_text('Line one\n$(touch BAD) [a|b] <x>')
            env={**os.environ,'MVP_CODEX_BIN':str(ROOT/'tests/fake_codex.py')}
            cmd=[sys.executable,str(ROOT/'bin/pipeline.py'),'--project',t]
            run=subprocess.run(cmd+['start','--lite','--idea-file',str(idea)],env=env,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            state=json.loads((root/'.mvp/state.json').read_text())
            self.assertEqual(state['idea'],idea.read_text()); self.assertFalse((root/'BAD').exists())
            with (root/'.mvp/lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                status=subprocess.run(cmd+['status'],env=env,capture_output=True,text=True)
                self.assertEqual(status.returncode,0)
                blocked=subprocess.run(cmd+['approve'],env=env,capture_output=True,text=True)
                self.assertNotEqual(blocked.returncode,0); self.assertIn('Another pipeline',blocked.stderr)

if __name__=='__main__': unittest.main()
