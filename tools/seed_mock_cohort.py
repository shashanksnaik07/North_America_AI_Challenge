"""Seed the 12 x 32 synthetic IEP review matrix into the local workspace."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import mock_cohort as M

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',dest='cases')
    parser.add_argument('--template',action='append',dest='templates')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if args.verify_only: result=M.verify_cohort(progress=lambda message:print(message,flush=True))
    else: result=M.seed_cohort(M.load_sources(),args.cases,args.templates)
    print(json.dumps({k:v for k,v in result.items() if k!='pairs'},indent=2))
