"""Preserve a verified public model while rebinding its local line files."""

from __future__ import annotations

import copy
from pathlib import Path
from xml.etree import ElementTree as ET

from pscad_mcp.hvdc.builders.mmc import blank_service, fault_channels
from tests.mmc_publication_resume import _Ledger


def _require(value, message):
    if not value:
        raise ValueError(message)


def _check(reference):
    _require(_Ledger().check(reference['path'], reference['sha256']) == reference, 'A frozen public seed reference changed')


def _render_seed(project, paths):
    tree = ET.parse(project)
    seen = set()
    for wire in tree.findall('./definitions/Definition/schematic/Wire'):
        if wire.get('classid') != 'TLine':
            continue
        names = wire.findall("./User/paramlist/param[@name='Name']")
        if len(names) != 1 or names[0].get('value') not in paths:
            continue
        name = names[0].get('value')
        values = wire.findall("./User/paramlist/param[@name='const_path']")
        _require(name not in seen and len(values) == 1 and values[0].get('value') == paths[name]['before'], 'The public seed line binding changed')
        values[0].set('value', paths[name]['after'])
        seen.add(name)
    _require(seen == set(paths), 'The public seed is missing a required line')
    return tree


def verify_public_seed(seed, plan=None):
    for key in ('receipt', 'project', 'manifest', 'channel_contract', 'derived_project', 'b_handoff'):
        _check(seed[key])
    receipt = blank_service._read_hashed_json(Path(seed['receipt']['path']), seed['receipt']['sha256'])
    _require(receipt.get('status') == 'PASS' and receipt.get('scope') == 'public_mmc_publication_recovery'
             and receipt.get('history', [])[-1:] == ['finished'] and receipt.get('lease_retained') is False
             and receipt['published_project'] == seed['project'] and receipt['publication_manifest'] == seed['manifest'],
             'The joint seed is not the finalized recovered publication')
    manifest = blank_service._read_hashed_json(Path(seed['manifest']['path']), seed['manifest']['sha256'])
    _require(manifest['plan'] == seed['parent_plan'] and manifest['checks_sha256'] == seed['checks_sha256']
             and manifest['channel_contract_sha256'] == seed['channel_contract']['sha256']
             and receipt['b_handoff'] == seed['b_handoff'], 'The public seed physical provenance changed')
    old_plan = seed['parent_plan']
    if plan is not None:
        _require(old_plan['source_identities'] == plan['source_identities'] and old_plan['settings'] == plan['settings']
                 and old_plan['checks_contract'] == plan['checks_contract']
                 and all(old_plan['model_recipe'][key] == plan['model_recipe'][key] for key in ('name', 'parameters', 'steps')),
                 'The joint seed and current preparation contract differ')
    old_bundle = Path(seed['project']['path']).with_suffix('.bundle').name
    expected_paths = {item['name']: {'before': old_bundle + '/lines/' + item['name'] + '.tlo',
                                    'after': 'JointFaultCase.bundle/lines/' + item['name'] + '.tlo'}
                      for item in old_plan['line_constants']['inputs']}
    _require(seed['line_paths'] == expected_paths, 'The seed line paths differ from the fixed local runtime layout')
    expected = _render_seed(seed['project']['path'], seed['line_paths'])
    actual = Path(seed['derived_project']['path']).read_text(encoding='utf-8')
    _require(ET.canonicalize(ET.tostring(expected.getroot(), encoding='unicode'), strip_text=True)
             == ET.canonicalize(actual, strip_text=True), 'The derived seed changed beyond the declared line paths')
    return True


def prepare_public_seed(plan, published, root, bundle, record):
    for key in ('receipt', 'project', 'manifest'):
        _check(published[key])
    project = Path(published['project']['path'])
    manifest, contract, checks, _ = blank_service._load_publication_evidence(project)
    _require(published['validation'].get('accepted') is True and published['plan'] == manifest['plan'], 'The public seed lacks its verified physical publication')
    old_plan = manifest['plan']
    _require(old_plan['source_identities'] == plan['source_identities'] and old_plan['settings'] == plan['settings']
             and checks == plan['checks_contract'] and all(old_plan['model_recipe'][key] == plan['model_recipe'][key] for key in ('name', 'parameters', 'steps')),
             'The joint seed and requested model contract differ')
    old_bundle = project.with_suffix('.bundle')
    request_hash = manifest['reload']['artifacts']['request.json']['sha256']
    request = blank_service._read_hashed_json(blank_service._bundle_file(old_bundle, 'reload/request.json'), request_hash)
    expected_dependencies = {Path(plan['source_identities']['library']['path']).name}
    expected_dependencies.update(item['relative_path'] for item in plan['compiler_support']['files'])
    expected_dependencies.update('lines/' + item['name'] + suffix for item in plan['line_constants']['inputs'] for suffix in ('.tli', '.tlo', '.log', '.out'))
    _require(set(request['bundle']['files']) == expected_dependencies, 'The public seed runtime dependency set changed')
    copies = record.setdefault('dependency_copies', [])
    for relative, digest in request['bundle']['files'].items():
        source = blank_service._bundle_file(old_bundle, relative)
        target = (bundle / relative).resolve()
        _require(target.is_relative_to(bundle.resolve()), 'A runtime dependency escapes the fresh joint bundle')
        copies.append(blank_service._copy_frozen(source, target, digest))
    paths = {}
    for item in plan['line_constants']['inputs']:
        name = item['name']
        relative = 'lines/' + name + '.tlo'
        _require(relative in request['bundle']['files'], 'An accepted line constant is missing')
        paths[name] = {'before': (Path(old_bundle.name) / relative).as_posix(), 'after': (Path(bundle.name) / relative).as_posix()}
    instrumented = root / 'FaultInstrumented.pscx'
    _render_seed(project, paths).write(instrumented, encoding='utf-8', xml_declaration=True)
    seed = {key: copy.deepcopy(published[key]) for key in ('receipt', 'project', 'manifest')}
    seed.update({'derived_project': blank_service._identity(instrumented), 'line_paths': paths,
                 'parent_plan': copy.deepcopy(old_plan), 'checks_sha256': manifest['checks_sha256'],
                 'b_handoff': copy.deepcopy(published['b_handoff']),
                 'channel_contract': blank_service._identity(blank_service._bundle_file(old_bundle, manifest['channel_contract_relative_path']))})
    verify_public_seed(seed, plan)
    record['publication_seed'] = seed
    record['lineage'].append({'stage': 'accepted_publication_seed', 'source': str(project), 'source_sha256': published['project']['sha256'],
                              'destination': str(instrumented), 'destination_sha256': seed['derived_project']['sha256']})
    parent = copy.deepcopy(contract)
    parent.pop('virtual_root_rebinding', None)
    parent.pop('publication_parent_contract_sha256', None)
    parent.update({'project_path': str(instrumented), 'instrumented_project_sha256': seed['derived_project']['sha256'], 'vendor_finalized': False})
    parent['readback'] = fault_channels.verify_fault_instrumentation(instrumented, parent)
    return parent, project
