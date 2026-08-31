from __future__ import annotations

import argparse

from api.dependencies import get_repository, get_vector_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the configured vector index from SQLite chunks.")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")

    vector_index = get_vector_index()
    if vector_index is None:
        raise SystemExit("RETRIEVAL_BACKEND is local; set it to qdrant before reindexing")
    chunks = get_repository().list_ready_chunks()
    if not chunks:
        print("No ready chunks were found.")
        return
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        vector_index.upsert(batch)
        print(f"Indexed {min(start + len(batch), len(chunks))}/{len(chunks)} chunks")
    print("Vector reindex completed.")


if __name__ == "__main__":
    main()

