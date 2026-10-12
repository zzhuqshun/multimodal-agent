import hashlib
import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("corrupt", [False, True])
def test_pinned_model_download_checks_bytes_before_publish(tmp_path, monkeypatch, corrupt):
    root = tmp_path / "server"
    (root / "state").mkdir(parents=True)
    (root / "env" / "bin").mkdir(parents=True)
    (root / "env" / "bin" / "python").touch()
    expected = b'{"model_type":"qwen3_5"}'
    source = {"files": [{"Path": "config.json", "Size": len(expected),
                         "Sha256": hashlib.sha256(expected).hexdigest(), "Revision": "a" * 40}]}
    manifest = root / "state" / "model-source.json"
    manifest.write_text(json.dumps(source))
    script = root / "download-model.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts" / "download-qwen-model.py", script)
    calls = []

    def curl(command, **kwargs):
        calls.append(command)
        assert command[0] == "curl"
        assert "Revision=" + "a" * 40 in command[-1]
        destination = Path(command[command.index("--output") + 1])
        destination.write_bytes(expected if not corrupt else b"wrong")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", curl)
    if corrupt:
        with pytest.raises(ValueError, match="size/hash"):
            runpy.run_path(str(script))
        assert not (root / "state" / "model-ready").exists()
        assert not (root / "models" / "Qwen3.5-9B" / "config.json").exists()
    else:
        runpy.run_path(str(script))
        assert (root / "state" / "model-ready").exists()
        assert (root / "models" / "Qwen3.5-9B" / "config.json").read_bytes() == expected
        runpy.run_path(str(script))
        assert len(calls) == 1  # Reuse pinned files instead of downloading again.
    assert json.loads(manifest.read_text()) == source


def test_model_downloader_refuses_outside_environment(tmp_path):
    script = tmp_path / "download-model.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts" / "download-qwen-model.py", script)
    with pytest.raises(SystemExit, match="isolated server"):
        runpy.run_path(str(script))
    assert not (tmp_path / "models").exists()
