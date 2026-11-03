"""Explicitly download provenance-pinned regression inputs and verify hashes."""
from pathlib import Path
import hashlib,json,urllib.request,zipfile
ROOT=Path(__file__).resolve().parent
def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'fpga-regression-inputs'}),timeout=120) as r:return r.read()
def main():
    folder=ROOT/'test_inputs';rows=json.loads((folder/'manifest.json').read_text())
    dataset=json.loads((folder/'dataset_manifest.json').read_text())
    by_name={Path(r['file']).name:r for r in dataset['samples']}
    archive=None
    try:
        for row in rows:
            target=folder/row['file']
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==row['sha256']:continue
            if 'source_url' in row:data=fetch(row['source_url'])
            else:
                if archive is None:
                    cache=ROOT/'.asset_cache';cache.mkdir(exist_ok=True)
                    file=cache/'dataset_test.zip'
                    if not file.exists():
                        urllib.request.urlretrieve(dataset['source'],file)
                    archive=zipfile.ZipFile(file)
                original=by_name[row['file'].split('_',1)[1]]['source_name']
                names=[n for n in archive.namelist() if Path(n).name==original]
                if len(names)!=1:raise ValueError('Dataset image missing or ambiguous: '+original)
                data=archive.read(names[0])
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('SHA256 mismatch: '+row['file'])
            target.write_bytes(data)
        print('Verified all',len(rows),'test images')
    finally:
        if archive:archive.close()
if __name__=='__main__':main()
