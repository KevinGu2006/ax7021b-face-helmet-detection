"""Capture/detect using the already-loaded combined design, then request display update."""
import pathlib,sys,json,time,subprocess,argparse,fcntl,os
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,'/home/xilinx/A_C_gray_hardware_20261028')
sys.path.insert(0,'/home/xilinx/A_C_gray_integration_20261028')
sys.path.insert(0,'/home/xilinx/A_B_integration_20261028')
def main():
 p=argparse.ArgumentParser();p.add_argument('--image');p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
 lock=open(ROOT/'pipeline.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 status=json.loads((ROOT/'status.json').read_text())
 if status['phase'] in ['starting','failed','stopped','black_frame']:raise RuntimeError('Wait for combined design gray regression / display readiness')
 if len(status.get('gray_regression',[]))!=31:raise RuntimeError('Wait for gray regression to finish')
 if status.get('heartbeat_monotonic',0)<time.monotonic()-15:raise RuntimeError('HDMI controller heartbeat stale')
 if not a.image:
  r=subprocess.run([sys.executable,'/home/xilinx/A_camera_test_20261029/camera_capture_test.py'],capture_output=True,text=True,timeout=45)
  if r.returncode:raise RuntimeError(r.stdout+r.stderr)
  image='/home/xilinx/A_camera_test_20261029/camera_frame.png'
 else:image=a.image
 import cv2
 from pynq import Overlay
 from a_gray_dma_fast import ReusableGrayDMA
 from pipeline_api import FacePipeline
 from pl_integration_example import process_with_gray_provider
 overlay=Overlay(str(ROOT/'HDMI_CANDIDATE.bit'),download=False)
 if not overlay.is_loaded():raise RuntimeError('Combined HDMI Overlay is no longer loaded. Do not reload old camera demo.')
 frame=cv2.imread(image)
 if frame is None:raise ValueError('Cannot read input')
 provider=ReusableGrayDMA(overlay,'axi_dma_0',timeout=5)
 try:
  annotated,record=process_with_gray_provider(frame,provider,'ZYNQ_PL',FacePipeline(execution_backend='ZYNQ_ARM'))
 finally:
  if not provider.poisoned or provider.last_diagnostic.get('channels_halted'):provider.close()
  else:
   (ROOT/'unsafe_pipeline.json').write_text(json.dumps({'error':'Cannot stop gray DMA; retaining buffers','pid':os.getpid()}))
   while True:time.sleep(5)
 path=ROOT/'camera_annotated.png'
 if not cv2.imwrite(str(path),annotated):raise IOError('Save image failed')
 record.update(input_file=image,HDMI_verified=False,display_observation_pending=True)
 if not a.prepare_only:
  cmd=ROOT/'command.tmp';cmd.write_text(json.dumps({'action':'image','path':str(path)}));cmd.replace(ROOT/'command.json')
  end=time.monotonic()+10
  while time.monotonic()<end:
   status=json.loads((ROOT/'status.json').read_text())
   if status['phase']=='failed':raise RuntimeError(status.get('error','HDMI controller failed'))
   if status['phase']=='image_running' and status.get('displayed_image')==str(path):break
   time.sleep(.1)
  else:raise TimeoutError('HDMI frame update confirmation timed out')
  record['display_registers']=status['snapshot']
 (ROOT/'camera_record.json').write_text(json.dumps(record,indent=2))
 print(json.dumps({'face_count':record['face_count'],'processing_ms':record['processing_ms'],'gray_backend':record['execution_backend']['gray'],'display_update_requested':not a.prepare_only,'HDMI_visually_verified':False,'result':str(path)}))
if __name__=='__main__':main()
