from substrate.er.cluster import MergeEdge, clusters


def test_singleton_map_to_self():
    assert clusters(["a", "b"], []) == {"a": "a", "b": "b"}


def test_chain_merges_to_smallest_id():
    edges = [MergeEdge("b", "c"), MergeEdge("a", "b")]
    result = clusters(["a", "b", "c", "d"], edges)
    assert result == {"a": "a", "b": "a", "c": "a", "d": "d"}


def test_transitive_and_deterministic():
    edges = [MergeEdge("e", "d"), MergeEdge("d", "e"), MergeEdge("e", "a")]
    result = clusters(["a", "d", "e"], edges)
    assert set(result.values()) == {"a"}


def test_reject_edges_never_enter_the_union():
    # Reject decisions simply do not arrive here — the caller filters. This test
    # pins that clusters() ignores anything but the edges it is given.
    assert clusters(["a", "b"], [MergeEdge("a", "b")]) == {"a": "a", "b": "a"}
