"""Deterministic diversity assignment for the 27 generated scenarios.

scenario_en, attack_vector, banking_flow, domain and amount_band are authored in
``data/raw/taxonomy.yaml`` (one coherent template per attack vector / benign flow).
This module rotates apps and renders concrete VND amounts deterministically, then
asserts the diversity-coverage targets across the full 30-row set (generated + gold).

The (attack_vector, banking_flow) key is unique by construction; the gold tuples are
reserved in the taxonomy and never echoed by the generated pool.
"""
from __future__ import annotations

import random
from typing import Any


def render_amount(amount_band: str, bands_map: dict[str, list[int]], rng: random.Random) -> str:
    """Pick a representative round VND value for a band and format it, or '' for none."""
    values = bands_map.get(amount_band) or []
    if not values:
        return ""
    return f"{rng.choice(values):,} VND"


def build_generated_specs(taxonomy: dict[str, Any], seed: int = 7) -> list[dict[str, Any]]:
    """Build the 27 generated scenario specs (18 suspicious + 9 benign)."""
    rng = random.Random(seed)
    prefixes = taxonomy["domains"]
    bands_map = taxonomy["amount_bands"]

    # Deterministic app rotation: shuffle once, then round-robin.
    apps = list(taxonomy["apps"])
    rng.shuffle(apps)

    rows: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    for s in taxonomy["suspicious_scenarios"]:
        raw.append({**s, "gold_label": "suspicious"})
    for s in taxonomy["benign_scenarios"]:
        raw.append({**s, "gold_label": "benign", "attack_vector": "none"})

    domain_counter: dict[str, int] = {}
    for i, s in enumerate(raw):
        domain = s["domain"]
        app = apps[i % len(apps)]
        amount = render_amount(s["amount_band"], bands_map, rng)
        scenario_en = s["template"].format(app=app, amount=amount).strip()

        domain_counter[domain] = domain_counter.get(domain, 0) + 1
        base_id = f"{prefixes[domain]}-{domain_counter[domain]:03d}"

        rows.append(
            {
                "base_id": base_id,
                "scenario_en": scenario_en,
                "gold_label": s["gold_label"],
                "domain": domain,
                "attack_vector": s.get("attack_vector", "none"),
                "banking_flow": s["banking_flow"],
                "app": app,
                "amount_band": s["amount_band"],
                "source": "generated",
            }
        )
    return rows


def assert_coverage(all_rows: list[dict[str, Any]]) -> None:
    """Fail loudly unless the full 30-row set hits every diversity target."""
    n = len(all_rows)
    assert n == 30, f"expected 30 scenarios, got {n}"

    susp = [r for r in all_rows if r["gold_label"] == "suspicious"]
    benign = [r for r in all_rows if r["gold_label"] == "benign"]
    assert len(susp) == 20, f"expected 20 suspicious, got {len(susp)}"
    assert len(benign) == 10, f"expected 10 benign, got {len(benign)}"

    vectors = {r["attack_vector"] for r in susp}
    assert len(vectors) >= 14, f"need >=14 distinct attack vectors, got {len(vectors)}: {sorted(vectors)}"

    susp_flows = {r["banking_flow"] for r in susp}
    assert len(susp_flows) >= 8, f"need >=8 distinct suspicious flows, got {len(susp_flows)}"

    benign_flows = {r["banking_flow"] for r in benign}
    assert len(benign_flows) >= 8, f"need >=8 distinct benign flows, got {len(benign_flows)}"

    tuples = [(r["attack_vector"], r["banking_flow"]) for r in all_rows]
    dupes = {t for t in tuples if tuples.count(t) > 1 and t[0] != "none"}
    assert not dupes, f"duplicate (vector, flow) tuples: {dupes}"

    apps = [r["app"] for r in all_rows]
    for app in set(apps):
        share = apps.count(app) / n
        assert share <= 0.40, f"app {app} exceeds 40% of rows ({share:.0%})"

    print(
        f"[diversity] OK: {n} rows | {len(susp)} susp / {len(benign)} benign | "
        f"{len(vectors)} vectors | susp_flows={len(susp_flows)} benign_flows={len(benign_flows)} | "
        f"max app share={max(apps.count(a) for a in set(apps)) / n:.0%}"
    )
