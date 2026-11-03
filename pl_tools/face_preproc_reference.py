"""Versioned BGR->gray integer reference and reproducible RTL vectors."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

VERSION = "bgr_gray_q15_v1"


def validate_bgr(image):
    if not isinstance(image,np.ndarray) or image.dtype != np.uint8:
        raise TypeError("Expected numpy uint8")
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1:
        raise ValueError("Expected nonempty HxWx3 BGR")


def gray_pixel(b, g, r):
    if any(isinstance(x,bool) or not isinstance(x,(int,np.integer)) or not 0 <= x <= 255
           for x in (b,g,r)):
        raise ValueError("Channels must be integers in [0,255]")
    return (3735*int(b)+19235*int(g)+9798*int(r)+16384) >> 15


def bgr_to_gray_fixed(image):
    validate_bgr(image)
    wide = image.astype(np.uint32)
    return ((wide[:,:,0]*3735+wide[:,:,1]*19235+wide[:,:,2]*9798+16384) >> 15).astype(np.uint8)


def compare_gray(expected, actual, tolerance=0):
    if expected.dtype != np.uint8 or actual.dtype != np.uint8:
        raise TypeError("Comparison requires uint8 arrays")
    if expected.shape != actual.shape or expected.ndim != 2:
        raise ValueError("Gray shape mismatch")
    delta = np.abs(expected.astype(np.int16)-actual.astype(np.int16))
    return {"pixels":int(delta.size),"max_abs_error":int(delta.max()),
            "mean_abs_error":float(delta.mean()),"different_pixels":int((delta>0).sum()),
            "outside_tolerance":int((delta>tolerance).sum()),
            "tolerance":tolerance,"passed":bool((delta<=tolerance).all())}


def generated_cases():
    rng = np.random.default_rng(20261027)
    colors = [(0,0,0),(255,255,255),(255,0,0),(0,255,0),(0,0,255),
              (255,255,0),(255,0,255),(0,255,255),(1,1,1),(254,254,254),
              (17,85,203),(253,2,129)]
    for i,color in enumerate(colors):
        yield "solid_{:02d}".format(i),np.full((3,5,3),color,np.uint8),"solid BGR "+str(color)
    for channel in range(3):
        image = np.zeros((3,256,3),np.uint8)
        image[:,:,channel] = np.arange(256,dtype=np.uint8)
        yield "gradient_"+"bgr"[channel],image,"single-channel 0..255"
    gray = np.broadcast_to(np.arange(256,dtype=np.uint8)[None,:,None],(3,256,3)).copy()
    yield "all_gray_levels",gray,"all 256 achromatic levels"
    checker = (np.indices((7,9)).sum(axis=0)%2*255).astype(np.uint8)
    yield "checker_odd",np.repeat(checker[:,:,None],3,axis=2),"odd width; row/packet boundary"
    for h,w in [(1,1),(1,17),(17,1),(3,7),(31,33),(60,80),(241,319),(240,320),(480,640)]:
        yield "random_{}x{}".format(w,h),rng.integers(0,256,(h,w,3),dtype=np.uint8),"seed 20261027"


def generate(output, images=None):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    cases = list(generated_cases())
    if images:
        def read_image(path):
            image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError('Cannot decode image: '+str(path))
            return image
        for name in ("lena.jpg","messi5.jpg","addams-family.png","audrybt1.png","bttf301.png"):
            path = Path(images)/name
            if path.exists():
                cases.append(("photo_"+path.stem,read_image(path),"real photo; see test_images/sources.json"))
    rows = []
    for name,bgr,note in cases:
        folder = output/name
        folder.mkdir(exist_ok=True)
        fixed = bgr_to_gray_fixed(bgr)
        opencv = cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
        bgr.tofile(str(folder/"input_bgr24.bin"))
        axis = np.zeros((*bgr.shape[:2],4),np.uint8)
        axis[:,:,:3] = bgr
        axis.tofile(str(folder/"input_axis32.bin"))
        words = axis.view("<u4").ravel()
        (folder/"input_axis32.mem").write_text("".join("{:08x}\n".format(int(x)) for x in words),encoding="ascii")
        fixed.tofile(str(folder/"expected_gray.bin"))
        (folder/"expected_gray.mem").write_text("".join("{:02x}\n".format(int(x)) for x in fixed.ravel()),encoding="ascii")
        cv2.imwrite(str(folder/"expected_gray.png"),fixed)
        cv2.imwrite(str(folder/"opencv_gray.png"),opencv)
        checks = compare_gray(opencv,fixed,1)
        files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}
        rows.append({"name":name,"height":bgr.shape[0],"width":bgr.shape[1],"note":note,
                     "version":VERSION,"opencv_comparison":checks,"sha256":files})
    (output/"manifest.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    with (output/"comparison.csv").open("w",newline="",encoding="utf-8") as f:
        fields = ["name","width","height","max_abs_error","different_pixels","outside_tolerance","passed"]
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k:r[k] if k in r else r["opencv_comparison"][k] for k in fields})
    pixels = []
    rng = np.random.default_rng(20261027)
    values = [(0,0,0),(255,255,255),(255,0,0),(0,255,0),(0,0,255),(255,255,0),
              (255,0,255),(0,255,255),(1,1,1),(127,127,127),(128,128,128),(254,254,254)]
    values += [tuple(map(int,x)) for x in rng.integers(0,256,(20,3))]
    for b,g,r in values:
        cv = int(cv2.cvtColor(np.array([[[b,g,r]]],np.uint8),cv2.COLOR_BGR2GRAY)[0,0])
        pixels.append({"B":b,"G":g,"R":r,"axis32_hex":"{:08x}".format(b+(g<<8)+(r<<16)),
                       "gray_q15":gray_pixel(b,g,r),"gray_opencv":cv})
    with (output/"pixel_vectors.csv").open("w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f,fieldnames=list(pixels[0])); w.writeheader(); w.writerows(pixels)
    print(json.dumps({"cases":len(rows),"pixels":len(pixels),
                      "max_cv_error":max(x["opencv_comparison"]["max_abs_error"] for x in rows)}))


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",default="golden_vectors")
    p.add_argument("--images",default=None)
    a=p.parse_args(); generate(a.output,a.images)
