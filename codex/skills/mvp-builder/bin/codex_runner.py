"""Codex subprocess boundary. No API SDK, Claude dependency, or shell interpolation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

PLUGIN = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.mvp', '.codex', '.agents', '.claude', 'node_modules', '.venv',
        'venv', '__pycache__', '.pytest_cache', '.DS_Store'}
PROTECTED = {'SPEC.md', 'DESIGN.md', 'AGENTS.md', 'CLAUDE.md'}

class PipelineError(RuntimeError):
    pass

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def ignored(name):
    return name in SKIP or name == '.env' or name.startswith('.env.')

def inventory(root):
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not ignored(d)]
        for name in dirs + files:
            path = Path(folder) / name
            if path.is_symlink():
                raise PipelineError(f'Symlinks are not supported in build input/output: {path}')
        for name in files:
            if ignored(name): continue
            path=Path(folder)/name
            if not path.is_file(): raise PipelineError(f'Not a regular file: {path}')
            result[path.relative_to(root).as_posix()] = digest(path)
    return result

def run_process(command, *, cwd, stdout, stderr, timeout, stdin=None):
    """Timeout kills the subprocess group, including tools launched by Codex."""
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                               stdout=stdout, stderr=stderr, start_new_session=True)
    try:
        process.communicate(stdin.encode() if stdin is not None else None, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        os.killpg(process.pid, signal.SIGTERM)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait()
        raise PipelineError('Subprocess interrupted or timed out')
    return process.returncode

class CodexRunner:
    def __init__(self, root, settings):
        self.root = Path(root).resolve()
        self.settings = settings

    def __call__(self, stage, prompt, *, schema='document', instructions=''):
        logdir=self.root/'.mvp/calls'/f'{time.time_ns()}-{stage}'
        logdir.mkdir(parents=True)
        full_prompt=('Batch pipeline node. The orchestration program owns approvals, state, and ledger. '
                     'Do only the requested node; do not launch this pipeline recursively. '
                     'Do not request approval in this node. Return the requested JSON object.\n\n'
                     + instructions + '\n\n' + prompt)
        if stage != 'build':
            full_prompt += ('\nRead files as needed. Do not write any files. For a document request return '
                            'the entire requested document in the content field; for review return the findings JSON.')
        args=[os.environ.get('MVP_CODEX_BIN','codex'), 'exec', '-C', str(self.root),
              '--skip-git-repo-check', '--ephemeral', '--json', '--color','never',
              '--sandbox', 'workspace-write' if stage=='build' else 'read-only',
              '--output-schema',str(PLUGIN/'schemas'/f'{schema}.json'),
              '--output-last-message',str(logdir/'response.json')]
        # Honor user model/config by default. Never bypass sandbox or approval policy.
        if self.settings.get('model'): args += ['--model',self.settings['model']]
        if self.settings.get('effort'): args += ['-c','model_reasoning_effort='+json.dumps(self.settings['effort'])]
        args += ['-']
        atomic_json(logdir/'request.json',{'stage':stage,'prompt':full_prompt,'argv':args})
        staging=None
        try:
            if stage=='build':
                before=inventory(self.root)
                staging=tempfile.TemporaryDirectory(prefix='mvp-codex-build-')
                work=Path(staging.name)/'work'
                shutil.copytree(self.root,work,ignore=lambda _,names:[n for n in names if ignored(n)])
                args[args.index('-C')+1]=str(work)
                atomic_json(logdir/'request.json',{'stage':stage,'prompt':full_prompt,'argv':args})
            else: work=self.root
            with (logdir/'events.jsonl').open('w') as out, (logdir/'stderr.log').open('w') as err:
                rc=run_process(args,cwd=work,stdout=out,stderr=err,
                               timeout=self.settings.get('timeout',900),stdin=full_prompt)
            atomic_json(logdir/'execution.json',{'exit_code':rc})
            if rc: raise PipelineError(f'Codex exited {rc}; see {logdir}')
            response=logdir/'response.json'
            if not response.is_file(): raise PipelineError(f'Codex returned no response: {logdir}')
            try: result=json.loads(response.read_text())
            except (ValueError,UnicodeError) as e: raise PipelineError(f'Invalid response JSON: {logdir}') from e
            if not isinstance(result,dict): raise PipelineError('Response must be an object')
            if stage=='build':
                if not isinstance(result.get('summary'),str): raise PipelineError('Build response requires summary')
                after=inventory(work)
                for name in PROTECTED:
                    if before.get(name)!=after.get(name): raise PipelineError(f'Build changed protected contract: {name}')
                if (work/'.mvp').exists(): raise PipelineError('Build wrote pipeline control state')
                if inventory(self.root)!=before: raise PipelineError('Project changed during build; refusing to overwrite it')
                changed=[n for n,h in after.items() if before.get(n)!=h]
                deleted=sorted(set(before)-set(after))
                # Validation precedes any export. Contracts/control files never come back from the model.
                for name in changed:
                    dest=self.root/name; dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(work/name,dest)
                for name in deleted: (self.root/name).unlink()
                atomic_json(logdir/'changes.json',{'changed':changed,'deleted':deleted})
            return result
        except (OSError,ValueError) as e:
            raise PipelineError(f'Codex invocation failed: {e}; see {logdir}') from e
        finally:
            if staging: staging.cleanup()
