"""Regression coverage for a joint case derived from an accepted saved model."""

import asyncio
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests import mmc_timing_fault_case as joint


@pytest.mark.parametrize("change", [None, "panel", "panel_wrong", "panel_foreign", "physical", "command", "position", "unrelated_width"])
def test_first_save_accepts_only_planned_timing_node_display_metadata(tmp_path, monkeypatch, change):
    before = tmp_path / "before.pscx"
    after = tmp_path / "after.pscx"
    before.write_text('<project><paramlist name="Settings"><param name="time_duration" value="5"/><param name="time_step" value="25"/><param name="sample_step" value="250"/><param name="PlotType" value="1"/><param name="StartType" value="0"/></paramlist><definitions><Definition name="Main"><schematic><User id="1" w="39" h="51" x="0" y="0"><paramlist crc="12"><param name="Value" value="-900"/></paramlist></User><User id="2" w="38" h="38" x="36" y="0"><paramlist><param name="Scale" value="1"/></paramlist></User><User id="3" w="38" h="38"><paramlist><param name="Ti" value="0.04"/></paramlist></User></schematic></Definition></definitions></project>')
    tree = ET.parse(before)
    control, probe, physical = tree.findall('./definitions/Definition/schematic/User')
    if change and change.startswith('panel'):
        ET.SubElement(control.find('paramlist'), 'param', name='Name', value='Pref2')
        frame = ET.SubElement(tree.find('./definitions/Definition/schematic'), 'Frame')
        panel = ET.SubElement(frame, 'Control', name='Pref2', link='3' if change == 'panel_foreign' else '1', classid='Slider', id='4')
        tree.write(before, encoding='utf-8')
        panel.set('name', 'wrong' if change == 'panel_wrong' else '')
    control.set('w', '69'); control.set('h', '33'); control.find('paramlist').set('crc', '55')
    probe.set('w', '147'); probe.set('q', '4'); probe.find('paramlist').set('crc', '77')
    if change == 'physical':
        physical.find('./paramlist/param').set('value', '0.08')
    elif change == 'command':
        control.find('./paramlist/param').set('value', '-800')
    elif change == 'position':
        probe.set('x', '54')
    elif change == 'unrelated_width':
        physical.set('w', '99')
    tree.write(after, encoding='utf-8')
    schedule = {'event_channels': [{'owner': '2', 'control_owner': '1'}]}
    verified = []
    monkeypatch.setattr(joint.timed_control, 'verify_embedded_control', lambda *args: verified.append(args))
    if change in (None, 'panel'):
        assert joint._verify_first_saved_model(before, after, {}, schedule=schedule)
        assert verified
    else:
        with pytest.raises(ValueError):
            joint._verify_first_saved_model(before, after, {}, schedule=schedule)


@pytest.fixture(scope='module')
def published_seed_case(tmp_path_factory):
    previous = Path('D:/PSCAD-Workspace/mmc-joint-20260922-r1/.pscad-mcp/mmc-builds/9d05449d39ac48ada2844f48de0954a0/journal.json')
    if not previous.is_file():
        pytest.skip('The frozen licensed first-save regression artifact is unavailable')
    prior = json.loads(previous.read_text())
    seed = prior['public_prerequisite']
    source = prior['b_handoff']['source_hashes']
    root = tmp_path_factory.mktemp('published_seed') / 'case'
    preparation = asyncio.run(joint.prepare_joint_case(root,
        source=source['project']['path'], library=source['library']['path'],
        master=source['master']['path'], model_recipe=prior['b_handoff']['recipe']['id'],
        publication_seed=seed))
    return preparation


def test_joint_seed_uses_accepted_saved_body_and_frozen_dependencies(published_seed_case):
    value = published_seed_case
    assert value['physical_acceptance_verified'] is False
    assert value['publication_seed']['project']['sha256'] == '907ca7b02153b1a59587aa6234a1375b87432f3ca1924a69e1ed060c78cf21cc'
    assert all(stage['stage'] not in {'charging_delay_repair', 'complete_arm_sorting'} for stage in value['lineage'])
    assert joint.verify_joint_preparation(value)


def test_joint_seed_keeps_parent_binding_after_rehash(published_seed_case):
    changed = copy.deepcopy(published_seed_case)
    changed['publication_seed']['project']['sha256'] = '0' * 64
    changed['preparation_sha256'] = joint._digest({key: value for key, value in changed.items() if key != 'preparation_sha256'})
    with pytest.raises((ValueError, RuntimeError)):
        joint.verify_joint_preparation(changed)
