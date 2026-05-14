"""run_clustering tool — k-means on lancedb embedding vectors."""

import json
from pathlib import Path

_LANCE_PATH = str(Path(__file__).parent.parent.parent / "lancedb")
_VALID_TABLES = {"videos", "searches", "google_searches"}


def run_clustering(table: str, n_clusters: int = 5) -> str:
    """k-means on lancedb embedding vectors. Returns cluster summary + nearest examples.

    Args:
        table:      lancedb table: 'videos', 'searches', or 'google_searches'.
        n_clusters: Number of k-means clusters (default 5).

    Memory note: full table scan via tbl.to_pandas() — ~35 MB for 5,790 videos.
    Returns [RAW-COMPUTED] tagged JSON.
    """
    if table not in _VALID_TABLES:
        return f"[RAW-COMPUTED] ERROR: table must be one of {sorted(_VALID_TABLES)}. Got {table!r}."
    if n_clusters < 2:
        return "[RAW-COMPUTED] ERROR: n_clusters must be >= 2."

    try:
        import lancedb
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score

        db  = lancedb.connect(_LANCE_PATH)
        tbl = db.open_table(table)
        df  = tbl.to_pandas()

        if "vector" not in df.columns:
            return f"[RAW-COMPUTED] ERROR: No 'vector' column in lancedb table {table!r}."

        vectors = np.stack(df["vector"].values)
        n_rows  = len(vectors)

        if n_clusters > n_rows:
            return (
                f"[RAW-COMPUTED] ERROR: n_clusters ({n_clusters}) exceeds row count "
                f"({n_rows}). Use n_clusters <= {n_rows}."
            )

        km     = KMeans(n_clusters=n_clusters, n_init=3, max_iter=100, random_state=42)
        labels = km.fit_predict(vectors)
        df["_cluster"] = labels

        sil = (
            float(silhouette_score(vectors, labels))
            if n_rows >= n_clusters * 2
            else None
        )

        clusters_out = []
        for c in range(n_clusters):
            mask    = df["_cluster"] == c
            members = df[mask]
            centroid = km.cluster_centers_[c]
            dists    = np.linalg.norm(vectors[mask.values] - centroid, axis=1)
            top_idx  = dists.argsort()[:3]
            examples = []
            for i in top_idx:
                row = members.iloc[i]
                if table == "videos":
                    lbl = f"{row.get('title', row.get('video_id', '?'))} — {row.get('channel', '')}"
                else:
                    lbl = str(row.get("query", "?"))
                examples.append(lbl[:80])
            clusters_out.append({
                "cluster":          c,
                "size":             int(mask.sum()),
                "nearest_examples": examples,
            })

        result = {
            "table":            table,
            "n_clusters":       n_clusters,
            "n_rows":           n_rows,
            "silhouette_score": round(sil, 3) if sil is not None else None,
            "clusters":         clusters_out,
        }
        return f"[RAW-COMPUTED]\n{json.dumps(result, indent=2)}"

    except ImportError as e:
        return f"[RAW-COMPUTED] ERROR: Missing dependency — {e}. Run: pip install scikit-learn lancedb"
    except Exception as e:
        return f"[RAW-COMPUTED] ERROR: {e}"
