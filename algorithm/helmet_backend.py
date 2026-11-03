"""Head-model factory for NCNN640 and OpenCV raw-head compatibility profiles."""
from pathlib import Path
import json,hashlib,os
import numpy as np
from helmet_algorithm import HelmetDetector
ROOT=Path(__file__).resolve().parent
NAMES=['/model.22/Concat_output_0','/model.22/Concat_1_output_0','/model.22/Concat_2_output_0']
class RawNet:
    def __init__(self,net,size):
        self.net=net;self.count=sum((size//s)**2 for s in (8,16,32))
        anchors=[];strides=[]
        for stride in (8,16,32):
            side=size//stride;y,x=np.meshgrid(np.arange(side,dtype=np.float32),np.arange(side,dtype=np.float32),indexing='ij')
            anchors.append(np.stack([x+.5,y+.5]).reshape(1,2,-1));strides.append(np.full((1,1,side*side),stride,np.float32))
        self.anchor=np.concatenate(anchors,axis=2);self.stride=np.concatenate(strides,axis=2)
        self.projection=np.arange(16,dtype=np.float32).reshape(1,1,16,1)
    def setInput(self,x):self.net.setInput(x)
    def forward(self):
        raw=np.concatenate([h.reshape(1,66,-1) for h in self.net.forward(NAMES)],axis=2)
        logits=raw[:,:64].reshape(1,4,16,self.count);logits=logits-logits.max(axis=2,keepdims=True)
        p=np.exp(logits);p/=p.sum(axis=2,keepdims=True);dist=(p*self.projection).sum(axis=2)
        lo=self.anchor-dist[:,:2];hi=self.anchor+dist[:,2:]
        scores=1/(1+np.exp(-np.clip(raw[:,64:],-80,80)))
        return np.concatenate([((lo+hi)*.5)*self.stride,(hi-lo)*self.stride,scores],axis=1)
def create_detector(profile=None):
    profile=profile or os.environ.get('HELMET_PROFILE','board640')
    if profile=='ncnn640':
        cfg=json.loads((ROOT/'profiles.json').read_text())[profile]
        for name,digest in cfg['files'].items():
            if hashlib.sha256((ROOT/cfg['model']/name).read_bytes()).hexdigest()!=digest:raise ValueError('NCNN checksum mismatch')
        return HelmetDetector(model=ROOT/cfg['model'],backend='ncnn',input_size=640,confidence=.4)
    cfg=json.loads((ROOT/'profiles.json').read_text())[profile]
    path=ROOT/cfg['model']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=cfg['sha256']:raise ValueError('Raw model checksum mismatch')
    detector=HelmetDetector(model=path,backend='opencv',input_size=cfg['input_size'],confidence=.4)
    detector.net=RawNet(detector.net,cfg['input_size']);detector.backend='opencv_raw_heads'
    return detector
