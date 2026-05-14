import ast, sys, os, glob

files = glob.glob('core/**/*.py', recursive=True) + glob.glob('skills/**/*.py', recursive=True) + ['main.py', 'core/tools/legacy/train_intent_v2.py']

# filter out init files or pycache
files = [f for f in files if '__pycache__' not in f and not f.endswith('__init__.py')]

all_ok = True
for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            src = fh.read()
        ast.parse(src)
        print(f'  OK   {f}')
    except SyntaxError as e:
        print(f'  FAIL {f}  =>  {e}')
        all_ok = False
    except FileNotFoundError:
        print(f'  MISS {f}')
        all_ok = False

print()
print('All clear!' if all_ok else 'SYNTAX ERRORS FOUND — see above.')
sys.exit(0 if all_ok else 1)
