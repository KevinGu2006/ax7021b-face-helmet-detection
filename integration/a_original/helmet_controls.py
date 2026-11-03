import pathlib,json,subprocess,fcntl
ROOT=pathlib.Path(__file__).resolve().parent;RAM=pathlib.Path('/dev/shm/a_helmet_preview')
def status():
 p=RAM/'state.json';r=json.loads(p.read_text()) if p.exists() else {'phase':'not_started'}
 if (RAM/'stop.request').exists() and r.get('phase') in ['running','starting']:r['phase']='stopping'
 return r
def start(seconds=0):
 RAM.mkdir(exist_ok=True)
 with open(RAM/'control.lock','w') as guard:
  fcntl.flock(guard,fcntl.LOCK_EX)
  r=status()
  launch=RAM/'launch.json'
  if launch.exists():
   pid=json.loads(launch.read_text()).get('pid');proc=pathlib.Path('/proc/%s/cmdline'%pid)
   if pid and proc.exists() and b'helmet_preview.py' in proc.read_bytes():return {'already_running':True,**r}
  pid=r.get('pid');proc=pathlib.Path('/proc/%s/cmdline'%pid)
  if pid and proc.exists() and b'helmet_preview.py' in proc.read_bytes():return {'already_running':True,**r}
  with open('/home/xilinx/A_hdmi_integration_20261029/controller.lock','a') as owner:
   try:fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:raise RuntimeError('另一显示程序仍在运行，请先正常停止')
  try:(RAM/'stop.request').unlink()
  except FileNotFoundError:pass
  with open(RAM/'console.log','w') as log:
   p=subprocess.Popen(['/usr/local/bin/pynq-a-python2025',str(ROOT/'helmet_preview.py'),'--max-seconds',str(seconds)],cwd='/tmp',stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  (RAM/'launch.json').write_text(json.dumps({'pid':p.pid}))
  return {'phase':'launching','pid':p.pid}
def stop():
 RAM.mkdir(exist_ok=True);(RAM/'stop.request').touch();return '已请求停止，请等待当前模型计算结束，可能需要半分钟以上。'
