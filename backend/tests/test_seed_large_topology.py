from scripts.seed_large_topology import build_topology_plan


def test_plan_honours_requested_counts():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    assert len(plan.systems) == 7
    assert len(plan.components) == 300
    assert len(plan.deps) == 600


def test_plan_has_exactly_one_hub_with_most_cross_edges():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    hubs = [s for s in plan.systems if s.is_hub]
    assert len(hubs) == 1
    hub = hubs[0]
    cross_by_system: dict[int, int] = {}
    for d in plan.deps:
        if not d.cross:
            continue
        from_sys = plan.components[d.from_index].system_index
        to_sys = plan.components[d.to_index].system_index
        cross_by_system[from_sys] = cross_by_system.get(from_sys, 0) + 1
        cross_by_system[to_sys] = cross_by_system.get(to_sys, 0) + 1
    assert cross_by_system[hub.index] == max(cross_by_system.values())


def test_deps_are_well_formed():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    n = len(plan.components)
    for d in plan.deps:
        assert 0 <= d.from_index < n and 0 <= d.to_index < n
        assert d.from_index != d.to_index
        same_system = (
            plan.components[d.from_index].system_index
            == plan.components[d.to_index].system_index
        )
        assert d.cross != same_system  # cross <=> different systems


def test_plan_is_deterministic_for_a_seed():
    a = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    b = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    assert [(d.from_index, d.to_index, d.cross) for d in a.deps] == [
        (d.from_index, d.to_index, d.cross) for d in b.deps
    ]


def test_cross_ratio_is_roughly_a_quarter():
    plan = build_topology_plan(num_systems=7, num_components=300, num_deps=600, seed=42)
    cross = sum(1 for d in plan.deps if d.cross)
    assert 120 <= cross <= 180  # ~25% of 600
