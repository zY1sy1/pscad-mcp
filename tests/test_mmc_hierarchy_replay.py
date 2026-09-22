"""Save compatibility for the hierarchy's instance index only."""

import copy
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc import native_fault_replay as replay


@pytest.mark.parametrize('change', ['reorder', 'renumbered', 'bad_ordinal', 'missing_ordinal', 'link', 'duplicate', 'missing', 'added', 'nested', 'schematic'])
def test_replay_preserves_unique_hierarchy_calls_and_all_model_content(tmp_path, change):
    original, saved = tmp_path / 'first.pscx', tmp_path / 'second.pscx'
    original.write_text('<project><hierarchy><call name="Case:Station" link="1"><call name="Case:Main" link="2"><call name="Case:DCTL" link="1533195475"><call name="Case:Line" link="9"/></call><call name="Case:DCTL" link="2005307872"/></call></call></hierarchy><definitions><Definition name="Main"><schematic><User id="10"/><User id="11"/></schematic></Definition></definitions></project>')
    tree = ET.parse(original)
    main = tree.find('./hierarchy/call/call')
    if change in ('renumbered', 'bad_ordinal', 'missing_ordinal'):
        for index, node in enumerate(main):
            node.set('instance', str(index))
        tree.write(original, encoding='utf-8')
    main[:] = list(reversed(main))
    if change == 'renumbered':
        for index, node in enumerate(main):
            node.set('instance', str(index))
    elif change == 'missing_ordinal':
        main[0].attrib.pop('instance')
    if change == 'link':
        main[0].set('link', '7')
    elif change == 'duplicate':
        main.append(copy.deepcopy(main[0]))
    elif change == 'missing':
        main.remove(main[0])
    elif change == 'added':
        ET.SubElement(main, 'call', name='Case:DCTL', link='8')
    elif change == 'nested':
        main[1][0].set('name', 'Case:DifferentLine')
    elif change == 'schematic':
        canvas = tree.find('./definitions/Definition/schematic')
        canvas[:] = list(reversed(canvas))
    tree.write(saved, encoding='utf-8')
    if change in ('reorder', 'renumbered'):
        assert replay._verify_replay_saved_model(original, saved, {}) is True
    else:
        with pytest.raises(ValueError):
            replay._verify_replay_saved_model(original, saved, {})
