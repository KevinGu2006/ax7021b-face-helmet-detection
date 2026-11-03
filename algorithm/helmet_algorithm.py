"""Direct two-class head-state detection. No face or color-heuristic gate."""
from pathlib import Path
import ast, time, json, hashlib
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
class HelmetDetector:
    def __init__(self, model=None, backend='ort', confidence=None, candidate=.15,
                 min_head=16, conflict_margin=.15, input_size=640):
        if input_size not in (320,640):raise ValueError('Supported model sizes: 320,640')
        self.input_size=input_size
        config=json.loads((ROOT/'release_config.json').read_text()) if (ROOT/'release_config.json').exists() else {}
        explicit_model=model is not None
        confidence=config.get('confidence',.5) if confidence is None else confidence
        self.confidence=confidence; self.candidate=candidate
        self.min_head=min_head; self.conflict_margin=conflict_margin
        if not 0<=candidate<=confidence<=1: raise ValueError('Invalid thresholds')
        path=str(model or ROOT/config.get('model','models/best.onnx'))
        if not Path(path).exists(): raise FileNotFoundError(path)
        if not explicit_model and config.get('model_sha256') and hashlib.sha256(Path(path).read_bytes()).hexdigest()!=config['model_sha256']:
            raise ValueError('Release model checksum mismatch')
        cv2.setNumThreads(1)
        self.backend=backend
        if backend=='ort':
            import onnxruntime as ort
            options=ort.SessionOptions(); options.intra_op_num_threads=2; options.inter_op_num_threads=1
            self.net=ort.InferenceSession(path,sess_options=options,providers=['CPUExecutionProvider'])
            self.input=self.net.get_inputs()[0].name
            names=ast.literal_eval(self.net.get_modelmeta().custom_metadata_map['names'])
            if [names[i].lower() for i in range(2)]!=['hardhat','no-hardhat']:
                raise ValueError('Wrong model class mapping')
        elif backend=='opencv':
            self.net=cv2.dnn.readNetFromONNX(path)
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        elif backend=='ncnn':
            from ncnn_runtime import NcnnNet
            self.net=NcnnNet(path)
        else: raise ValueError('Unknown backend')

    @staticmethod
    def validate(frame):
        if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8: raise TypeError('uint8 BGR required')
        if frame.ndim!=3 or frame.shape[2]!=3 or min(frame.shape[:2])<2: raise ValueError('HxWx3 BGR required')

    def predict(self,frame):
        self.validate(frame); started=time.perf_counter()
        size=self.input_size
        h,w=frame.shape[:2]; scale=min(size/w,size/h)
        rw,rh=round(w*scale),round(h*scale)
        left,top=(size-rw)//2,(size-rh)//2
        image=np.full((size,size,3),114,np.uint8)
        image[top:top+rh,left:left+rw]=cv2.resize(frame,(rw,rh))
        tensor=cv2.dnn.blobFromImage(image,1/255.,(size,size),swapRB=True,crop=False)
        prepared=time.perf_counter()
        if self.backend=='ort': output=self.net.run(None,{self.input:tensor})[0]
        else: self.net.setInput(tensor); output=self.net.forward()
        inferred=time.perf_counter()
        count=sum((size//stride)**2 for stride in (8,16,32))
        if output.shape!=(1,6,count): raise ValueError('Unexpected YOLO output shape: '+str(output.shape))
        if not np.isfinite(output).all():raise FloatingPointError('Non-finite model output')
        p=output[0].T; scores=p[:,4:]; labels=np.argmax(scores,axis=1); confidence=scores.max(axis=1)
        rows=[]
        for i in np.flatnonzero(confidence>=self.candidate):
            cx,cy,bw,bh=p[i,:4]
            box=[max(0.,(cx-bw/2-left)*w/rw),max(0.,(cy-bh/2-top)*h/rh),
                 min(float(w),(cx+bw/2-left)*w/rw),min(float(h),(cy+bh/2-top)*h/rh)]
            if box[2]<=box[0] or box[3]<=box[1]:continue
            rows.append({'bbox':box,'score':float(confidence[i]),'class_id':int(labels[i])})
        # Same-class NMS first; conflicting class evidence is retained until arbitration.
        kept=[]
        for cls in (0,1):
            group=[r for r in rows if r['class_id']==cls]
            indices=cv2.dnn.NMSBoxes([[r['bbox'][0],r['bbox'][1],r['bbox'][2]-r['bbox'][0],r['bbox'][3]-r['bbox'][1]] for r in group],
                                     [r['score'] for r in group],self.candidate,.45)
            kept.extend(group[int(i)] for i in np.array(indices).ravel())
        remaining=sorted(kept,key=lambda r:-r['score']); detections=[]
        while remaining:
            r=remaining.pop(0); conflicts=[x for x in remaining if iou(r['bbox'],x['bbox'])>=.5]
            remaining=[x for x in remaining if iou(r['bbox'],x['bbox'])<.5]
            opposite=max((x['score'] for x in conflicts if x['class_id']!=r['class_id']),default=0.)
            x1,y1,x2,y2=r['bbox']; reason='model_detection'
            status=['helmet','no_helmet'][r['class_id']]
            if r['score']<self.confidence: status='unknown'; reason='low_score'
            elif min(x2-x1,y2-y1)<self.min_head:status='unknown';reason='small_head'
            elif x1<=1 or y1<=1 or x2>=w-1 or y2>=h-1:status='unknown';reason='head_box_touches_boundary'
            elif opposite and r['score']-opposite<self.conflict_margin:status='unknown';reason='conflicting_classes'
            detections.append({'bbox':[int(np.floor(x1)),int(np.floor(y1)),int(np.ceil(x2)),int(np.ceil(y2))],
                'status':status,'score':round(r['score'],6),'reason':reason,'backend':'yolov8n_hardhat_'+self.backend,
                'model_class':['hardhat','no-hardhat'][r['class_id']],'face_bbox':None})
        return detections,{'preprocess':(prepared-started)*1000,'model':(inferred-prepared)*1000,
                           'postprocess':(time.perf_counter()-inferred)*1000,'total':(time.perf_counter()-started)*1000}

    def process_frame(self,frame):
        detections,self.last_timings=self.predict(frame)
        annotated=frame.copy()
        for d in detections:
            x1,y1,x2,y2=d['bbox']; color={'helmet':(0,190,0),'no_helmet':(0,0,230),'unknown':(0,180,255)}[d['status']]
            cv2.rectangle(annotated,(x1,y1),(x2-1,y2-1),color,2)
            cv2.putText(annotated,d['status']+' %.2f'%d['score'],(x1,max(15,y1-4)),0,.5,color,1,cv2.LINE_AA)
        return annotated,detections

def iou(a,b):
    v=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-v
    return v/area if area>0 else 0.

_default=None
def configure(**kwargs):
    global _default
    _default=HelmetDetector(**kwargs);return _default
def process_frame(frame_bgr):
    global _default
    if _default is None:_default=HelmetDetector()
    return _default.process_frame(frame_bgr)
