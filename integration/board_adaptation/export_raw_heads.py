"""Run with onnx==1.17.0; keeps B's source model and learned head weights unchanged."""
import pathlib,hashlib,onnx,numpy as np
from onnx import numpy_helper
r=pathlib.Path(__file__).resolve().parent
p=r/'models/release.onnx'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='1df4b82cd69f345acb16e8faf74ae109c7edeb320d33179d2e8836765a715e8f'
m=onnx.shape_inference.infer_shapes(onnx.load(str(p)))
initial={x.name:x for x in m.graph.initializer}
node=next(x for x in m.graph.node if x.name=='/model.22/dfl/conv/Conv')
assert np.array_equal(numpy_helper.to_array(initial[node.input[1]]).ravel(),np.arange(16,dtype=np.float32))
names=['/model.22/Concat_output_0','/model.22/Concat_1_output_0','/model.22/Concat_2_output_0']
raw=onnx.utils.Extractor(m).extract_model([m.graph.input[0].name],names)
onnx.checker.check_model(raw);onnx.save(raw,str(r/'release_raw_heads.onnx'))
