#!/usr/bin/env python3
"""
Sort a DiscordChatExporter JSON export (or a folder of them, one per
channel) into a clean /exams/<subject>/... folder structure, and write
an index.json describing every file for the static site to consume.

Usage:
    python sort_exams.py --export path/to/export --assets path/to/assets \
        --output ../exams --config config.json

    --export can be a single messages.json file, or a directory
    containing multiple *.json exports (typical when you export each
    course channel separately).

    --assets is the folder containing the downloaded attachment files
    (searched recursively). If you exported with DiscordChatExporter's
    asset-download option, point this at that folder.

Re-run this any time you export new Discord history - it is safe to
run repeatedly: existing files are matched by a stable name derived
from their content, so re-running does not create duplicates, it just
adds anything new and refreshes index.json.
"""

import argparse
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("sort_exams")

DEFAULT_CONFIG = {
    "subject_overrides": {},
    "channel_ignore_list": [],
    "month_term_map": {
        "1": "Winter", "2": "Winter", "3": "Winter",
        "4": "Spring", "5": "Spring", "6": "Spring",
        "7": "Summer", "8": "Summer",
        "9": "September", "10": "Fall", "11": "Fall", "12": "Fall",
    },
    "exam_type_keywords": {},
    "default_exam_type": "exam",
    "year_regex": r"\b(19|20)\d{2}\b",
}

MONTH_NAME_TO_NUM = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic"}
PDF_EXTS = {".pdf"}


def strip_comments(value):
    """Recursively drop any dict key that is or ends with '_comment', so
    config.json can carry human-readable notes without them leaking into
    keyword/mapping lookups."""
    if isinstance(value, dict):
        return {
            k: strip_comments(v)
            for k, v in value.items()
            if not (k == "_comment" or k.endswith("_comment"))
        }
    if isinstance(value, list):
        return [strip_comments(v) for v in value]
    return value


def load_config(path: Optional[Path]) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path and path.exists():
        with open(path, encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update(strip_comments(user_cfg))
    return cfg


def slugify(text: str) -> str:
    text = text.strip().replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9._-]", "", text)
    return text or "unknown"


def safe_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return text.strip(" .") or "file"


def find_year(text: str, regex: str) -> Optional[str]:
    m = re.search(regex, text)
    return m.group(0) if m else None


def find_month(text: str) -> Optional[int]:
    lowered = text.lower()
    for name, num in MONTH_NAME_TO_NUM.items():
        if re.search(rf"\b{name}\b", lowered):
            return num
    m = re.search(r"\b(0?[1-9]|1[0-2])[/-](19|20)\d{2}\b", lowered)
    if m:
        return int(m.group(1))
    return None


def find_exam_type(text: str, keywords: dict, default: str) -> tuple[str, str]:
    lowered = text.lower()
    for exam_type, aliases in keywords.items():
        for alias in aliases:
            if alias.lower() in lowered:
                return exam_type, "text"
    return default, "default"


@dataclass
class Entry:
    subject: str
    channel: str
    year: str
    year_source: str
    term: str
    term_source: str
    exam_type: str
    exam_type_source: str
    original_filename: str
    stored_path: str
    author: str
    author_id: str
    timestamp: str
    message_content: str
    file_size_bytes: Optional[int]
    file_kind: str
    message_id: str
    attachment_url: Optional[str] = None
    status: str = "ok"


def entry_key(entry: dict) -> str:
    """Stable identity for merging index.json across runs: Discord message
    ids are globally unique snowflakes, so message_id + filename is enough
    to dedupe/update the same attachment across repeated invocations."""
    return f"{entry.get('message_id')}:{entry.get('original_filename')}"


def file_kind_for(ext: str) -> str:
    ext = ext.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"


def build_asset_index(assets_dir: Path) -> dict:
    """Map every filename under assets_dir to its full path, so we can
    resolve DiscordChatExporter's downloaded attachments (which are
    sometimes prefixed with the attachment id) by exact or suffix match."""
    index: dict[str, list[Path]] = {}
    for p in assets_dir.rglob("*"):
        if p.is_file():
            index.setdefault(p.name, []).append(p)
    return index


def resolve_asset(filename: str, asset_index: dict) -> Optional[Path]:
    if filename in asset_index:
        return asset_index[filename][0]
    for name, paths in asset_index.items():
        if name.endswith(filename) or name.endswith("_" + filename):
            return paths[0]
    return None


def iter_export_files(export_path: Path):
    if export_path.is_dir():
        yield from sorted(export_path.glob("*.json"))
    else:
        yield export_path


def process_export_file(path: Path, cfg: dict, asset_index: dict,
                         output_dir: Path, dry_run: bool) -> list[Entry]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    channel_name = (data.get("channel") or {}).get("name", path.stem)
    if channel_name in cfg["channel_ignore_list"]:
        log.info("Skipping ignored channel: %s", channel_name)
        return []

    subject = cfg["subject_overrides"].get(channel_name, channel_name.replace("-", " ").title())
    entries: list[Entry] = []
    # Tracks dest_name -> attachment id already claimed *this run*, so a
    # re-run of the same export reuses the same name (and just overwrites
    # the file on disk) instead of treating its own prior output as a
    # collision and duplicating it with a -suffix each time.
    claimed_names: dict[str, str] = {}

    for msg in data.get("messages", []):
        attachments = msg.get("attachments") or []
        if not attachments:
            continue

        content = msg.get("content") or ""
        timestamp = msg.get("timestamp", "")
        author = (msg.get("author") or {}).get("name", "unknown")
        author_id = (msg.get("author") or {}).get("id", "")

        year = find_year(content, cfg["year_regex"])
        year_source = "text"
        if not year:
            year = timestamp[:4] if len(timestamp) >= 4 else "unknown-year"
            year_source = "timestamp"

        month = find_month(content)
        term_source = "text"
        if month is None:
            try:
                month = int(timestamp[5:7])
                term_source = "timestamp"
            except (ValueError, IndexError):
                month = None
                term_source = "unknown"
        term = cfg["month_term_map"].get(str(month), "unspecified") if month else "unspecified"

        exam_type, exam_type_source = find_exam_type(
            content, cfg["exam_type_keywords"], cfg["default_exam_type"]
        )

        subject_dir = output_dir / slugify(subject)

        for att in attachments:
            original_filename = att.get("fileName") or att.get("url", "").split("/")[-1]
            ext = Path(original_filename).suffix
            stem = Path(safe_filename(original_filename)).stem

            attachment_key = att.get("id") or f"{msg.get('id', '')}:{original_filename}"
            dest_name = f"{year}-{term}-{exam_type}-{stem}{ext}"

            if claimed_names.get(dest_name, attachment_key) != attachment_key:
                short_id = attachment_key[-6:]
                dest_name = f"{year}-{term}-{exam_type}-{stem}-{short_id}{ext}"
            claimed_names[dest_name] = attachment_key
            dest_path = subject_dir / dest_name

            resolved = resolve_asset(original_filename, asset_index) if asset_index else None
            status = "ok"
            if resolved:
                if not dry_run:
                    subject_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(resolved, dest_path)
            else:
                status = "missing_file"
                log.warning("Could not find local asset for '%s' (msg %s)",
                            original_filename, msg.get("id"))

            entries.append(Entry(
                subject=subject,
                channel=channel_name,
                year=year,
                year_source=year_source,
                term=term,
                term_source=term_source,
                exam_type=exam_type,
                exam_type_source=exam_type_source,
                original_filename=original_filename,
                stored_path=f"{slugify(subject)}/{dest_name}" if status == "ok" else "",
                author=author,
                author_id=author_id,
                timestamp=timestamp,
                message_content=content,
                file_size_bytes=att.get("fileSizeBytes"),
                file_kind=file_kind_for(ext),
                message_id=msg.get("id", ""),
                attachment_url=att.get("url"),
                status=status,
            ))

    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", required=True, type=Path,
                         help="Path to a messages.json export, or a directory of them (one per channel)")
    parser.add_argument("--assets", type=Path, default=None,
                         help="Folder of downloaded attachment files, searched recursively")
    parser.add_argument("--output", type=Path, default=Path("exams"),
                         help="Output folder for the sorted /exams tree (default: ./exams)")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.json",
                         help="Path to config.json (default: scripts/config.json)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would happen without copying files or writing index.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    asset_index = build_asset_index(args.assets) if args.assets else {}
    if args.assets and not asset_index:
        log.warning("No files found under assets dir: %s", args.assets)

    all_entries: list[Entry] = []
    export_files = list(iter_export_files(args.export))
    if not export_files:
        log.error("No JSON export files found at %s", args.export)
        sys.exit(1)

    for export_file in export_files:
        log.info("Processing %s", export_file)
        entries = process_export_file(export_file, cfg, asset_index, args.output, args.dry_run)
        all_entries.extend(entries)

    ok = sum(1 for e in all_entries if e.status == "ok")
    missing = sum(1 for e in all_entries if e.status == "missing_file")
    log.info("Done: %d files sorted, %d missing on disk", ok, missing)

    if args.dry_run:
        log.info("Dry run - not writing index.json")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    index_path = args.output / "index.json"

    # Merge into any existing index.json rather than overwriting it, so
    # running this script against just one newly-exported channel (rather
    # than the full export folder) doesn't drop previously indexed
    # channels whose files are still sitting on disk.
    merged: dict[str, dict] = {}
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            existing = json.load(f)
        for e in existing.get("files", []) + existing.get("missing", []):
            merged[entry_key(e)] = e

    for e in all_entries:
        merged[entry_key(e.__dict__)] = e.__dict__

    index_data = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "files": [e for e in merged.values() if e["status"] == "ok"],
        "missing": [e for e in merged.values() if e["status"] == "missing_file"],
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s (%d files, %d missing)", index_path, len(index_data["files"]), len(index_data["missing"]))


if __name__ == "__main__":
    main()
