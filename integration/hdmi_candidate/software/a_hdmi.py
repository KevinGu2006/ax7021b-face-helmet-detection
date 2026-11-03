"""AX7021B HDMI candidate integration. Clock/VTC port from bundled Xilinx PYNQ drivers.
See reference_video_display.[ch] for original license and algorithm provenance.
No hardware operations on import. One controller process, retain active DMA buffers.
"""
import pathlib,json,time,os,ctypes,hashlib
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent

def wait_for(fn,timeout=3):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  if fn():return
  time.sleep(.01)
 raise TimeoutError('Hardware status did not reach expected state')

def clock_plan(pixel_mhz):
 target=pixel_mhz*5;best=None
 for d in range(1,11):
  for m in range(6*d,min(12*d,64)+1):
   o=int(100/d/target*m+.5)
   if not 1<=o<=128:continue
   actual=100/d*m/o
   item=(abs(actual-target),d,m,o,actual/5)
   if best is None or item[0]<best[0]:best=item
 _,d,m,o,actual=best
 def div(n):
  if n==1:return 0x1041
  hi=n//2;return ((1<<13) if n%2 else 0)|((n-hi)&63)|((hi<<6)&0xfc0)
 def count(n):
  value=div(n);return (value&0xfff)|((value<<10)&0xc00000)
 tab=json.loads((ROOT/'clock_tables.json').read_text());lock=tab['lock_lookup'][m-1]
 return {'pixel_requested_mhz':pixel_mhz,'pixel_actual_mhz':actual,'main_div':d,'fb_mult':m,'out_div':o,'registers':[count(o),count(m),0,div(d),lock&0xffffffff,((lock>>32)&255)|((tab['filter_lookup_low'][m-1]<<16)&0x3ff0000)]}

def configure_clock(mmio):
 plan=clock_plan(40.0)
 for off,value in zip([8,12,16,20,24,28],plan['registers']):mmio.write(off,value)
 mmio.write(0,0);wait_for(lambda:not mmio.read(4)&1)
 mmio.write(0,1);wait_for(lambda:bool(mmio.read(4)&1))
 plan['status']=int(mmio.read(4));return plan

def configure_vtc(v):
 # XVtc_ConvTiming2Signal: progressive 800x600, H+ V+, sync start Vactive+front-1.
 v.write(0,2)
 for off,value in {0x60:800|(600<<16),0x68:0,0x6c:0x7f,0x70:1056,0x74:628|(628<<16),0x78:840|(968<<16),0x7c:800|(800<<16),0x80:600|(604<<16),0x84:840|(840<<16),0x88:800|(800<<16),0x8c:600|(604<<16),0x90:840|(840<<16),0x94:600<<16}.items():v.write(off,value)
 v.write(0,0x07f7ef07) # all generator source selections except interlace, enable core+generator+update
 return {hex(off):int(v.read(off)) for off in [0,4,8,0x10,0x60,0x64,0x68,0x6c,0x70,0x74,0x78,0x80]}

class I2C:
 def __enter__(self):
  self.fd=os.open('/dev/i2c-0',os.O_RDWR);return self
 def __exit__(self,*args):os.close(self.fd)
 def write(self,address,register,value):
  import fcntl
  fcntl.ioctl(self.fd,0x703,address)
  if os.write(self.fd,bytes([register,value]))!=2:raise IOError('Short I2C write')
 def read(self,address,register):
  # Combined I2C_RDWR messages, keeps repeated-start transaction atomic.
  class Msg(ctypes.Structure):_fields_=[('addr',ctypes.c_uint16),('flags',ctypes.c_uint16),('len',ctypes.c_uint16),('buf',ctypes.POINTER(ctypes.c_uint8))]
  class Rdwr(ctypes.Structure):_fields_=[('msgs',ctypes.POINTER(Msg)),('nmsgs',ctypes.c_uint32)]
  tx=(ctypes.c_uint8*1)(register);rx=(ctypes.c_uint8*1)();msgs=(Msg*2)(Msg(address,0,1,tx),Msg(address,1,1,rx));args=Rdwr(msgs,2)
  libc=ctypes.CDLL(None,use_errno=True)
  if libc.ioctl(self.fd,0x707,ctypes.byref(args))<0:raise OSError(ctypes.get_errno(),'I2C_RDWR failed')
  return int(rx[0])

def slcr_snapshot():
 from pynq import MMIO
 m=MMIO(0xf8000000,0x1000)
 offsets=[0x100,0x104,0x108,0x120,0x124,0x12c,0x140,0x170,0x180,0x190,0x1a0,0x22c]+list(range(0x700,0x800,4))
 return {hex(o):int(m.read(o)) for o in offsets}

def hardware_preflight():
 # Drivers/sysfs map must match the known PS IIC0; do not probe arbitrary I2C addresses.
 p=pathlib.Path('/sys/bus/i2c/devices/i2c-0/name')
 if not p.exists() or 'e0004000' not in p.read_text():raise RuntimeError('Unexpected IIC0 mapping')
 dt=pathlib.Path('/proc/device-tree/amba/i2c@e0004000/status')
 if dt.read_bytes().rstrip(b'\0')!=b'okay':raise RuntimeError('IIC0 disabled')
 for base in ['43000000','43c00000','43c10000','41200000']:
  for node in pathlib.Path('/sys/bus/platform/devices').glob('*'+base+'*'):
   if (node/'driver').exists():raise RuntimeError('Hardware already owned by driver '+str(node))
 for node in pathlib.Path('/sys/bus/i2c/devices').glob('0-00*'):
  if node.name in ['0-0039','0-003d'] and (node/'driver').exists():raise RuntimeError('SiI9134 owned by kernel')
 return {'iic0':p.read_text().strip(),'display_kernel_owner_found':False,'slcr_before':slcr_snapshot()}

class Display:
 def __init__(self):
  from pynq import Overlay,MMIO,Clocks,allocate
  self.buffers=[];self.vdma=None;self.closed=False
  self.preflight=hardware_preflight()
  Clocks._instance._ref_clk_mhz=33.333333
  self.overlay=Overlay(str(ROOT/'HDMI_CANDIDATE.bit'))
  expected={'axi_dma_0':0x40400000,'axi_vdma_0':0x43000000,'v_tc_0':0x43c00000,'axi_dynclk_0':0x43c10000,'hdmi_reset_gpio':0x41200000}
  for name,addr in expected.items():
   if self.overlay.ip_dict[name]['phys_addr']!=addr:raise RuntimeError('Unexpected IP mapping '+name)
  self.preflight['slcr_after']=slcr_snapshot()
  # Overlay may change only PL clock registers, not CPU/DDR PLL or pin mux.
  for key in self.preflight['slcr_before']:
   if int(key,16) in [0x170,0x180,0x190,0x1a0]:continue
   if self.preflight['slcr_before'][key]!=self.preflight['slcr_after'][key]:raise RuntimeError('Unexpected PS configuration change '+key)
  self.preflight['fclk0_mhz']=Clocks.fclk0_mhz
  self.vdma=MMIO(0x43000000,0x10000);self.vtc=MMIO(0x43c00000,0x10000);self.clock=MMIO(0x43c10000,0x10000);self.gpio=MMIO(0x41200000,0x10000)
  self.clock_result=configure_clock(self.clock)
  self.gpio.write(4,0);self.gpio.write(0,0);time.sleep(.06);self.gpio.write(0,1);time.sleep(.06)
  with I2C() as i2c:
   i2c.write(0x39,8,0x35);i2c.write(0x3d,0x2f,0)
   self.i2c_result={'0x39:0x08':i2c.read(0x39,8),'0x3d:0x2f':i2c.read(0x3d,0x2f)}
  self.vtc_result=configure_vtc(self.vtc)
  from pynq_vdma_mm2s import start_static,plan_rgb888
  for i in range(3):
   b=allocate((600,800,3),dtype=np.uint8);self.buffers.append(b);b[:]=0;b.flush()
  self.plan=plan_rgb888(800,600,2400,[int(b.physical_address) for b in self.buffers])
  self.started=start_static(self.vdma,self.plan)
  time.sleep(.25)
  self.vdma.write(0x28,self.vdma.read(0x28)&~31)
  self.vdma.write(0,self.vdma.read(0)&~2)
  wait_for(lambda:((self.vdma.read(0x28)>>16)&31)==0)
 def snapshot(self):
  from pynq_vdma_mm2s import status
  return {'vdma':status(self.vdma),'park_pointer':int(self.vdma.read(0x28)),'dynclk_status':int(self.clock.read(4)),'vtc_control':int(self.vtc.read(0)),'vtc_status':int(self.vtc.read(4)),'vtc_error':int(self.vtc.read(8)),'frame_addresses':[int(b.physical_address) for b in self.buffers]}
 def show(self,image):
  import cv2
  if image.shape!=(600,800,3):image=cv2.resize(image,(800,600))
  current=(self.vdma.read(0x28)>>16)&31
  target=1 if current==0 else 0
  b=self.buffers[target];b[:]=image;b.flush()
  self.vdma.write(0x28,(self.vdma.read(0x28)&~31)|target)
  wait_for(lambda:((self.vdma.read(0x28)>>16)&31)==target)
  self.last_frame_store=target
 def stop(self):
  if self.vdma:
   self.vdma.write(0,0);wait_for(lambda:bool(self.vdma.read(4)&1))
  for b in self.buffers:b.freebuffer()
  self.buffers=[];self.closed=True

def colorbars():
 image=np.zeros((600,800,3),np.uint8)
 for i,c in enumerate([(255,255,255),(0,255,255),(255,255,0),(0,255,0),(255,0,255),(0,0,255),(255,0,0),(0,0,0)]):image[:,i*100:(i+1)*100]=c
 return image


