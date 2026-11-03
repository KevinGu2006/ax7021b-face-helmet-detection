"""Live HDMI preview with an explicitly historical helmet result inset.
Reuses C/A verified async owners; no old head boxes on the live image.
"""
import pathlib,sys,time,json,os,threading,argparse
ROOT=pathlib.Path(__file__).resolve().parent
RAM=pathlib.Path('/dev/shm/a_helmet_preview');RAM.mkdir(exist_ok=True)
sys.path.insert(0,'/home/xilinx/A_compat_RC1/01_Async_Live')
sys.path.insert(0,os.environ.get('B_ALGORITHM_DIR',str(ROOT.parent)))
import camera_hdmi_async as app
from async_pipeline import DetectionOutput
lock=threading.Lock();latest=None;count=0;preview_count=0;preview_start=None;last_save=0
state={'phase':'starting','pid':os.getpid(),'helmet_completed':0,'helmet_on':'ZYNQ_ARM','pl_gray_used':False}
def save():
 with lock:data=dict(state)
 temp=RAM/'state.tmp';temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(RAM/'state.json')
class HelmetDetector:
 def __init__(self,overlay,backend):
  from raw_head_adapter import create_detector
  self.detector=create_detector(execution_backend="ZYNQ_ARM");self.provider=None;self.closed=False;self.last_diagnostic=None
 def process(self,packet):
  global latest,count
  t=time.perf_counter()
  with lock:state['inference_started_at']=time.monotonic();state['inference_source_id']=packet.frame_id
  annotated,detections=self.detector.process_frame(packet.image)
  record=dict(self.detector.last_record,source_frame_id=packet.frame_id)
  annotated.setflags(write=False)
  with lock:
   count+=1;latest={'image':annotated,'captured_at':packet.captured_at,'completed_at':time.perf_counter(),'detections':detections,'frame_id':packet.frame_id,'model_ms':(time.perf_counter()-t)*1000}
   state.update(latest_face_count=record["face_count"],latest_record=record,helmet_completed=count,latest_detections=detections,latest_source_frame_id=packet.frame_id,latest_capture_monotonic=packet.captured_at,model_ms=latest['model_ms'])
  # Generic engine counters represent helmet jobs. Do not mislabel model time as Haar or PL.
  return DetectionOutput((),0.,0.,0.,0.,0.)
 def close(self):self.closed=True
class Renderer:
 def __init__(self,cv):self.cv=cv
 def __call__(self,packet,result,box_state,result_age_ms):
  global preview_count,preview_start,last_save
  now=time.perf_counter();preview_count+=1
  if preview_start is None:preview_start=now
  fps=(preview_count-1)/max(.001,now-preview_start)
  canvas=packet.image.copy()
  with lock:snapshot=latest
  self.cv.rectangle(canvas,(0,0),(800,42),(0,0,0),-1)
  self.cv.putText(canvas,'LIVE PREVIEW | Face + helmet in background',(10,27),0,.62,(255,255,255),1,self.cv.LINE_AA)
  # The inset's boxes are drawn ONLY on that same historical source image.
  self.cv.rectangle(canvas,(458,300),(799,599),(15,15,15),-1)
  if snapshot is None:
   self.cv.putText(canvas,'WAITING FOR FIRST RESULT',(470,340),0,.5,(0,220,255),1)
   self.cv.putText(canvas,'Waiting for face + helmet result',(470,370),0,.5,(255,255,255),1)
  else:
   thumb=self.cv.resize(snapshot['image'],(320,240));canvas[354:594,470:790]=thumb
   age=now-snapshot['captured_at']
   self.cv.putText(canvas,'RESULT SNAPSHOT - NOT LIVE',(470,320),0,.45,(0,220,255),1)
   self.cv.putText(canvas,'Captured %.1fs ago'%age,(470,343),0,.48,(0,220,255),1)
  if now-last_save>=1:
   with lock:
    state.update(phase='running',pid=os.getpid(),preview_frames=preview_count,preview_fps=fps,preview_heartbeat_monotonic=time.monotonic(),last_preview_source_id=packet.frame_id)
    if snapshot is not None:state['snapshot_age_seconds']=now-snapshot['captured_at']
   save();last_save=now
  return canvas
OriginalEngine=app.AsyncEngine
class Engine(OriginalEngine):
 def __init__(self,**kwargs):
  kwargs['join_timeout']=90 # Allow an in-progress CPU model call to finish before exit.
  super().__init__(**kwargs)
 def run(self):
  def watch():
   while not self.stop_event.wait(.2):
    if (RAM/'stop.request').exists():self.request_stop();break
  threading.Thread(target=watch,daemon=True).start()
  return super().run()
app.BoardDetector=HelmetDetector;app.PreviewRenderer=Renderer;app.AsyncEngine=Engine
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--max-seconds',type=int,default=0);args=p.parse_args()
 save()
 try:
  argv=['--backend','cpu','--camera','0','--log-root',str(ROOT/'run_logs'),'--stats-every-seconds','5']
  if args.max_seconds:argv+=['--max-seconds',str(args.max_seconds)]
  code=app.main(argv)
  with lock:state.update(phase='stopped' if code==0 else 'failed',exit_code=code)
  save();sys.exit(code)
 except Exception:
  import traceback
  with lock:state.update(phase='failed',error=traceback.format_exc())
  save();raise
