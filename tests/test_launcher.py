from pathlib import Path

import run as launcher


def test_frontend_rebuilds_when_index_changes(tmp_path: Path, monkeypatch):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "App.vue").write_text("initial", encoding="utf-8")
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    index = frontend / "index.html"
    index.write_text("<title>old</title>", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    (frontend / "node_modules" / ".pdf2dify-deps").write_text(
        launcher.fingerprint(frontend / "package.json", frontend / "package-lock.json"), encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "FRONTEND", frontend)
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "npm")
    commands = []

    def command(*args, **_kwargs):
        commands.append(args)
        (frontend / "dist").mkdir(exist_ok=True)
        (frontend / "dist" / "index.html").write_text("built", encoding="utf-8")

    monkeypatch.setattr(launcher, "command", command)

    launcher.ensure_frontend()
    assert commands == [("npm", "run", "build")]
    index.write_text("<title>new</title>", encoding="utf-8")
    launcher.ensure_frontend()
    assert commands == [("npm", "run", "build"), ("npm", "run", "build")]
