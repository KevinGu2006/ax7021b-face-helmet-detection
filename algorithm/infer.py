import argparse,json
from pathlib import Path
import cv2,numpy as np
from combined_pipeline import CombinedPipeline
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',default='outputs');p.add_argument('--profile',choices=['ncnn640','board640'],default='ncnn640');p.add_argument('--execution-backend',choices=['PC','ZYNQ_ARM'],default='PC');a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    try:
        pipeline=CombinedPipeline(helmet_profile=a.profile,execution_backend=a.execution_backend)
        source=Path(a.input)
        if not source.exists():raise FileNotFoundError(source)
        paths=sorted(x for x in source.rglob('*') if x.suffix.lower() in ('.jpg','.png','.bmp','.jpeg')) if source.is_dir() else [source]
        if not paths:raise ValueError('No images')
        records=[]
        for idx,path in enumerate(paths):
            image=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR)
            annotated,record=pipeline.run(image);record['source']=str(path)
            name='%04d_'%idx+path.stem
            ok,data=cv2.imencode('.png',annotated)
            if not ok:raise RuntimeError('Encode failed')
            data.tofile(str(out/(name+'.png')));(out/(name+'.json')).write_text(json.dumps(record,indent=2),encoding='utf-8');records.append(record)
        (out/'summary.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    except Exception as e:
        (out/'error.json').write_text(json.dumps({'error':type(e).__name__,'message':str(e)}),encoding='utf-8');raise
if __name__=='__main__':main()
