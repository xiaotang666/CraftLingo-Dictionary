#!/usr/bin/env python3
"""Build the enhanced i18n dictionary release artifacts.

Merge order: own dictionary first, then the VM dictionary overwrites conflicts
(VM wins). Outputs, into --out:

  full-<tag>.db.zst          compressed full SQLite database
  inc-<from>-<to>.sql.zst    per-baseline incremental SQL script
  manifest.json              consumed by the desktop client

The script is idempotent: if the merged content hash matches the existing
manifest it exits 0 without writing anything, so CI does not publish a release.

Usage:
  python build_dict.py --vm-dict vm/Dict.json --own-dict sources/own-dict.json \
      --out dist --tag 2026-11-23
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

KEEP_ASSETS = 10  # 1 full + 9 increments
MAX_INCREMENT_BASELINES = KEEP_ASSETS - 1
SCHEMA = """
CREATE TABLE dict(
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    ORIGIN_NAME TEXT NOT NULL,
    TRANS_NAME TEXT NOT NULL,
    MODID TEXT NOT NULL,
    KEY TEXT NOT NULL,
    VERSION TEXT NOT NULL,
    CURSEFORGE TEXT NOT NULL
);
CREATE INDEX dict_index ON dict(ORIGIN_NAME);
"""


def pick(item: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty field among aliases (VM uses snake_case)."""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


OWN_ORIGIN_KEYS = ("ORIGIN_NAME", "originName", "origin_name", "term", "source_text")
OWN_TRANS_KEYS = ("TRANS_NAME", "transName", "trans_name", "translation", "target")


def row_from_item(item: dict[str, Any]) -> dict[str, str]:
    return {
        "origin": pick(item, *OWN_ORIGIN_KEYS).strip(),
        "trans": pick(item, *OWN_TRANS_KEYS).strip(),
        "modid": pick(item, "MODID", "modid", "mod_id"),
        "key": pick(item, "KEY", "key"),
        "version": pick(item, "VERSION", "version"),
        "curseforge": pick(item, "CURSEFORGE", "curseforge"),
    }


def parse_entries(data: Any) -> list[dict[str, str]]:
    """Normalize one JSON payload into rows, tolerating several schemas."""
    if isinstance(data, dict):
        if "entries" in data:
            data = data["entries"] or []
        elif any(key in data for key in OWN_ORIGIN_KEYS):
            # A single entry object (e.g. one line of a .jsonl file).
            return [row_from_item(data)]
        elif data and all(isinstance(v, str) for v in data.values()):
            # A plain {source: translation} mapping.
            return [
                {"origin": str(k).strip(), "trans": v.strip(), "modid": "", "key": "", "version": "", "curseforge": ""}
                for k, v in data.items()
            ]
        else:
            return []
    if not isinstance(data, list):
        return []
    return [row_from_item(item) for item in data if isinstance(item, dict)]


def load_file(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, str]] = []
        for line in text.splitlines():
            if line.strip():
                rows.extend(parse_entries(json.loads(line)))
        return rows
    return parse_entries(json.loads(text))


def dict_files(path: Path) -> list[Path]:
    """Accept a single file or a directory (e.g. dictionary/latest)."""
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".jsonl"))
    return [path] if path.is_file() else []


def load_entries(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for file in dict_files(path):
        rows.extend(load_file(file))
    return rows


def merge(own: list[dict[str, str]], vm: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for row in own:
        if row["origin"] and row["trans"]:
            merged[row["origin"].casefold()] = row
    for row in vm:
        if row["origin"] and row["trans"]:
            merged[row["origin"].casefold()] = row
    return merged


def content_hash(rows: dict[str, dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for key in sorted(rows):
        row = rows[key]
        digest.update(
            f"{row['origin']}\t{row['trans']}\t{row['modid']}\t{row['key']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def write_db(path: Path, rows: dict[str, dict[str, str]]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO dict(ORIGIN_NAME, TRANS_NAME, MODID, KEY, VERSION, CURSEFORGE)"
            " VALUES(?,?,?,?,?,?)",
            [
                (r["origin"], r["trans"], r["modid"], r["key"], r["version"], r["curseforge"])
                for r in rows.values()
            ],
        )
        conn.commit()
    finally:
        conn.close()


def zstd_compress(src: Path, dest: Path) -> None:
    import zstandard as zstd  # type: ignore

    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dest.open("wb") as fout:
        cctx = zstd.ZstdCompressor(level=10)
        cctx.copy_stream(fin, fout)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_db_rows(path: Path) -> dict[str, tuple[str, str, str, str]]:
    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute(
            "SELECT ORIGIN_NAME, TRANS_NAME, MODID, KEY FROM dict"
        )
        return {
            str(origin).casefold(): (str(origin), str(trans), str(modid), str(key))
            for origin, trans, modid, key in cursor.fetchall()
        }
    finally:
        conn.close()


def sql_escape(value: str) -> str:
    return value.replace("'", "''")


def build_increment(previous_db: Path, current_rows: dict[str, dict[str, str]]) -> str:
    previous = read_db_rows(previous_db)
    lines: list[str] = []
    for key, row in current_rows.items():
        old = previous.get(key)
        if old is None or old[1] != row["trans"]:
            # Delete first: ORIGIN_NAME has no UNIQUE constraint, so a plain
            # INSERT OR REPLACE would append a duplicate row instead of
            # replacing the existing translation.
            lines.append(
                "DELETE FROM dict WHERE ORIGIN_NAME = '{}';".format(
                    sql_escape(row["origin"])
                )
            )
            lines.append(
                "INSERT INTO dict(ORIGIN_NAME, TRANS_NAME, MODID, KEY, VERSION, CURSEFORGE)"
                " VALUES('{}','{}','{}','{}','{}','{}');".format(
                    sql_escape(row["origin"]),
                    sql_escape(row["trans"]),
                    sql_escape(row["modid"]),
                    sql_escape(row["key"]),
                    sql_escape(row["version"]),
                    sql_escape(row["curseforge"]),
                )
            )
    for key in previous.keys() - current_rows.keys():
        origin = previous[key][0]
        lines.append(f"DELETE FROM dict WHERE ORIGIN_NAME = '{sql_escape(origin)}';")
    return "\n".join(lines) + ("\n" if lines else "")


def prune(out: Path, current_tag: str) -> None:
    fulls = sorted(out.glob("full-*.db.zst"), key=lambda p: p.name, reverse=True)
    for stale in fulls[KEEP_ASSETS:]:
        stale.unlink()
    incs = sorted(out.glob("inc-*.sql.zst"), key=lambda p: p.name, reverse=True)
    for stale in incs[MAX_INCREMENT_BASELINES:]:
        stale.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vm-dict", required=True)
    parser.add_argument(
        "--own-dict",
        action="append",
        help="自有汉化库文件或目录（可重复，目录会递归读取其中的 .json/.jsonl）。"
        "默认 sources/own-dict.json",
    )
    parser.add_argument("--out", default="dist")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    previous_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    own_rows: list[dict[str, str]] = []
    for own_path in args.own_dict or ["sources/own-dict.json"]:
        files = dict_files(Path(own_path))
        if Path(own_path).is_dir() and not files:
            print(f"warning: no dictionary files under {own_path}", file=sys.stderr)
        for file in files:
            own_rows.extend(load_file(file))
    rows = merge(own_rows, load_entries(Path(args.vm_dict)))
    if not rows:
        print("no entries to publish", file=sys.stderr)
        return 1

    digest = content_hash(rows)
    if previous_manifest.get("contentHash") == digest:
        print("dictionary content unchanged; skipping release")
        return 0

    full_name = f"full-{args.tag}.db.zst"
    full_path = out / full_name
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "Dict-Sqlite.db"
        write_db(db_path, rows)
        zstd_compress(db_path, full_path)

        # Increments from every retained full database baseline.
        previous_fulls = sorted(
            [p for p in out.glob("full-*.db.zst") if p.name != full_name],
            key=lambda p: p.name,
            reverse=True,
        )[:MAX_INCREMENT_BASELINES]
        increments = []
        import zstandard as zstd  # type: ignore

        for older in previous_fulls:
            from_tag = older.name[len("full-") : -len(".db.zst")]
            older_db = Path(tmp) / f"old-{from_tag}.db"
            with zstd.ZstdDecompressor().stream_reader(older.open("rb")) as reader, older_db.open(
                "wb"
            ) as fout:
                fout.write(reader.read())
            sql = build_increment(older_db, rows)
            inc_name = f"inc-{from_tag}-{args.tag}.sql.zst"
            inc_path = out / inc_name
            sql_path = Path(tmp) / inc_name.replace(".zst", "")
            sql_path.write_text(sql, encoding="utf-8")
            zstd_compress(sql_path, inc_path)
            increments.append(
                {
                    "fromTag": from_tag,
                    "url": f"{args.base_url.rstrip('/')}/{inc_name}" if args.base_url else inc_name,
                    "sha256": sha256_file(inc_path),
                    "size": inc_path.stat().st_size,
                    "compression": "zstd",
                }
            )

    manifest = {
        "schemaVersion": 1,
        "tag": args.tag,
        "name": args.name or f"CraftLingo 增强词典 {args.tag}",
        "publishedAt": f"{args.tag}T00:00:00+08:00",
        "entryCount": len(rows),
        "contentHash": digest,
        "full": {
            "url": f"{args.base_url.rstrip('/')}/{full_name}" if args.base_url else full_name,
            "sha256": sha256_file(full_path),
            "size": full_path.stat().st_size,
            "compression": "zstd",
        },
        "increments": increments,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prune(out, args.tag)
    print(f"published {args.tag}: {len(rows)} entries, {len(increments)} increments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
