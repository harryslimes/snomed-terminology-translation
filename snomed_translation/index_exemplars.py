"""CLI: ``python -m snomed_translation.index_exemplars --source <id>``.

Embeds a registered data source's (en, target) pairs with BGE-M3 and indexes
them into the source's per-content Qdrant collection (see
:mod:`snomed_translation.exemplars`). Idempotent: a complete collection returns
immediately; an interrupted index resumes; superseded collections for the
same source are dropped. The wizard's Sources page drives this same entry
point as a tracked run job.
"""
from __future__ import annotations

import argparse
import logging
import sys

from snomed_translation.assemble import (
    AssemblyError,
    Registries,
    load_investigation,
    resolve_environment,
)
from snomed_translation.exemplars import ExemplarError, index_source


def main() -> int:
    p = argparse.ArgumentParser(
        description="Index a data source's exemplar embeddings into Qdrant.")
    p.add_argument("--source", required=True,
                   help="Source id (configs/sources/<id>.json).")
    p.add_argument("--investigation", "--project", dest="investigation",
                   default="project",
                   help="Investigation whose environment supplies language + "
                        "Qdrant settings (--project is a deprecated alias).")
    p.add_argument("--configs-dir", default="configs")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("snomed_translation.index_exemplars")

    try:
        inv = load_investigation(args.investigation, args.configs_dir)
        environment = resolve_environment(inv, args.configs_dir)
        registries = Registries.load()
    except AssemblyError as exc:
        log.error("%s", exc)
        return 1
    spec = registries.sources.get(args.source)
    if spec is None:
        log.error("unknown source %r; available: %s",
                  args.source, sorted(registries.sources))
        return 1

    try:
        result = index_source(spec, environment.language.code,
                              environment.qdrant.url,
                              environment.qdrant.bgem3.model_name)
    except ExemplarError as exc:
        log.error("%s", exc)
        return 1
    log.info("Done: collection %r holds %d points",
             result["collection"], result["points"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
