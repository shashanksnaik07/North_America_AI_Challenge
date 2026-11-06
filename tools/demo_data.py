r"""Run with .venv\Scripts\python tools/demo_data.py --prepare / --list / --restore ID."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import demo_snapshots as snapshots
import demo_video

parser=argparse.ArgumentParser(description='Recording data snapshots for IEP Bridge')
actions=parser.add_mutually_exclusive_group(required=True)
actions.add_argument('--prepare',action='store_true',help='Prepare recording students and save Demo start once')
actions.add_argument('--list',action='store_true',help='List available snapshots')
actions.add_argument('--restore',metavar='ID',help='Back up the current take, then restore the specified snapshot')
actions.add_argument('--save',metavar='LABEL',help='Save the current application data')
args=parser.parse_args()
if args.prepare: result=demo_video.prepare()
elif args.list: result=[{k:item[k] for k in ('id','label','created','students','reviews')} for item in snapshots.list_snapshots()]
elif args.restore:
    restored=snapshots.restore(args.restore)
    result={key:{k:item[k] for k in ('id','label')} for key,item in restored.items()}
else:
    item=snapshots.capture(args.save);result={k:item[k] for k in ('id','label','students','reviews')}
print(json.dumps(result,indent=2))
