import json
import sys
from pathlib import Path
from types import ModuleType

from pdf2dify.engine_bridge import setup_datasets


def test_dify_setup_creates_only_categories_with_exported_documents(monkeypatch, tmp_path: Path):
    root = tmp_path / "engine-data"
    manifest = root / "full-export" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"documents": [{"domain": "finance"}]}), encoding="utf-8")
    old_state = root / "dify" / "full-state.json"
    old_state.parent.mkdir(parents=True)
    old_state.write_text(json.dumps({
        "datasets": {"finance": {"id": "old-empty"}},
        "documents": {"other": {"dataset_id": "unrelated-dataset"}},
    }), encoding="utf-8")

    def read_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def write_json(path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    created = []

    class Client:
        def call(self, method, endpoint, **kwargs):
            if method == "GET" and endpoint == "datasets":
                return {"data": [], "has_more": False}
            if method == "POST" and endpoint == "datasets":
                created.append(kwargs["json"]["name"])
                return {"id": "finance-dataset", **kwargs["json"]}
            raise AssertionError((method, endpoint))

    package = ModuleType("ops_rag")
    package.__path__ = []
    common = ModuleType("ops_rag.common")
    common.read_json = read_json
    common.write_json = write_json
    corpus = ModuleType("ops_rag.corpus")
    corpus.DOMAINS = {}
    full_sync = ModuleType("ops_rag.full_sync")
    full_sync.connect = lambda cfg: Client()
    full_sync.retrieval_model = lambda domain: {}
    package.common = common
    package.corpus = corpus
    package.full_sync = full_sync
    for name, module in (
        ("ops_rag", package), ("ops_rag.common", common),
        ("ops_rag.corpus", corpus), ("ops_rag.full_sync", full_sync),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("DIFY_BASE_URL", "http://dify.example/v1")
    monkeypatch.setenv("PDF2DIFY_DATASET_PREFIX", "pdf2dify-")
    monkeypatch.setenv("PDF2DIFY_DATASET_IDS", "{}")

    result = setup_datasets({
        "data_dir": str(root),
        "categories": {"finance": "财务核算", "equipment": "设备管理"},
    })

    assert created == ["pdf2dify-财务核算"]
    assert list(result) == ["finance"]
