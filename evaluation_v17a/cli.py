"""python -m evaluation_v17a.cli INPUT.json OUTPUT.json -- no engine execution."""
import argparse,json,platform
from pathlib import Path
from .scoring import evaluate,serialize

def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    try:raw=json.loads(a.input.read_text(encoding='utf-8'),parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (ValueError,OSError) as e:result={'state':'invalid_input','errors':[str(e)]}
    else:result=evaluate(raw,environment={'python':platform.python_version()},config={'mode':'offline-adjudications-only'})
    a.output.write_text(serialize(result),encoding='utf-8');return 2 if result['state']=='invalid_input' else 0
if __name__=='__main__':raise SystemExit(main())
