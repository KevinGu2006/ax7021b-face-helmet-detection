from combined_pipeline import CombinedPipeline
_pipeline=None
def configure(**kwargs):
    global _pipeline
    _pipeline=CombinedPipeline(**kwargs);return _pipeline
def process_frame(frame_bgr):
    global _pipeline
    if _pipeline is None:_pipeline=CombinedPipeline()
    return _pipeline.process_frame(frame_bgr)
