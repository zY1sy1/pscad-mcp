from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.common.blank import (
    BlankProjectFactory,
    ComponentLibraryResolver,
    DefinitionResolution,
)


def test_resolver_prefers_master_and_records_hashes(tmp_path: Path):
    resolver = ComponentLibraryResolver(
        master={"master:source": {"ports": ["A"]}},
        companion={"companion:bridge": {"ports": ["DC_POS"], "sha256": "abc"}},
    )
    master = resolver.resolve("master:source")
    companion = resolver.resolve("companion:bridge")
    assert isinstance(master, DefinitionResolution)
    assert master.source == "master"
    assert companion.source == "companion"
    assert companion.source_hash == "abc"


def test_resolver_fails_closed_for_missing_definition():
    with pytest.raises(BackendError) as raised:
        ComponentLibraryResolver(master={}, companion={}).resolve("missing:item")
    assert raised.value.code == "BLANK_DEFINITION_MISSING"


def test_factory_rejects_existing_destination_and_never_overwrites(tmp_path: Path):
    target = tmp_path / "case.pscx"
    target.write_text("existing", encoding="ascii")
    factory = BlankProjectFactory(tmp_path)
    with pytest.raises(BackendError) as raised:
        factory.plan("case")
    assert raised.value.code == "BLANK_BUILD_CONFLICT"
    assert target.read_text(encoding="ascii") == "existing"
