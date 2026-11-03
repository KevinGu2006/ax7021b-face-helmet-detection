"""Local CPU-only NCNN backend. No frame leaves the process."""
from pathlib import Path
import sys
import numpy as np
class NcnnNet:
    def __init__(self,folder,threads=1):
        vendor=Path(__file__).resolve().parent/'board_vendor'
        if vendor.is_dir():sys.path.insert(0,str(vendor))
        import ncnn
        self.ncnn=ncnn;self.net=ncnn.Net()
        self.net.opt.use_vulkan_compute=False;self.net.opt.num_threads=threads
        self.net.opt.use_fp16_storage=False;self.net.opt.use_fp16_arithmetic=False
        folder=Path(folder)
        if self.net.load_param(str(folder/'model.ncnn.param'))!=0:raise RuntimeError('NCNN param load failed')
        if self.net.load_model(str(folder/'model.ncnn.bin'))!=0:raise RuntimeError('NCNN weights load failed')
    def setInput(self,tensor):self.tensor=np.ascontiguousarray(tensor[0])
    def forward(self):
        with self.net.create_extractor() as ex:
            if ex.input('in0',self.ncnn.Mat(self.tensor).clone())!=0:raise RuntimeError('NCNN input failed')
            code,result=ex.extract('out0')
            if code!=0:raise RuntimeError('NCNN extraction failed')
            out=np.array(result).copy()
        if out.ndim==2 and out.shape[1]==6:out=out.T
        return out[None]
