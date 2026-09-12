"""Electrical checks shared by planned and independently observed MMC graphs."""

from collections import defaultdict, deque


def cable_path_issues(components, nets):
    adjacency = defaultdict(set)
    for net in nets:
        if net.kind != "electrical":
            continue
        nodes = [("endpoint", endpoint) for endpoint in net.endpoints]
        if net.label is not None:
            nodes.append(("label", net.label))
        for node in nodes[1:]:
            adjacency[nodes[0]].add(node)
            adjacency[node].add(nodes[0])
    issues = []
    for component in components:
        if component.definition == "master:dc_cable":
            pairs = (("IN", "OUT"),)
        elif component.definition.endswith(":MMCCableLink"):
            pairs = (("SEND_POS", "RECV_POS"), ("SEND_NEG", "RECV_NEG"))
        else:
            continue
        for sending, receiving in pairs:
            start = ("endpoint", f"{component.logical_id}:{sending}")
            end = ("endpoint", f"{component.logical_id}:{receiving}")
            if start not in adjacency or end not in adjacency:
                issues.append(
                    {"component": component.logical_id, "reason": "unconnected"}
                )
                continue
            pending, visited = deque([start]), {start}
            while pending:
                node = pending.popleft()
                if node == end:
                    issues.append(
                        {"component": component.logical_id, "reason": "bypassed"}
                    )
                    break
                for neighbor in adjacency[node] - visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
    return issues


def is_neutral_reference(terminals, components):
    return any(port == "NEUTRAL" for _, port in terminals) and all(
        owner in components
        and (
            (
                port == "NEUTRAL"
                and components[owner].definition
                in {"master:source3", "master:transformer"}
            )
            or (port == "GND" and components[owner].definition == "master:ground")
        )
        for owner, port in terminals
    )
