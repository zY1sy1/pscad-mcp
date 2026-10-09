import hashlib

import pytest

from pscad_mcp.builders.blueprint.inventory import read_live_inventory
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from tests.test_legacy_workspace_reload import arrange


def prepared(tmp_path):
    backend, app = arrange(tmp_path)
    project = backend.definition_paths["Source"]
    project.write_text('''<project name="Source"><definitions><Definition name="Main">
    <schematic><User classid="UserCmp" id="7" defn="master:source_1" x="20" y="30" orient="0">
    <paramlist><param name="Name" value="Source1"/><param name="Vm" value="70.71 [kV]"/></paramlist>
    </User><Wire classid="WireOrthogonal" id="8"/></schematic></Definition></definitions></project>''', encoding="utf-8")
    master = tmp_path / "master.pslx"
    master.write_text('''<project name="master"><definitions><Definition name="source_1">
    <form><category><parameter name="Name" type="Text"/><parameter name="Vm" type="Real" unit="kV"/></category></form>
    <svg><port name="A" x="18" y="0" model="Natural" dim="1" type="NonRemovable"/></svg>
    </Definition></definitions></project>''', encoding="utf-8")
    backend.definition_paths["master"] = master
    backend._loaded_project_files[project] = ("Source", hashlib.sha256(project.read_bytes()).hexdigest())
    service = PscadService(lambda: backend, executor=backend.executor, path_policy=PathPolicy(str(tmp_path)))
    service._backend = backend
    return service, backend, app, project


@pytest.mark.asyncio
async def test_saved_loaded_legacy_inventory_uses_real_library_units_without_dirtying_source(tmp_path):
    service, backend, app, project = prepared(tmp_path)
    before = project.read_bytes()
    snapshot = await read_live_inventory(service, "Source")
    assert len(snapshot.components) == 1
    assert snapshot.components[0]["parameters"]["Vm"] == "70.71 [kV]"
    assert snapshot.definitions["master:source_1"]["parameters"]["Vm"]["units"] == "kV"
    assert snapshot.components[0]["ports"]["A"]["x"] == 38
    assert app.projects["Source"].dirty is False
    assert project.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["dirty", "changed", "unloaded"])
async def test_saved_loaded_inventory_rejects_source_that_is_not_current_and_saved(tmp_path, reason):
    service, backend, app, project = prepared(tmp_path)
    if reason == "dirty":
        app.projects["Source"].dirty = True
    elif reason == "changed":
        project.write_text(project.read_text().replace("70.71", "35.355"), encoding="utf-8")
    else:
        app.projects.pop("Source")
    with pytest.raises(BackendError):
        await read_live_inventory(service, "Source")
