"""Module clustering via export-centric TF-IDF + Leiden community detection."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

_SUFFIX_RE = re.compile(r"(?:ExW|ExA|Ex|W|A)$")


def _tokenize_function_name(name: str) -> list[str]:
    """Split a Win32 function name into lowercase semantic tokens."""
    if "!" in name:
        name = name.split("!", 1)[1]

    name = _SUFFIX_RE.sub("", name)

    tokens = []
    for part in name.split("_"):
        for match in _CAMEL_RE.finditer(part):
            tok = match.group().lower()
            if len(tok) > 1 and not tok.isdigit():
                tokens.append(tok)

    return tokens


def compute_module_clusters(neo4j_loader, *, anthropic_api_key: str | None = None) -> dict:
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        raise ImportError("scikit-learn is required: pip install scikit-learn") from e

    try:
        import igraph as ig
    except ImportError as e:
        raise ImportError("igraph is required: pip install igraph") from e

    records = neo4j_loader.query(
        "MATCH (caller:Function)-[r]->(callee:Function) "
        "WHERE caller.module <> callee.module "
        "RETURN callee.module AS module, "
        "       callee.name AS function_name, "
        "       caller.module AS caller_module, "
        "       type(r) AS edge_type, "
        "       count(*) AS weight"
    )

    if not records:
        raise ValueError("No cross-module edges found in Neo4j.")

    module_exports: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    module_callers: dict[str, set[str]] = defaultdict(set)
    all_modules: set[str] = set()

    for rec in records:
        module = rec["module"]
        func = rec["function_name"] or ""
        caller = rec["caller_module"]
        weight = rec["weight"] or 1

        all_modules.add(module)
        all_modules.add(caller)

        if "!" in func:
            func = func.split("!", 1)[1]

        if func:
            module_exports[module][func] += weight
        module_callers[module].add(caller)

    # Fallback: modules with no incoming cross-module edges use their own function names
    modules_with_exports = set(module_exports.keys())
    modules_without_exports = all_modules - modules_with_exports

    if modules_without_exports:
        fallback_records = neo4j_loader.query(
            "MATCH (f:Function) "
            "WHERE f.module IN $modules "
            "RETURN f.module AS module, collect(DISTINCT f.name) AS own_functions",
            parameters={"modules": sorted(modules_without_exports)},
        )

        for rec in fallback_records or []:
            module = rec["module"]
            for func in rec["own_functions"] or []:
                if func and "!" in func:
                    func = func.split("!", 1)[1]
                if func:
                    module_exports[module][func] = 1

    n_modules = len(all_modules)
    if n_modules < 3:
        raise ValueError(f"Too few modules for clustering ({n_modules}). Need at least 3.")

    sorted_modules = sorted(all_modules)
    documents = []

    for module in sorted_modules:
        terms: list[str] = []

        for func, weight in module_exports.get(module, {}).items():
            tokens = _tokenize_function_name(func)
            repeat = min(weight, 10)
            for _ in range(repeat):
                terms.extend(tokens * 3)

            clean_name = func.lower()
            if len(clean_name) > 1:
                terms.append(clean_name)

        for caller in module_callers.get(module, set()):
            terms.append(f"caller:{caller}")

        if not terms:
            terms.append(module.lower())

        documents.append(" ".join(terms))

    logger.info(
        "Feature extraction: %d modules (%d with exports, %d fallback), %d total terms",
        len(sorted_modules),
        len(modules_with_exports),
        len(modules_without_exports),
        sum(len(d.split()) for d in documents),
    )

    vectorizer = TfidfVectorizer(
        sublinear_tf=True,
        min_df=2,
        max_df=0.80,
        token_pattern=r"[^\s]+",
        norm="l2",
    )
    tfidf_matrix = vectorizer.fit_transform(documents)

    logger.info(
        "TF-IDF matrix: %d modules x %d features",
        tfidf_matrix.shape[0],
        tfidf_matrix.shape[1],
    )

    sim_matrix = cosine_similarity(tfidf_matrix)

    k = min(15, len(sorted_modules) - 1)
    threshold = 0.01

    edge_dict: dict[tuple[int, int], float] = {}
    for i in range(len(sorted_modules)):
        sims = sim_matrix[i].copy()
        sims[i] = -1
        top_k = np.argsort(sims)[-k:]

        for j in top_k:
            if sims[j] > threshold:
                key = (min(i, j), max(i, j))
                if key not in edge_dict or sims[j] > edge_dict[key]:
                    edge_dict[key] = float(sims[j])

    edges = list(edge_dict.keys())
    weights = [edge_dict[e] for e in edges]

    g = ig.Graph(n=len(sorted_modules), edges=edges, directed=False)
    g.es["weight"] = weights

    partition = g.community_leiden(
        objective_function="modularity",
        weights="weight",
        resolution=1.0,
        n_iterations=-1,
    )

    labels = np.array(partition.membership)
    n_clusters = int(labels.max()) + 1 if len(labels) > 0 else 0

    logger.info(
        "Leiden: %d clusters from %d modules (graph: %d edges)",
        n_clusters,
        len(sorted_modules),
        len(edges),
    )

    feature_names = vectorizer.get_feature_names_out()

    assignments: dict[str, int] = {}
    for i, mod in enumerate(sorted_modules):
        assignments[mod] = int(labels[i])

    clusters = []
    for cid in range(n_clusters):
        member_indices = [i for i in range(len(sorted_modules)) if labels[i] == cid]
        cluster_modules = [sorted_modules[i] for i in member_indices]

        char_functions = _ctfidf_characteristic_functions(
            tfidf_matrix,
            member_indices,
            feature_names,
            top_n=10,
        )

        clusters.append(
            {
                "id": cid,
                "modules": cluster_modules,
                "characteristic_functions": char_functions,
            }
        )

    labeled = _label_clusters(clusters, anthropic_api_key)

    return {
        "assignments": assignments,
        "clusters": clusters,
        "noise_modules": [],
        "n_modules": n_modules,
        "n_functions": len(feature_names),
        "n_clusters": n_clusters,
        "labeled": labeled,
    }


def _ctfidf_characteristic_functions(
    tfidf_matrix,
    member_indices: list[int],
    feature_names,
    top_n: int = 10,
) -> list[str]:
    """Top terms for a cluster: mean TF-IDF minus global mean, ranked by difference."""
    import numpy as np

    if not member_indices:
        return []

    cluster_mean = np.asarray(tfidf_matrix[member_indices].mean(axis=0)).flatten()
    global_mean = np.asarray(tfidf_matrix.mean(axis=0)).flatten()

    scores = cluster_mean - global_mean

    top_indices = np.argsort(scores)[::-1][:top_n]

    result = []
    for idx in top_indices:
        if scores[idx] <= 0:
            break
        term = feature_names[idx]
        if term.startswith("caller:"):
            continue
        result.append(term)

    return result


def _label_clusters(clusters: list[dict], api_key: str | None = None) -> bool:
    import json

    if not api_key:
        logger.debug("No Anthropic API key, skipping cluster labeling")
        return False

    try:
        import anthropic
    except ImportError:
        logger.debug("anthropic package not installed, skipping cluster labeling")
        return False

    cluster_lines = []
    for c in clusters:
        mods = ", ".join(c["modules"][:15])
        if len(c["modules"]) > 15:
            mods += f", ... ({len(c['modules'])} total)"
        funcs = ", ".join(c["characteristic_functions"][:7])
        cluster_lines.append(f"Cluster {c['id']}: modules=[{mods}], characteristic_exports=[{funcs}]")

    prompt = (
        "You are analyzing Windows PE binary module clusters discovered by "
        "export-centric TF-IDF + Leiden community detection.\n\n"
        "Modules are clustered by the functions they **export** (provide to other "
        "modules), not by what they import. The characteristic terms are:\n"
        "- Lowercase tokens from CamelCase-split exported function names "
        "(e.g. 'crypt', 'encode', 'query', 'nt', 'reg')\n"
        "- Full function names in lowercase (e.g. 'ntcreatefile')\n\n"
        "For each cluster below, provide:\n"
        '- label: a short name (2-4 words, e.g. "Kernel Memory Management")\n'
        "- description: one sentence explaining what these modules provide\n\n"
        + "\n".join(cluster_lines)
        + "\n\nRespond with a JSON array of objects, one per cluster, each with "
        '"id" (int), "label" (string), and "description" (string). '
        "Return ONLY the JSON array, no other text."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=16384,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        labels = json.loads(text)
        label_map = {item["id"]: item for item in labels}

        for c in clusters:
            info = label_map.get(c["id"], {})
            c["label"] = info.get("label", "")
            c["description"] = info.get("description", "")

        logger.info("Labeled %d clusters via Claude", len(clusters))
        return True
    except Exception:
        logger.debug("Cluster labeling failed", exc_info=True)
        return False
