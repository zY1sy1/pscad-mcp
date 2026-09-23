import hashlib

import pytest

from pscad_mcp.hvdc.builders.mmc.native_portable import copy_native_bundle


def test_portable_copy_contains_only_frozen_models_and_declared_constants(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    project, library, constants = source / "model.pscx", source / "lib.pslx", source / "constants" / "cable.clo"
    constants.parent.mkdir()
    project.write_text('<project name="model"/>')
    library.write_text(f'<project name="lib"><paramlist><param name="const_path" value="{constants}"/></paramlist></project>')
    constants.write_text("constants")
    (source / "model.exe").write_text("stale executable")
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (project, library, constants)}
    result = copy_native_bundle(project, library, hashes, tmp_path / "reload")
    assert len(result["copied_hashes"]) == 3
    assert not (tmp_path / "reload" / "model.exe").exists()
    assert result["model_accepted"] is False
    assert result["dependency_relocations"][0]["after"] == str(tmp_path / "reload" / "constants" / "cable.clo")
    assert str(source) not in (tmp_path / "reload" / "lib.pslx").read_text()
    constants.write_text("changed")
    with pytest.raises(ValueError, match="source changed"):
        copy_native_bundle(project, library, hashes, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_portable_manifest_cannot_copy_an_outside_file(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    project, library, outside = source / "model.pscx", source / "lib.pslx", tmp_path / "outside"
    for path in (project, library, outside):
        path.write_text("data")
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (project, library, outside)}
    with pytest.raises(ValueError, match="escapes"):
        copy_native_bundle(project, library, hashes, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
