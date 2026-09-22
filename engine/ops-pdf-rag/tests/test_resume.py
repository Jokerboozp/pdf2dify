from contextlib import nullcontext
from types import SimpleNamespace
from PIL import Image
from ops_rag.common import write_json, signature
from ops_rag import __version__
from ops_rag import pipeline


def test_limit_counts_pending_pages_and_next_run_advances(tmp_path, monkeypatch):
    cfg = {'data_dir': str(tmp_path), 'ocr': {'render_scale': 1, 'min_score': .75}}
    tasks = [dict(source_id='source', sha256='hash', path='source.pdf', name='source.pdf', page=n) for n in (1, 2, 3)]
    write_json(tmp_path/'pilot-manifest.json', {'pages': tasks})
    sig = signature({'config': cfg['ocr'], 'version': __version__, 'format': 4})
    write_json(tmp_path/'parsed/source/p0001.json', {'status': 'complete', 'run_signature': sig})
    bitmap = SimpleNamespace(to_pil=lambda: Image.new('RGB', (100, 100), 'white'), close=lambda: None)
    page = SimpleNamespace(render=lambda **kw: bitmap, close=lambda: None)
    class Document:
        def __getitem__(self, _): return page
        def close(self): pass
    lp = SimpleNamespace(extract_text=lambda **kw: '这是用于验证断点续跑的正文' * 5, images=[],
                         width=100, height=100, find_tables=lambda: [], close=lambda: None)
    monkeypatch.setattr(pipeline, 'digest_file', lambda _: 'hash')
    monkeypatch.setattr(pipeline.pdfium, 'PdfDocument', lambda _: Document())
    monkeypatch.setattr(pipeline.pdfplumber, 'open', lambda _: nullcontext(SimpleNamespace(pages=[lp, lp, lp])))
    first = pipeline.process(cfg, limit=1)
    assert first['completed'] == 1 and first['failed'] == []
    assert (tmp_path/'parsed/source/p0002.json').exists()
    assert not (tmp_path/'parsed/source/p0003.json').exists()
    second = pipeline.process(cfg, limit=1)
    assert second['completed'] == 1 and second['failed'] == []
    assert (tmp_path/'parsed/source/p0003.json').exists()
