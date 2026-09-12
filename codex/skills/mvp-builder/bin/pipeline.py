#!/usr/bin/env python3
"""Program-owned MVP state machine, ported from Claude MVP-Builder 0.4.2."""
import argparse
import csv
import difflib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import shutil
import tempfile
from contextlib import nullcontext
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from codex_runner import CodexRunner, PipelineError, atomic_json, digest, inventory, run_process

PLUGIN=Path(__file__).resolve().parents[1]

def ids(text):
    return sorted(set(re.findall(r'^\|\s*\*{0,2}([A-Z][0-9]+)\*{0,2}\s*\|',text,re.M)))

def contains(text, identifier):
    return re.search(r'(?<![A-Za-z0-9])'+re.escape(identifier)+r'(?![A-Za-z0-9])',text) is not None

class Pipeline:
    def __init__(self,root,invoke=None):
        self.root=Path(root).resolve(); self.meta=self.root/'.mvp'; self.file=self.meta/'state.json'
        if self.meta.is_symlink() or self.file.is_symlink(): raise PipelineError('Control paths must not be symlinks')
        self.state=json.loads(self.file.read_text()) if self.file.exists() else {}
        if self.file.exists() and (not isinstance(self.state,dict) or self.state.get('engine')!='codex' or self.state.get('version')!=1):
            raise PipelineError('Unsupported state format; use a separate project for this Codex port')
        self.invoke=invoke or CodexRunner(self.root,self.state.get('settings',{}))

    def save(self): atomic_json(self.file,self.state)
    def event(self,event,**fields):
        self.state.setdefault('history',[]).append({'event':event,'time':time.time(),**fields}); self.save()
    def phase(self,value): self.state['phase']=value; self.save()
    def require(self,*allowed):
        if self.state.get('phase') not in allowed:
            raise PipelineError(f"Current phase {self.state.get('phase','not started')}; expected {', '.join(allowed)}")
    def read(self,name):
        path=self.root/name
        if not path.is_file() or path.is_symlink(): raise PipelineError(f'Missing or unsafe artifact: {name}')
        return path.read_text()
    def write(self,name,text):
        if not isinstance(text,str) or not text.strip(): raise PipelineError('Document response must have nonempty content')
        path=self.root/name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=self.root.parent):
            raise PipelineError(f'Symlink output is not supported: {name}')
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.mvp-tmp'); temp.write_text(text); temp.replace(path)
    def settings(self,profile):
        result={}
        with (PLUGIN/'policy/budget.tsv').open() as f:
            result.update({r['key']:int(r['value']) for r in csv.DictReader(f,delimiter='\t')})
        profiles={}
        with (PLUGIN/'policy/profiles.tsv').open() as f:
            for r in csv.DictReader(f,delimiter='\t'):
                profiles.setdefault(r['profile'],{})[r['key']]=r['value']
        if profile!='standard' and profile not in profiles: raise PipelineError(f'Unknown profile: {profile}')
        for k,v in profiles.get(profile,{}).items(): result[k]=int(v) if k in result else v
        for key in ('design_rounds','review_max_attempts','review_max_stall','build_rounds'):
            if result[key]<1: raise PipelineError(f'Invalid budget: {key}')
        return result
    def instructions(self,name):
        return (PLUGIN/'prompts'/self.state['skills']/f'{name}.md').read_text()
    def node(self,stage,prompt,*,schema='document',skill=None):
        self.event('node_started',stage=stage)
        try:
            result=self.invoke(stage,prompt,schema=schema,instructions=self.instructions(skill) if skill else '')
            if not isinstance(result,dict): raise PipelineError('Node result must be an object')
            if schema=='document' and (not isinstance(result.get('content'),str) or not result['content'].strip()):
                raise PipelineError('Missing nonempty document content')
        except Exception as e:
            self.event('node_failed',stage=stage,error=str(e))
            raise PipelineError(str(e)) from e
        self.event('node_finished',stage=stage); return result
    def contract_check(self):
        for name,expected in self.state.get('contracts',{}).items():
            path=self.root/name
            if not path.is_file() or path.is_symlink() or digest(path)!=expected:
                raise PipelineError(f'Approved contract changed: {name}')
    def snapshot(self,name):
        self.state.setdefault('contracts',{})[name]=digest(self.root/name)
        self.write('.mvp/approved/'+name,self.read(name)); self.save()

    def start(self,idea,*,skills='full',profile='standard',mode='build',gate='human',model=None,effort=None,timeout=900):
        if self.state: raise PipelineError('A run already exists. Use approve/reject/status or a new project directory.')
        if not idea.strip(): raise PipelineError('Idea must not be empty')
        if skills not in ('full','lite') or mode not in ('build','design') or gate not in ('human','auto'):
            raise PipelineError('Invalid skills/mode/gate')
        settings=self.settings(profile); settings['timeout']=timeout
        if model: settings['model']=model
        if effort: settings['effort']=effort
        self.state={'version':1,'engine':'codex','phase':'spec_running','idea':idea,'skills':skills,
                    'profile':profile,'mode':mode,'gate':gate,'settings':settings,'rounds':{},'history':[],'contracts':{}}
        self.save()
        if isinstance(self.invoke,CodexRunner): self.invoke.settings=settings
        task=('Write a high-level SPEC.md with module M1 and feature F1 tables, responsibilities, inputs, outputs, '
              'scope and contracts. Each ID must be in the FIRST cell of a Markdown table. Do not implement.'
              if mode=='design' else
              'Write SPEC.md: goals, scope, constraints, acceptance criteria. Each acceptance criterion has '
              'an ID such as A1 in the FIRST cell of a Markdown table. Put IDs only in that table. Do not implement.')
        try:
            result=self.node('spec','Idea:\n'+idea+'\n\n'+task,skill='spec')
            self.write('SPEC.md',result['content'])
        except PipelineError:
            self.phase('spec_failed'); raise
        self.spec_pending()
        if gate=='auto':
            if self.state['rounds']['spec_ids']:
                self.event('spec_auto_gate_pass'); self.approve()
            else: self.event('spec_auto_gate_hold',reason='no acceptance IDs')

    def spec_pending(self):
        self.state['rounds']['spec_ids']=len(ids(self.read('SPEC.md')))
        self.phase('spec_pending_approval'); self.event('spec_written',ids=self.state['rounds']['spec_ids'])

    def approve(self):
        self.require('spec_pending_approval','design_pending_approval')
        self.contract_check()
        if self.state['phase']=='spec_pending_approval':
            if not ids(self.read('SPEC.md')): raise PipelineError('SPEC has no acceptance IDs; reject and revise it first')
            self.snapshot('SPEC.md'); self.event('spec_approved'); self.design(); return
        # Human may explicitly accept nonzero findings; undetermined/failed execution is never a success.
        if self.state.get('review_verdict')=='undetermined': raise PipelineError('Review undetermined; reject to retry before approval')
        coverage=self.design_check()
        if not coverage['pass']: raise PipelineError('Design misses SPEC IDs; reject to revise')
        if self.state['mode']=='design':
            if not self.decompose_check()['pass']: raise PipelineError('Subproject decomposition incomplete; reject to revise')
            self.snapshot('DESIGN.md'); self.phase('designed'); self.event('design_mode_done'); return
        self.snapshot('DESIGN.md'); self.event('design_approved'); self.build()

    def reject(self,reason):
        self.require('spec_pending_approval','design_pending_approval')
        if not reason.strip(): raise PipelineError('Rejection requires feedback')
        self.contract_check()
        if self.state['phase']=='spec_pending_approval':
            result=self.node('spec-revise','Revise SPEC.md according to this feedback, retaining acceptance IDs:\n'+reason,skill='spec')
            self.write('SPEC.md',result['content']); self.event('spec_rejected',reason=reason); self.spec_pending()
        else:
            before=self.read('DESIGN.md')
            result=self.node('design-revise','Revise DESIGN.md only; SPEC is an approved contract. Preserve the ID mapping and subproject decomposition. Feedback:\n'+reason)
            self.write('DESIGN.md',result['content']); self.diff(before)
            self.event('design_rejected',reason=reason); self.design()

    def design_check(self):
        specids=ids(self.read('SPEC.md')); design=self.read('DESIGN.md')
        missing=[i for i in specids if not contains(design,i)]
        result={'total':len(specids),'covered':len(specids)-len(missing),'missingIds':missing,
                'coverage':int(100*(len(specids)-len(missing))/len(specids)) if specids else 0,
                'pass':bool(specids) and not missing}
        atomic_json(self.meta/'design-check.json',result); return result
    def decompose_check(self):
        match=re.search(r'^#{1,3} .*하위 프로젝트 분해[^\n]*\n(.*?)(?=^#{1,3} |\Z)',self.read('DESIGN.md'),re.M|re.S)
        section=match[1] if match else ''
        specids=ids(self.read('SPEC.md')); missing=[i for i in specids if not contains(section,i)]
        result={'unassignedIds':missing,'pass':bool(section.strip()) and bool(specids) and not missing}
        atomic_json(self.meta/'decompose-check.json',result); return result
    def diff(self,before):
        text=''.join(difflib.unified_diff(before.splitlines(True),self.read('DESIGN.md').splitlines(True),fromfile='before',tofile='DESIGN.md'))
        self.write('.mvp/design-diff-latest.txt',text or '(no changes)\n')
    def design(self):
        self.phase('design_running')
        try:
            for _ in range(self.state['settings']['design_rounds']):
                self.contract_check()
                r=self.state['rounds'].get('design',0)+1; self.state['rounds']['design']=r; self.save()
                existing=r>1 and (self.root/'DESIGN.md').exists()
                check=self.design_check() if existing else None
                if check and check['pass']: self.event('design_generation_skipped',round=r)
                else:
                    task=('Preserve existing DESIGN.md and repair only missing SPEC IDs: '+', '.join(check['missingIds']) if existing else
                          'Read SPEC.md and write DESIGN.md with architecture, modules, interfaces, data, error handling, test strategy, and a mapping of every SPEC ID to design sections.')
                    if self.state['mode']=='design': task+=' Include a section exactly titled "## 하위 프로젝트 분해" with a table: project, assigned SPEC IDs, dependencies, self-contained idea to start each subproject. Assign all SPEC IDs.'
                    result=self.node('design',task,skill='design-highlevel' if self.state['mode']=='design' else 'design')
                    self.write('DESIGN.md',result['content'])
                atomic_json(self.meta/f'design-check-r{r}.json',self.design_check())
            verdict=self.review_loop()
        except PipelineError as e:
            verdict='undetermined'; self.event('design_or_review_failed',reason=str(e))
        self.state['review_verdict']=verdict; self.phase('design_pending_approval')
        self.event('design_phase_done',review_verdict=verdict)
        if self.state['gate']=='auto':
            if verdict=='pass' and self.design_check()['pass']:
                if self.state['mode']=='design' and not self.decompose_check()['pass']:
                    self.event('design_auto_gate_hold',reason='incomplete decomposition'); return
                self.event('design_auto_gate_pass'); self.approve()
            else: self.event('design_auto_gate_hold',reason=verdict)

    def ledger(self):
        path=self.meta/'ledger.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    def findings(self):
        current={}
        for e in self.ledger():
            if e['event']=='found': current[e['id']]={**e,'state':'open'}
            else: current[e['id']]['state']='resolved' if e['event']=='resolved' else 'open'
        return current
    def open_must(self):
        return sorted(i for i,f in self.findings().items() if f['state']=='open' and f['severity']=='must')
    def append_events(self,events):
        # Validate the entire response before append: malformed responses never partially close findings.
        with (self.meta/'ledger.jsonl').open('a') as out:
            for event in events: out.write(json.dumps(event,ensure_ascii=False)+'\n')
    def apply_review(self,result,r,delta):
        known=self.findings(); events=[]
        def finding(f):
            if not isinstance(f,dict) or f.get('severity') not in ('must','should','nit'):
                raise PipelineError('Invalid finding severity')
            if any(not isinstance(f.get(k),str) or not f[k].strip() for k in ('where','summary','why','fix')):
                raise PipelineError('Finding requires where/summary/why/fix')
        if delta:
            if set(result)!= {'resolved','unresolved','new'} or any(not isinstance(result[k],list) for k in result):
                raise PipelineError('Invalid delta review schema')
            resolved=result['resolved']; unresolved=result['unresolved']
            if any(not isinstance(i,str) for i in resolved) or any(not isinstance(u,dict) or not isinstance(u.get('id'),str) or not isinstance(u.get('note'),str) for u in unresolved):
                raise PipelineError('Invalid resolution fields')
            checked=resolved+[u['id'] for u in unresolved]
            if len(set(checked))!=len(checked) or set(checked)!=set(self.open_must()):
                raise PipelineError('Delta must judge each open must exactly once')
            events += [{'event':'resolved','id':i,'round':r,'by':'reviewer'} for i in resolved]
            events += [{'event':'reopened','id':u['id'],'round':r,'by':'reviewer','note':u['note']} for u in unresolved]
            new=result['new']
        else:
            if set(result)!={'findings'} or not isinstance(result['findings'],list): raise PipelineError('Invalid full review schema')
            new=result['findings']
        for f in new:
            finding(f); identifier=f'L-{len(known)+1:03d}'
            event={'event':'found','id':identifier,'round':r,'by':'reviewer',**f}
            known[identifier]=event; events.append(event)
        self.append_events(events)
    def review_loop(self):
        previous=None; stall=0; settings=self.state['settings']
        for _ in range(settings['review_max_attempts']):
            self.contract_check()
            r=self.state['rounds'].get('review',0)+1; self.state['rounds']['review']=r; self.save()
            delta=bool(self.ledger()) and (self.meta/'design-diff-latest.txt').exists()
            severity=(PLUGIN/'policy/severity.tsv').read_text()
            task='Review DESIGN.md against SPEC.md. Report only evidence-backed issues using these severities:\n'+severity
            if delta:
                task+='\nDelta review: read .mvp/design-diff-latest.txt. Judge every open must exactly once. Do not report known issues as new. Current findings:\n'+json.dumps(self.findings(),ensure_ascii=False)
            result=self.node('review-delta' if delta else 'review',task,schema='review-delta' if delta else 'review',skill=None if delta else 'review')
            self.apply_review(result,r,delta)
            openids=self.open_must(); report={'round':r,'openMust':len(openids),'openMustIds':openids}
            atomic_json(self.meta/f'review-r{r}.json',report)
            self.event('review_result',**report)
            if not openids:
                self.write('.mvp/triage.md','# Remaining should/nit\n'+ '\n'.join(f"- {i}: {f['summary']}" for i,f in self.findings().items() if f['state']=='open'))
                return 'pass'
            stall=stall+1 if openids==previous else 0; previous=openids
            if stall>=settings['review_max_stall']: self.event('review_deadlock',ids=openids); return 'deadlock'
            if _+1>=settings['review_max_attempts']: self.event('review_exhausted',ids=openids); return 'exhausted'
            before=self.read('DESIGN.md')
            result=self.node('design-fix','Fix only these open must findings in DESIGN.md. Preserve SPEC and its mapping.\n'+json.dumps([self.findings()[i] for i in openids],ensure_ascii=False))
            self.write('DESIGN.md',result['content']); self.diff(before)
            self.append_events([{'event':'claimed','id':i,'round':r,'by':'fixer'} for i in openids])
        return 'exhausted'

    def build_check(self):
        files=inventory(self.root)
        sources=[n for n in files if Path(n).suffix in ('.py','.js','.ts','.tsx','.jsx') and 'test' not in Path(n).name and not n.startswith(('tests/','test/','tasks/'))]
        tests=[n for n in files if Path(n).suffix in ('.py','.js','.ts','.tsx','.jsx') and ('test' in Path(n).name or 'spec' in Path(n).name or n.startswith(('tests/','test/')))]
        text='\n'.join((self.root/n).read_text(errors='replace') for n in tests)
        specids=ids(self.read('SPEC.md')); missing=[i for i in specids if not contains(text,i)]
        command=None
        if (self.root/'package.json').is_file(): command=['npm','test']
        elif (self.root/'pyproject.toml').is_file() or (self.root/'pytest.ini').is_file(): command=[sys.executable,'-m','pytest','-q']
        elif tests:
            testdir='tests' if (self.root/'tests').is_dir() else 'test' if (self.root/'test').is_dir() else '.'
            command=[sys.executable,'-m','unittest','discover','-s',testdir,'-v']
        rc=99
        test_contract='ok'
        if command:
            # Tests are generated code too: run them in a disposable project copy.
            # This isolates relative file writes, not arbitrary hostile code; see README.
            from codex_runner import ignored
            prepared=getattr(self.invoke,'build_workspace',None)
            context=nullcontext(None) if prepared else tempfile.TemporaryDirectory(prefix='mvp-codex-test-')
            with context as temp:
                work=prepared or Path(temp)/'work'
                if not prepared:
                    shutil.copytree(self.root,work,ignore=lambda _,names:[n for n in names if ignored(n)])
                before_tests=inventory(work)
                local_python=work/'.venv/bin/python'
                if command[0]==sys.executable and local_python.exists(): command[0]=str(local_python)
                with (self.meta/'test.log').open('w') as log:
                    rc=run_process(command,cwd=work,stdout=log,stderr=log,timeout=self.state['settings']['timeout'])
                for name,expected in self.state.get('contracts',{}).items():
                    path=work/name
                    if not path.is_file() or path.is_symlink() or digest(path)!=expected: test_contract='modified'
                if (work/'.mvp').exists(): test_contract='modified'
                if inventory(work)!=before_tests: test_contract='modified'
                if 'unittest' in command and re.search(r'Ran 0 tests', (self.meta/'test.log').read_text()): rc=99
        contract=test_contract
        try: self.contract_check()
        except PipelineError: contract='modified'
        result={'sourceFiles':len(sources),'testFiles':len(tests),'testExit':rc,'runner':command,
                'specIds':len(specids),'missingIds':missing,'contract':contract,
                'pass':bool(sources) and bool(tests) and bool(specids) and rc==0 and not missing and contract=='ok'}
        atomic_json(self.meta/'build-check.json',result); return result
    def build(self):
        self.phase('build_running')
        try:
            self.contract_check()
            # Regenerate the task plan from the current approved contracts, never reuse an unverified old plan.
            result=self.node('plan','Read approved SPEC.md and DESIGN.md. Write tasks/todo.md as vertical implementation slices, each with acceptance IDs and completion evidence.',skill='plan')
            self.write('tasks/todo.md',result['content'])
            for r in range(1,self.state['settings']['build_rounds']+1):
                self.contract_check()
                feedback=json.dumps(json.loads((self.meta/'build-check.json').read_text())) if (self.meta/'build-check.json').exists() else 'First build round'
                self.node('build','Implement tasks/todo.md in this isolated workspace. Write real source and tests. Run failing tests first, then implement and verify. Put acceptance IDs in tests. Do not modify SPEC.md, DESIGN.md, AGENTS.md or CLAUDE.md. Do not write .mvp or modify repository/agent configuration. No commits required. Final response: summary. Previous gate:\n'+feedback,schema='build',skill='build')
                check=self.build_check(); self.state['rounds']['build']=r; self.event('build_gate',**check)
                if check['pass']: self.phase('built'); self.event('build_done'); return
            self.phase('build_incomplete'); self.event('build_incomplete')
        except PipelineError:
            self.phase('build_failed'); raise
        finally:
            if isinstance(self.invoke,CodexRunner): self.invoke.cleanup()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default='.')
    sub=parser.add_subparsers(dest='command',required=True)
    start=sub.add_parser('start'); start.add_argument('idea',nargs='*'); start.add_argument('--idea-file')
    modes=start.add_mutually_exclusive_group(); modes.add_argument('--lite',action='store_true'); modes.add_argument('--full',action='store_true')
    start.add_argument('--skills',choices=['lite','full']); start.add_argument('--mode',choices=['build','design'],default='build'); start.add_argument('--design',action='store_true')
    start.add_argument('--fast',action='store_true'); start.add_argument('--profile',default='standard'); start.add_argument('--auto-approve',action='store_true')
    start.add_argument('--model'); start.add_argument('--effort'); start.add_argument('--timeout',type=int,default=900)
    sub.add_parser('approve'); sub.add_parser('status')
    reject=sub.add_parser('reject'); reject.add_argument('reason',nargs='*'); reject.add_argument('--reason-file')
    args=parser.parse_args(); root=Path(args.project).resolve()
    if not root.is_dir(): parser.error('Project directory does not exist')
    try:
        if args.command=='status':
            p=Pipeline(root); print(json.dumps(p.state or {'phase':'not_started'},ensure_ascii=False,indent=2)); return 0
        if (root/'.mvp').is_symlink(): raise PipelineError('.mvp must not be a symlink')
        (root/'.mvp').mkdir(exist_ok=True)
        with (root/'.mvp/lock').open('w') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise PipelineError('Another pipeline command is running')
            p=Pipeline(root)
            if args.command=='start':
                if args.timeout<1: raise PipelineError('Timeout must be positive')
                idea=Path(args.idea_file).read_text() if args.idea_file else ' '.join(args.idea)
                p.start(idea,skills=args.skills or ('lite' if args.lite else 'full'),profile='fast' if args.fast else args.profile,
                        mode='design' if args.design else args.mode,gate='auto' if args.auto_approve else 'human',
                        model=args.model,effort=args.effort,timeout=args.timeout)
            elif args.command=='approve': p.approve()
            else: p.reject(Path(args.reason_file).read_text() if args.reason_file else ' '.join(args.reason))
            print(json.dumps({'phase':p.state['phase'],'rounds':p.state['rounds'],'review_verdict':p.state.get('review_verdict')},ensure_ascii=False,indent=2))
            return 1 if p.state['phase'] in ('build_failed','build_incomplete','spec_failed') else 0
    except (PipelineError,OSError,ValueError) as e:
        print(str(e),file=sys.stderr); return 3

if __name__=='__main__': sys.exit(main())
