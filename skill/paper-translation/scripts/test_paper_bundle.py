import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

import pymupdf

spec=importlib.util.spec_from_file_location("paper_bundle",Path(__file__).with_name("paper_bundle.py"))
bundle=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def paper(self,single=False):
        doc=pymupdf.open()
        page=doc.new_page(width=600,height=800)
        page.insert_text((60,80),"A paper")
        page.draw_rect(pymupdf.Rect(60,100,280,180))
        page.insert_text((60,250),"Body left before references.")
        page.insert_text((330,250),"Body right before references.")
        x=60 if single else 330
        page.insert_text((x,400),"References")
        page.insert_text((x,430),"Should not be in translation input.")
        path=self.root/"paper.pdf"
        doc.save(path)
        return {"slug":"paper","title":"A paper","source_pdf":str(path),"main_end_page":1,
                "single_column":single,"figures":[{"number":1,"page":1,"rect_normalized":[.1,.12,.48,.23],"path":"medias/figure-01.png"}]}

    def test_two_column_reference_trimming_preserves_body(self):
        paper=self.paper()
        before=Path(paper["source_pdf"]).read_bytes()
        bundle.prepare(self.root,paper)
        main=pymupdf.open(self.root/"paper/source/main.pdf")[0].get_text()
        self.assertIn("Body left",main)
        self.assertIn("Body right",main)
        self.assertNotIn("Should not",main)
        self.assertNotIn("References",main)
        self.assertEqual(before,Path(paper["source_pdf"]).read_bytes())
        self.assertTrue((self.root/"paper/medias/figure-01.png").exists())

    def test_single_column_trimming_preserves_full_width_body(self):
        paper=self.paper(single=True)
        bundle.prepare(self.root,paper)
        text=pymupdf.open(self.root/"paper/source/main.pdf")[0].get_text()
        self.assertIn("Body right",text)
        self.assertIn("Body left",text)
        self.assertNotIn("Should not",text)

    def test_paths_and_frozen_input(self):
        with self.assertRaises(ValueError):bundle.inside(self.root,"../outside")
        p=self.root/"input.txt";p.write_text("original")
        checksum=bundle.digest(p.read_bytes());p.write_text("changed")
        with self.assertRaises(ValueError):bundle.checked(self.root,"input.txt",checksum)

    def test_explicit_reference_boundary_works_without_heading_detection(self):
        from unittest.mock import patch
        paper=self.paper()
        paper['references_heading']=[330,388,400,403]
        with patch.object(bundle,'find_references',return_value=None):
            bundle.prepare(self.root,paper)
        text=pymupdf.open(self.root/'paper/source/main.pdf')[0].get_text()
        self.assertIn('Body right',text)
        self.assertNotIn('References',text)

    def test_reviewed_output_is_not_overwritten_by_assembly(self):
        folder=self.root/'paper/source';folder.mkdir(parents=True)
        (folder/'codex-review.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Reviewed output'):
            bundle.assemble(self.root,{'slug':'paper'})

    def test_cross_page_sentence_keeps_float_and_meaning(self):
        value='我们根据当前状态生成动作，并检查动作是否\n\n<!-- source-page: 2 -->\n\n![图1](medias/figure-01.png)\n\n图 1：流程。\n\n成功执行。这是判定的依据。'
        merged=bundle.join_page_fragments(value)
        visible=__import__('re').sub(r'<!--.*?-->','',merged)
        self.assertIn('检查动作是否成功执行。',visible)
        self.assertEqual(merged.count('medias/figure-01.png'),1)
        self.assertIn('图 1：流程。',merged)

    def test_complex_subtable_caption_is_not_joined_into_sentence(self):
        value='对于成功的轨迹，\n\n<!-- source-page: 2 -->\n\n**表 1**：实验结果\n\n(a) 子表的说明。\n\n| 模型 | 得分 |\n| --- | --- |\n| A | 1 |\n\n我们检查每一步的正确性。'
        merged=bundle.join_page_fragments(value)
        self.assertNotIn('<!-- source-page: 2 -->**表',merged)
        self.assertIn('**表 1**：实验结果',merged)

    def test_completed_generation_reused_without_second_call(self):
        paper=self.paper();bundle.prepare(self.root,paper)
        dest=self.root/"paper"
        part=json.loads((dest/"source/plan.json").read_text())["parts"][0]
        calls=[]
        def request(*args):
            calls.append(args)
            text='<!-- source-page: 1 -->\n# 测试论文\n\n![图1](medias/figure-01.png)\n\n完整正文。\n\n<!-- translation-part-complete: 1-1 -->'
            return {"model":"test-model","choices":[{"finish_reason":"stop","message":{"content":text}}]},200,.1
        client=SimpleNamespace(load_key=lambda:"test-only",request_json=request)
        for _ in range(2):bundle.generation(self.root,paper,part,{"model":"test-model"},client,False,threading.Event())
        self.assertEqual(len(calls),1)
        bundle.assemble(self.root,paper)
        self.assertEqual(bundle.validate(self.root,paper)["status"],"checks_passed")

    def test_incomplete_response_never_assembled_and_retry_capped(self):
        paper=self.paper();bundle.prepare(self.root,paper)
        part=json.loads((self.root/"paper/source/plan.json").read_text())["parts"][0]
        calls=[]
        def request(*args):
            calls.append(args)
            return {"choices":[{"finish_reason":"length","message":{"content":"仅有片段"}}]},200,.1
        client=SimpleNamespace(load_key=lambda:"test-only",request_json=request)
        for retry in [False,False,True,True]:bundle.generation(self.root,paper,part,{"model":"test-model"},client,retry,threading.Event())
        self.assertEqual(len(calls),2)
        with self.assertRaises(ValueError):bundle.assemble(self.root,paper)
        self.assertFalse((self.root/"paper/paper_zh.md").exists())

    def test_quota_error_inside_http_200_stops_dispatch(self):
        paper=self.paper();bundle.prepare(self.root,paper)
        part=json.loads((self.root/"paper/source/plan.json").read_text())["parts"][0]
        client=SimpleNamespace(load_key=lambda:"test-only",request_json=lambda *args:({'error':{'code':'rate_limit_exceeded','message':'reset later'}},200,.1))
        halt=threading.Event()
        bundle.generation(self.root,paper,part,{'model':'test-model'},client,False,halt)
        self.assertTrue(halt.is_set())
        status=json.loads((self.root/'paper/source/parts/part-01.status.json').read_text())
        self.assertEqual(status['status'],'failed')


if __name__=="__main__":unittest.main()
