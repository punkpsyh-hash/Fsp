import random, sys, json, importlib
from .core import request_for, make_example
mod = importlib.import_module('ml.corpus.' + sys.argv[1])
shown = int(sys.argv[2]) if len(sys.argv) > 2 else 1
bad = 0; total = 0
for fam in mod.FAMILIES:
    for seed in range(60):
        rng = random.Random(seed)
        grade = rng.choice(['junior', 'middle'])
        try:
            sc = fam(rng, grade)
        except Exception as e:
            bad += 1; print('GENERR', fam.__name__, seed, repr(e)); continue
        for kind, (task, brief) in sc['tasks'].items():
            total += 1
            try:
                req = request_for(kind, sc['spec'], grade, sc['skills'], brief)
                ex = make_example(fam.__name__, req, task)
            except Exception as e:
                bad += 1; print('VALERR', fam.__name__, kind, seed, str(e)[:200])
                continue
            if seed < shown:
                print('---', fam.__name__, kind, grade); print('BRIEF:', brief); print('OUT:', ex['completion'])
print('total', total, 'bad', bad)
