"""Face-first pipeline. One full-color helmet inference per frame with faces."""
import time,threading
import cv2
from face_detection import FaceDetector
from face_geometry import head_box

def overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def associate(faces,heads,width,height):
    edges=[]
    for fi,f in enumerate(faces):
        fw,fh=f[2]-f[0],f[3]-f[1];roi=head_box(f,width,height)
        for hi,h in enumerate(heads):
            b=h['bbox'];cx,cy=(b[0]+b[2])/2,(b[1]+b[3])/2
            dx=abs(cx-(f[0]+f[2])/2)/fw
            if dx>.65 or not f[1]-1.2*fh<=cy<=f[1]+.7*fh:continue
            coverage=overlap(roi,b)/max(1,(b[2]-b[0])*(b[3]-b[1]))
            if coverage<.5:continue
            edges.append((.8*coverage+.2*(1-dx/.65),fi,hi))
    # Reject ambiguity on both sides, then enforce one-to-one matching.
    ambiguous_faces=set();ambiguous_heads=set()
    for fi in range(len(faces)):
        candidates=sorted((s for s,f,h in edges if f==fi),reverse=True)
        if len(candidates)>1 and candidates[0]-candidates[1]<.15:ambiguous_faces.add(fi)
    for hi in range(len(heads)):
        candidates=sorted((s for s,f,h in edges if h==hi),reverse=True)
        if len(candidates)>1 and candidates[0]-candidates[1]<.15:ambiguous_heads.add(hi)
    ambiguous_faces.update(fi for _,fi,hi in edges if hi in ambiguous_heads)
    matches={};used=set()
    for score,fi,hi in sorted(edges,reverse=True):
        if fi in ambiguous_faces or hi in ambiguous_heads:continue
        if fi not in matches and hi not in used:matches[fi]=(hi,score);used.add(hi)
    rows=[]
    for fi,face in enumerate(faces):
        row={'face_index':fi,'face_bbox':list(face),'face_detected':True,'bbox':head_box(face,width,height),
             'helmet_status':'unknown','status':'unknown','score':None,'helmet_score':None,
             'association_score':None,'helmet_bbox':None,'reason':'no_associated_head'}
        if fi in ambiguous_faces or any(f==fi and h in ambiguous_heads for _,f,h in edges):row['reason']='ambiguous_association'
        if fi in matches:
            hi,score=matches[fi];h=heads[hi]
            row.update(helmet_status=h['status'],status=h['status'],helmet_score=h['score'],
                       association_score=score,helmet_bbox=h['bbox'],reason=h['reason'],helmet_detection_index=hi)
        rows.append(row)
    return rows,[dict(h,association='unassociated') for hi,h in enumerate(heads) if hi not in used]

class CombinedPipeline:
    def __init__(self,face_detector=None,helmet_detector=None,helmet_profile='ncnn640',execution_backend='PC'):
        if execution_backend not in ('PC','ZYNQ_ARM'):raise ValueError('CPU execution backend required')
        self.face=face_detector or FaceDetector()  # original quality profile: 640/1.1
        if helmet_detector is None:
            from helmet_backend import create_detector
            helmet_detector=create_detector(helmet_profile)
        self.helmet=helmet_detector;self.location=execution_backend
        self.backend='face_haar640+helmet_'+str(getattr(self.helmet,'backend','injected'))
        self.lock=threading.Lock()

    def run(self,frame_bgr,gray_image=None,original_shape=None,gray_execution_backend='EXTERNAL_UNVERIFIED'):
        with self.lock:return self._run(frame_bgr,gray_image,original_shape,gray_execution_backend)

    def _run(self,frame,gray,original_shape,gray_backend):
        start=time.perf_counter();self.face.validate_frame(frame);h,w=frame.shape[:2]
        if gray is None:
            if original_shape is not None:raise ValueError('original_shape requires external gray')
            faces=self.face.detect_faces(frame)
        else:
            self.face.validate_gray(gray)
            if original_shape is None and gray.shape!=(h,w):raise ValueError('Full-size gray must match original BGR')
            if original_shape is not None and tuple(original_shape)!=(h,w):raise ValueError('original_shape must match BGR')
            faces=self.face.detect_faces_gray(gray,original_shape)
        face_ms=(time.perf_counter()-start)*1000
        stage=time.perf_counter();heads=[];helmet_times={}
        if faces:heads,helmet_times=self.helmet.predict(frame)
        helmet_ms=(time.perf_counter()-stage)*1000 if faces else 0.
        stage=time.perf_counter();rows,unmatched=associate(faces,heads,w,h)
        association_ms=(time.perf_counter()-stage)*1000
        stage=time.perf_counter();out=frame.copy()
        for row in rows:
            b=row['face_bbox'];color={'helmet':(0,190,0),'no_helmet':(0,0,230),'unknown':(0,180,255)}[row['status']]
            cv2.rectangle(out,tuple(b[:2]),(b[2]-1,b[3]-1),color,2)
            cv2.putText(out,'face: '+row['status'],(b[0],max(15,b[1]-4)),0,.45,color,1,cv2.LINE_AA)
            if row['helmet_bbox']:
                hb=row['helmet_bbox'];cv2.rectangle(out,tuple(hb[:2]),(hb[2]-1,hb[3]-1),(255,180,0),1)
        for head in unmatched:
            b=head['bbox'];cv2.rectangle(out,tuple(b[:2]),(b[2]-1,b[3]-1),(180,180,180),1)
            cv2.putText(out,'unassigned head',(b[0],max(15,b[1]-3)),0,.4,(180,180,180),1)
        render_ms=(time.perf_counter()-stage)*1000
        record={'schema_version':'face_helmet_v2','mode':'face_then_helmet','face_count':len(faces),
            'face_detected':bool(faces),'face_backend':self.face.backend,'detections':rows,
            'helmet_detections':heads,'unassociated_heads':unmatched,
            'helmet_stage':'executed' if faces else 'skipped_no_faces',
            'observation_scope':'detected_faces_only_not_all_workers','processing_ms':(time.perf_counter()-start)*1000,
            'timings_ms':{'face':face_ms,'helmet':helmet_ms,'association':association_ms,'render':render_ms,'helmet_detail':helmet_times},
            'execution_backend':{'face':self.location,'helmet':self.location if faces else 'NOT_EXECUTED',
                                 'gray':self.location if gray is None else gray_backend},'external_gray':gray is not None}
        self.last_record=record;self.last_timings=record['timings_ms']
        return out,record

    def process_frame(self,frame_bgr):
        """Legacy A preview contract: image and per-face detections list."""
        image,record=self.run(frame_bgr);return image,record['detections']
