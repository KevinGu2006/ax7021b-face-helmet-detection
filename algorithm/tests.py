import unittest,json
import numpy as np
from combined_pipeline import CombinedPipeline,associate
class Face:
    backend='injected_face'
    def __init__(self,boxes):self.boxes=boxes
    @staticmethod
    def validate_frame(frame):
        from face_detection import FaceDetector
        FaceDetector.validate_frame(frame)
    @staticmethod
    def validate_gray(gray):
        from face_detection import FaceDetector
        FaceDetector.validate_gray(gray)
    def detect_faces(self,image):return self.boxes
    def detect_faces_gray(self,image,original_shape=None):return self.boxes
class Heads:
    backend='injected_helmet'
    def __init__(self,heads):self.heads=heads;self.calls=0
    def predict(self,image):self.calls+=1;return self.heads,{'model':1.}
def head(box,status):return {'bbox':box,'status':status,'score':.9,'reason':'model_detection'}
class Tests(unittest.TestCase):
    def test_helmet_and_bare_head_association(self):
        rows,extra=associate([[40,80,80,120],[140,80,180,120]],
            [head([38,51,82,83],'helmet'),head([137,61,183,122],'no_helmet')],240,160)
        self.assertEqual([r['status'] for r in rows],['helmet','no_helmet']);self.assertEqual(extra,[])
    def test_missing_head_never_means_no_helmet(self):
        rows,_=associate([[40,80,80,120]],[],160,160)
        self.assertEqual(rows[0]['status'],'unknown')
    def test_ambiguous_two_faces_do_not_share_a_helmet(self):
        rows,extra=associate([[40,80,80,120],[50,80,90,120]],[head([43,52,87,84],'helmet')],160,160)
        self.assertEqual([r['status'] for r in rows],['unknown','unknown']);self.assertEqual(len(extra),1)
    def test_spatially_unrelated_hat_stays_unassigned(self):
        rows,extra=associate([[40,80,80,120]],[head([130,20,150,45],'helmet')],160,160)
        self.assertEqual(rows[0]['status'],'unknown');self.assertEqual(len(extra),1)
    def test_unknown_head_does_not_become_confident(self):
        rows,_=associate([[40,80,80,120]],[head([38,51,82,83],'unknown')],160,160)
        self.assertEqual(rows[0]['status'],'unknown')
    def test_no_faces_skips_model_but_does_not_claim_safe(self):
        heads=Heads([]);p=CombinedPipeline(Face([]),heads);image=np.zeros((160,240,3),np.uint8)
        out,r=p.run(image)
        self.assertEqual(heads.calls,0);self.assertEqual(r['face_count'],0);self.assertEqual(r['helmet_stage'],'skipped_no_faces')
        self.assertFalse(np.shares_memory(out,image));json.dumps(r,allow_nan=False)
    def test_many_faces_only_one_model_call_and_color_preserved(self):
        heads=Heads([]);p=CombinedPipeline(Face([[40,80,80,120],[140,80,180,120]]),heads)
        image=np.full((160,240,3),(12,82,198),np.uint8);before=image.copy();_,r=p.run(image)
        self.assertEqual(heads.calls,1);self.assertEqual(r['face_count'],2);np.testing.assert_array_equal(image,before)
    def test_external_gray_can_locate_while_bgr_is_retained(self):
        p=CombinedPipeline(Face([[40,80,80,120]]),Heads([]));image=np.zeros((160,240,3),np.uint8)
        _,r=p.run(image,np.zeros((160,240),np.uint8),gray_execution_backend='ZYNQ_PL')
        self.assertTrue(r['external_gray']);self.assertEqual(r['execution_backend']['gray'],'ZYNQ_PL')
        with self.assertRaises(ValueError):p.run(image,np.zeros((80,120),np.uint8))
    def test_legacy_image_list_contract(self):
        p=CombinedPipeline(Face([[40,80,80,120]]),Heads([]))
        _,ds=p.process_frame(np.zeros((160,240,3),np.uint8));self.assertIsInstance(ds,list);self.assertIn('face_bbox',ds[0])
    def test_invalid_image_fails(self):
        with self.assertRaises(TypeError):CombinedPipeline(Face([]),Heads([])).run(None)
    def test_real_haar_bgr_and_external_gray_agree(self):
        import cv2
        from pathlib import Path
        from face_detection import FaceDetector
        path=Path(__file__).resolve().parent/'test_inputs/010_bttf301.png'
        image=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR)
        pipeline=CombinedPipeline(FaceDetector(),Heads([]))
        _,bgr=pipeline.run(image)
        prepared=pipeline.face.prepare_bgr_for_pl(image)
        gray=cv2.cvtColor(prepared,cv2.COLOR_BGR2GRAY)
        _,pl=pipeline.run(image,gray,original_shape=image.shape[:2],gray_execution_backend='ZYNQ_PL')
        self.assertGreater(bgr['face_count'],0)
        self.assertEqual(bgr['detections'],pl['detections'])
    def test_a_factory_accepts_explicit_board_execution_backend(self):
        from unittest.mock import patch
        import raw_head_adapter
        with patch.object(raw_head_adapter,'CombinedPipeline') as factory:
            raw_head_adapter.create_detector('ncnn640',execution_backend='ZYNQ_ARM')
            factory.assert_called_once_with(helmet_profile='ncnn640',execution_backend='ZYNQ_ARM')
if __name__=='__main__':unittest.main()
