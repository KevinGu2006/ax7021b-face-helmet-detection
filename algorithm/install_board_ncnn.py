"""Explicit project-local install. Refuses wrong Python/CPU/glibc; no system upgrade."""
import platform,sys,json,hashlib,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    if platform.machine()!='armv7l' or sys.version_info[:2]!=(3,10):raise RuntimeError('Requires ARMv7l CPython3.10')
    libc=platform.libc_ver()[1]
    if not libc:
        libc=os.confstr('CS_GNU_LIBC_VERSION').split()[-1]
    if tuple(map(int,libc.split('.')[:2]))<(2,31):raise RuntimeError('Official wheel needs glibc>=2.31; do not upgrade the system for this script')
    metadata=json.loads((ROOT/'wheels/source.json').read_text())
    wheel=next((ROOT/'wheels').glob('*armv7l.whl'))
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('Wheel checksum mismatch')
    target=ROOT/'board_vendor'
    if target.exists():raise FileExistsError('board_vendor already exists; inspect it before reinstalling')
    subprocess.run([sys.executable,'-m','pip','--disable-pip-version-check','install','--no-index','--no-deps','--target',str(target),str(wheel)],check=True)
    sys.path.insert(0,str(target));import ncnn
    (ROOT/'board_install_result.json').write_text(json.dumps({'machine':platform.machine(),'python':sys.version,'glibc':libc,'ncnn':ncnn.__version__,'target':str(target),'system_libraries_upgraded':False},indent=2))
    print('Project-local NCNN import passed. Run board_benchmark.py before changing the preview.')
if __name__=='__main__':main()
