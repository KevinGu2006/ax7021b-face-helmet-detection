import json,time
from pathlib import Path
import cv2,numpy as np
from face_detection import FaceDetector
from combined_pipeline import CombinedPipeline
ROOT=Path(__file__).resolve().parent
def main():
    detector=FaceDetector();pipeline=CombinedPipeline();results=[]
    demo=ROOT/'examples';demo.mkdir(exist_ok=True)
    data=json.loads((ROOT/'test_inputs/manifest.json').read_text(encoding='utf-8'))
    sources=[ROOT/'test_inputs'/s['file'] for s in data]
    for idx,path in enumerate(sources):
        image=cv2.imread(str(path));expected=detector.detect_faces(image)
        out,record=pipeline.run(image)
        actual=[r['face_bbox'] for r in record['detections']]
        if actual!=expected:raise AssertionError('Face detection changed')
        if expected:
            reference,_=pipeline.helmet.predict(image)
            if reference!=record['helmet_detections']:raise AssertionError('Helmet detection changed')
        record['source']=str(path);record['face_matches_original']=True
        (demo/('%03d.json'%idx)).write_text(json.dumps(record,indent=2),encoding='utf-8')
        cv2.imwrite(str(demo/('%03d.png'%idx)),out)
        results.append(record)
    summary={'images':len(results),'face_exact_agreement':len(results),'helmet_exact_agreement_on_executed_frames':sum(r['face_count']>0 for r in results),
      'no_face_model_skips':sum(r['face_count']==0 for r in results),'matched_faces':sum(sum(d['helmet_bbox'] is not None for d in r['detections']) for r in results),
      'total_faces':sum(r['face_count'] for r in results),'median_total_ms':float(np.median([r['processing_ms'] for r in results])),
      'median_with_faces_ms':float(np.median([r['processing_ms'] for r in results if r['face_count']])),
      'board_tested':False,'association_accuracy_measured':False,
      'note':'PC regression only. Face/head pairing has no independent real pairing GT; synthetic unit tests do not prove field association accuracy.'}
    (ROOT/'validation.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
