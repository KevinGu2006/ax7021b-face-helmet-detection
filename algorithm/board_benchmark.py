"""Benchmark the complete local pipeline. No camera, HDMI or PL accesses."""
import argparse,json,time,platform,sys
from pathlib import Path
import cv2,numpy as np
from combined_pipeline import CombinedPipeline
def main():
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);p.add_argument('--repeats',type=int,default=5);p.add_argument('--profile',choices=['ncnn640','board640'],default='ncnn640');p.add_argument('--execution-backend',choices=['PC','ZYNQ_ARM'],default='PC');p.add_argument('--output',default='joint_benchmark.json');a=p.parse_args()
    if not 1<=a.repeats<=100:raise ValueError('repeats must be 1..100')
    image=cv2.imdecode(np.fromfile(a.image,np.uint8),cv2.IMREAD_COLOR)
    if image is None:raise ValueError('Cannot read image')
    t=time.perf_counter();pipeline=CombinedPipeline(helmet_profile=a.profile,execution_backend=a.execution_backend);load=(time.perf_counter()-t)*1000
    pipeline.run(image) # explicit warmup, excluded
    rows=[pipeline.run(image)[1] for _ in range(a.repeats)]
    result={'platform':platform.platform(),'machine':platform.machine(),'python':sys.version,'opencv':cv2.__version__,'profile':a.profile,'load_ms':load,'warmup_excluded':True,'samples':rows,'median_total_ms':float(np.median([r['processing_ms'] for r in rows])),'scope':'algorithm only; no capture/DMA/HDMI; no-face samples skip helmet inference'}
    Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='samples'},indent=2))
if __name__=='__main__':main()
