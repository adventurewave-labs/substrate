"""Cluster view: the canonical person is a connected component, not a mutated row.

Merges are never executed destructively (repo invariant: import never merges
identities; claims are append-only). A cluster = persons linked by auto_merge
decisions; the canonical id is the lexicographically smallest member id, so the
view is deterministic across replays. Reject decisions sever nothing — they are
recorded and simply never enter the union.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MergeEdge:
    left_id: str
    right_id: str


def clusters(person_ids: list[str], merge_edges: list[MergeEdge]) -> dict[str, str]:
    """Union-find over auto_merge edges → {person_id: canonical_id}.

    Every person appears in the result, singletons mapping to themselves.
    Edges referencing unknown (e.g. erased) persons are skipped, never KeyError —
    erasure is an invariant-sanctioned path and must not break the cluster view.
    """
    parent = {pid: pid for pid in person_ids}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    for edge in merge_edges:
        if edge.left_id not in parent or edge.right_id not in parent:
            continue  # erased or otherwise absent — the live set wins
        a, b = find(edge.left_id), find(edge.right_id)
        if a != b:
            parent[max(a, b)] = min(a, b)

    return {pid: find(pid) for pid in person_ids}
