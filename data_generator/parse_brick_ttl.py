#!/usr/bin/env python3
"""
ACME Co. Autonomous Building Operations (ABO)
Semantic Ontology Parser (`parse_brick_ttl.py`)
===============================================
Extracts generalized ACME Co. equipment, spatial, BACnet network/controller,
and point entities from `ec_building_brick.ttl` for the BigQuery Property Graph.
"""

from pathlib import Path
from typing import Any, Dict
import sys

# Reuse the canonical parser from Source Data / data_generator
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Source Data"))
from generate_acme_demo_data import parse_ttl, clean_brand, TTL_PATH  # noqa: E402


def summarize_ontology(ttl_path: Path = TTL_PATH) -> Dict[str, Any]:
    entities = parse_ttl(ttl_path)
    points = [k for k in entities if "__" in k]
    controllers = [
        k
        for k, v in entities.items()
        if any(
            t in ("bsm:Controller", "bsm:Router", "bacnet:BACnetDevice", "bsm:InferredNetworkDevice")
            for t in v["rdf_types"]
        )
    ]
    networks = [k for k, v in entities.items() if "bsm:Network" in v["rdf_types"]]
    programs = [k for k, v in entities.items() if "bsm:Program" in v["rdf_types"]]
    return {
        "total_subject_blocks": len(entities),
        "points_count": len(points),
        "controllers_and_inferred_hubs_count": len(controllers),
        "networks_count": len(networks),
        "programs_count": len(programs),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summarize_ontology(), indent=2))

