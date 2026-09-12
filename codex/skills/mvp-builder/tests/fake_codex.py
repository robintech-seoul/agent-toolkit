#!/usr/bin/env python3
"""Deterministic CLI double. Does not call a model or pretend to be real validation."""
import json
import os
from pathlib import Path
import sys
import time
args=sys.argv[1:]; prompt=sys.stdin.read(); cwd=Path(args[args.index('-C')+1]); out=Path(args[args.index('--output-last-message')+1]); schema=Path(args[args.index('--output-schema')+1]).stem
scenario=os.environ.get('MVP_TEST_SCENARIO','ok')
if scenario=='exit': sys.exit(7)
if scenario=='timeout': time.sleep(5)
if scenario=='missing': sys.exit(0)
if scenario=='invalid': out.write_text('not json'); sys.exit(0)
if schema=='build':
    assert args[args.index('--sandbox')+1]=='workspace-write'
    (cwd/'add.py').write_text('def add(a, b):\n    return a + b\n')
    (cwd/'tests').mkdir(exist_ok=True)
    (cwd/'tests/test_add.py').write_text('import unittest\nfrom add import add\nclass TestAdd(unittest.TestCase):\n    def test_A1(self):\n        self.assertEqual(add(2, 3), 5)\n')
    if scenario=='contract': (cwd/'SPEC.md').write_text('tampered')
    if scenario=='control':
        (cwd/'.mvp').mkdir(); (cwd/'.mvp/state.json').write_text('{}')
    if scenario=='symlink': (cwd/'escape.py').symlink_to('/tmp/outside.py')
    if scenario=='tests-mutate':
        (cwd/'tests/test_add.py').write_text('import unittest\nfrom pathlib import Path\nclass TestAdd(unittest.TestCase):\n    def test_A1(self):\n        Path("SPEC.md").write_text("tampered")\n')
    if scenario=='dependency':
        (cwd/'node_modules').mkdir()
        (cwd/'node_modules/fixture.txt').write_text('prepared by build')
        (cwd/'tests/test_add.py').write_text('import unittest\nfrom pathlib import Path\nfrom add import add\nclass TestAdd(unittest.TestCase):\n    def test_A1(self):\n        self.assertEqual(add(2,3),5)\n        self.assertTrue(Path("node_modules/fixture.txt").exists())\n')
    result={'summary':'fixture implementation'}
else:
    assert args[args.index('--sandbox')+1]=='read-only'
    if schema=='review': result={'findings':[]}
    elif schema=='review-delta': result={'resolved':[],'unresolved':[],'new':[]}
    elif 'tasks/todo.md as vertical' in prompt: result={'content':'# Tasks\n- A1 implement add and tests\n'}
    elif 'write DESIGN.md' in prompt or 'Preserve existing DESIGN.md' in prompt:
        result={'content':'# Design\nA1: add module and unittest\n\n## 하위 프로젝트 분해\n| Project | IDs | Dependencies | idea |\n|---|---|---|---|\n| calc | A1 | none | Create add module |\n'}
    else: result={'content':'# Spec\n| ID | Acceptance |\n|---|---|\n| A1 | add(2,3) equals 5 |\n'}
out.write_text(json.dumps(result));print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
