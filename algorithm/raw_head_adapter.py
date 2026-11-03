"""A's existing factory now returns BOTH face and helmet processing."""
import os
from combined_pipeline import CombinedPipeline
def create_detector(profile=None,execution_backend=None):
    return CombinedPipeline(helmet_profile=profile or os.environ.get('HELMET_PROFILE','ncnn640'),
                            execution_backend=execution_backend or os.environ.get('VISION_EXECUTION_BACKEND','PC'))
