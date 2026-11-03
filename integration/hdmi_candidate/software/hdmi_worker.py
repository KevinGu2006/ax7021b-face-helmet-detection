import pathlib,sys,time,json,traceback,os,fcntl
ROOT=pathlib.Path(__file__).parent
sys.path.insert(0,'/home/xilinx/A_C_gray_hardware_20261028')
sys.path.insert(0,'/home/xilinx/A_C_gray_integration_20261028')
sys.path.insert(0,'/home/xilinx/A_B_integration_20261028')
from a_hdmi import Display,colorbars
lock=open(ROOT/'controller.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
r={'phase':'starting','display_observed_by_user':False,'HDMI_verified':False,'pid':os.getpid()}
def save():
 p=ROOT/'status.tmp';p.write_text(json.dumps(r,indent=2));p.replace(ROOT/'status.json')
save();display=Display.__new__(Display)
try:
 Display.__init__(display)
 r.update(phase='black_frame',preflight=display.preflight,clock=display.clock_result,i2c=display.i2c_result,snapshot=display.snapshot());save();time.sleep(3)
 display.show(colorbars());r.update(phase='colorbars_running',snapshot=display.snapshot());save()
 from a_gray_dma_fast import ReusableGrayDMA
 from a_gray_dma import compare_gray
 import numpy as np
 vectors=pathlib.Path('/home/xilinx/A_C_gray_integration_20261028/vectors');provider=ReusableGrayDMA(display.overlay,'axi_dma_0',timeout=5)
 r['gray_regression']=[]
 try:
  for case in json.loads((vectors/'manifest.json').read_text()):
   p=vectors/case['name'];h,w=case['height'],case['width']
   bgr=np.fromfile(str(p/'input_bgr24.bin'),np.uint8).reshape(h,w,3);ref=np.fromfile(str(p/'expected_gray.bin'),np.uint8).reshape(h,w)
   cmp=compare_gray(provider(bgr),ref);r['gray_regression'].append({'name':case['name'],'pixels':h*w,'comparison':cmp});save()
   if not cmp['passed']:raise RuntimeError('Gray mismatch '+case['name'])
 finally:
  if not provider.poisoned or provider.last_diagnostic.get('channels_halted'):provider.close()
  else:raise RuntimeError('Gray DMA unsafe; retain process and buffers')
 r.update(phase='colorbars_and_gray_regression_passed',snapshot=display.snapshot());save()
 while True:
  cmdfile=ROOT/'command.json'
  if cmdfile.exists():
   cmd=json.loads(cmdfile.read_text());cmdfile.unlink()
   if cmd['action']=='stop':
    display.stop();r['phase']='stopped';r['snapshot']=display.snapshot();save();break
   elif cmd['action']=='bars':display.show(colorbars());r['phase']='colorbars_running'
   elif cmd['action']=='image':
    import cv2
    img=cv2.imread(cmd['path'])
    if img is None:raise ValueError('Cannot read image')
    display.show(img);r.update(phase='image_running',displayed_image=cmd['path'])
   r['snapshot']=display.snapshot();save()
  r['snapshot']=display.snapshot();r['heartbeat_monotonic']=time.monotonic();save()
  if r['snapshot']['vdma']['error']:raise RuntimeError('VDMA error')
  time.sleep(1)
except Exception:
 r.update(phase='failed',error=traceback.format_exc());save();print(r['error'],flush=True)
 try:
  display.stop();r['cleanup']='VDMA halted, display buffers released';save()
 except Exception:
  r['cleanup']='Cannot confirm VDMA halt. Retaining process/buffers.';save()
  while True:time.sleep(5)
