"""Compare a raw PL uint8 output against one golden case; nonzero exit on failure."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from face_preproc_reference import compare_gray


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case",required=True)
    p.add_argument("--actual",required=True,help="H*W bytes, no header/padding")
    p.add_argument("--output",default="pl_compare.json")
    a=p.parse_args()
    folder=Path(a.case)
    manifest=json.loads((folder.parent/"manifest.json").read_text(encoding="utf-8"))
    spec=next(x for x in manifest if x["name"]==folder.name)
    shape=(spec["height"],spec["width"])
    expected=np.fromfile(str(folder/"expected_gray.bin"),np.uint8).reshape(shape)
    actual=np.fromfile(a.actual,np.uint8)
    if actual.size != expected.size:
        raise ValueError("Output byte count must equal H*W exactly")
    result=compare_gray(expected,actual.reshape(shape),0)
    result.update(case=folder.name,actual_source=a.actual,
                  note="Offline file comparison only; this tool does not prove board execution")
    Path(a.output).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result)); return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
