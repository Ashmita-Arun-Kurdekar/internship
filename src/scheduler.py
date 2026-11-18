"""Local arrival/schedule simulator. python -m src.scheduler --interval 60"""
import argparse
import hashlib
import time
from pathlib import Path
from .configuration import load_config
from .main import run


def signature(base):
    config=load_config(base)
    folder=base/config["settings"]["input_folder"]
    if not folder.exists():
        folder=base/"sample-data"
    paths=list(folder.rglob("*.json"))+list((base/"config").glob("*.json"))
    return hashlib.sha256(b"".join(str(p).encode()+p.read_bytes() for p in sorted(paths))).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--interval",type=float,default=60)
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    if args.interval<1:
        parser.error("interval must be at least one second")
    previous=None
    try:
        while True:
            current=signature(args.base)
            if current!=previous:
                run(args.base)
                previous=current
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__=="__main__":
    main()
