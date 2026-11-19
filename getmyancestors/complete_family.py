"""Explore every FamilySearch person connected by parent, child or couple links.

The crawl keeps an SQLite checkpoint so that it can resume without revisiting
people already fetched. It deliberately imposes no *generation* boundaries.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from threading import RLock

from getmyancestors.classes.session import Session
from getmyancestors.classes.tree import Tree

PERSON_URL = "/platform/tree/persons?pids="
PERSON_ID = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{3}\Z")
RELATIONSHIP_FIELDS = ("childAndParentsRelationships", "relationships")
MEMBER_FIELDS = ("parent1", "parent2", "child", "person1", "person2")


def related_people(document):
    """Find endpoints in *all* parent/child and couple relationships."""
    found = set()
    for kind in RELATIONSHIP_FIELDS:
        for relationship in document.get(kind, []):
            for field in MEMBER_FIELDS:
                member = relationship.get(field)
                if isinstance(member, dict):
                    identifier = member.get("resourceId")
                    if identifier and PERSON_ID.fullmatch(identifier):
                        found.add(identifier)
    return found


class Checkpoint:
    """Persistent discovery queue and successful FamilySearch responses."""

    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        os.chmod(self.path, 0o600)
        with self.lock, self.connection:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS people "
                "(fid TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending')"
            )
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS responses "
                "(request_key TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )

    def close(self):
        with self.lock:
            self.connection.close()

    def seed(self, ids):
        with self.lock, self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO people (fid) VALUES (?)",
                ((fid,) for fid in ids),
            )

    def retry_failed(self):
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE people SET status = 'pending' WHERE status = 'failed'"
            )

    def next_pending(self):
        with self.lock:
            row = self.connection.execute(
                "SELECT fid FROM people WHERE status = 'pending' "
                "ORDER BY rowid LIMIT 1"
            ).fetchone()
        return row[0] if row else None

    def count(self, status):
        with self.lock:
            return self.connection.execute(
                "SELECT COUNT(*) FROM people WHERE status = ?", (status,)
            ).fetchone()[0]

    def completed_ids(self):
        with self.lock:
            return [
                row[0]
                for row in self.connection.execute(
                    "SELECT fid FROM people WHERE status = 'done' ORDER BY rowid"
                )
            ]

    def get_response(self, key):
        with self.lock:
            row = self.connection.execute(
                "SELECT data FROM responses WHERE request_key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_response(self, key, document):
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO responses (request_key, data) VALUES (?, ?)",
                (key, json.dumps(document, ensure_ascii=False)),
            )

    def finish(self, fid, discovered):
        with self.lock, self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO people (fid) VALUES (?)",
                ((person,) for person in sorted(discovered) if person != fid),
            )
            self.connection.execute(
                "UPDATE people SET status = 'done' WHERE fid = ?", (fid,)
            )

    def fail(self, fid):
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE people SET status = 'failed' WHERE fid = ?", (fid,)
            )


def crawl(checkpoint, session, max_people=1000, progress=25):
    """Breadth-first walk; max_people=0 removes the safety cap.

    Return True only if the reachable queue has been exhausted without failures.
    """
    while max_people == 0 or checkpoint.count("done") < max_people:
        fid = checkpoint.next_pending()
        if fid is None:
            break
        key = PERSON_URL + fid
        document = checkpoint.get_response(key)
        if document is None:
            document = session.get_url(key)
            if document is not None:
                checkpoint.save_response(key, document)
        if not document or not any(
            person.get("id") == fid for person in document.get("persons", [])
        ):
            checkpoint.fail(fid)
            print(f"Could not retrieve {fid}; will retry on a future run.", file=sys.stderr)
            continue
        discovered = related_people(document)
        checkpoint.finish(fid, discovered)
        done = checkpoint.count("done")
        if progress and done % progress == 0:
            print(
                f"Explored {done} people, "
                f"{checkpoint.count('pending')} still to explore.",
                file=sys.stderr,
            )
    return checkpoint.count("pending") == 0 and checkpoint.count("failed") == 0


def _combined_documents(documents):
    """Recreate the batch response expected by Tree.add_indis from cached pages."""
    combined = {key: [] for key in ("persons", *RELATIONSHIP_FIELDS, "places")}
    seen = {key: set() for key in combined}
    for document in documents:
        for key in combined:
            for item in document.get(key, []):
                marker = item.get("id") or json.dumps(item, sort_keys=True)
                if marker not in seen[key]:
                    seen[key].add(marker)
                    combined[key].append(item)
    return combined


class ReplaySession:
    """Expose cached person responses to the original GEDCOM exporter."""

    def __init__(self, session, checkpoint):
        self.session = session
        self.checkpoint = checkpoint

    def __getattr__(self, name):
        return getattr(self.session, name)

    def get_url(self, url, headers=None, no_api=False):
        if url.startswith(PERSON_URL):
            ids = url[len(PERSON_URL):].split(",")
            documents = []
            for fid in ids:
                document = self.checkpoint.get_response(PERSON_URL + fid)
                if document is None:
                    raise RuntimeError(f"Missing cached person {fid}")
                documents.append(document)
            return _combined_documents(documents)

        accept = headers.get("Accept", "") if headers else ""
        key = f"{int(no_api)}:{accept}:{url}"
        document = self.checkpoint.get_response(key)
        if document is None:
            document = self.session.get_url(url, headers, no_api)
            if document is not None:
                self.checkpoint.save_response(key, document)
        return document


def assemble(checkpoint, session, output, workers=2, no_notes=False, no_sources=False):
    """Build a GEDCOM snapshot from the fetched part of the connected graph."""
    ids = checkpoint.completed_ids()
    if not ids:
        return 0, 0
    tree = Tree(ReplaySession(session, checkpoint), no_sources=no_sources)
    tree.add_indis(ids)

    # The normal program makes these links while traversing. Recreate them
    # after all accessible person records have been loaded into the tree.
    for fid, person in list(tree.indi.items()):
        relationships = set(person.parents)
        relationships.update(
            (father, mother)
            for father, mother, child in person.children
            if child == fid
        )
        for father, mother in relationships:
            father = father if father in tree.indi else None
            mother = mother if mother in tree.indi else None
            if father or mother:
                tree.add_trio(father, mother, fid)
        for father, mother, child in person.children:
            if child not in tree.indi:
                continue
            father = father if father in tree.indi else None
            mother = mother if mother in tree.indi else None
            if father or mother:
                tree.add_trio(father, mother, child)

    seen_couples = set()
    for person in tree.indi.values():
        for first, second, relationship_id in person.spouses:
            if first not in tree.indi or second not in tree.indi:
                continue
            pair_key = frozenset((first, second))
            if pair_key in seen_couples:
                continue
            seen_couples.add(pair_key)
            if (first, second) in tree.fam:
                pair = (first, second)
            elif (second, first) in tree.fam:
                pair = (second, first)
            else:
                pair = (first, second)
                tree.add_fam(*pair)
            tree.indi[first].add_fams(pair)
            tree.indi[second].add_fams(pair)
            if relationship_id:
                tree.fam[pair].add_marriage(relationship_id)

    if not no_notes:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(person.get_notes) for person in tree.indi.values()
            ]
            futures.extend(
                executor.submit(family.get_notes) for family in tree.fam.values()
            )
            for future in futures:
                future.result()

    tree.reset_num()
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        tree.print(file)
    temporary.replace(output)
    return len(tree.indi), len(tree.fam)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Explore all accessible FamilySearch relatives in every direction."
    )
    parser.add_argument("-i", "--individual", required=True, help="FamilySearch person ID")
    parser.add_argument("-o", "--output", required=True, type=Path, help="Output GEDCOM")
    parser.add_argument(
        "--database", type=Path,
        help="Persistent SQLite checkpoint (defaults to output with .sqlite suffix)"
    )
    parser.add_argument(
        "--max-people", type=int, default=1000,
        help="Pause after this many people; 0 means no cap (potentially enormous)"
    )
    parser.add_argument(
        "--rate-limit", type=int, default=2,
        help="Maximum HTTP requests per second, passed to FamilySearch session"
    )
    parser.add_argument("--no-notes", action="store_true")
    parser.add_argument("--no-sources", action="store_true")
    args = parser.parse_args(argv)
    if not PERSON_ID.fullmatch(args.individual):
        parser.error("Invalid FamilySearch ID")
    if args.max_people < 0 or args.rate_limit < 1:
        parser.error("--max-people must be >= 0 and --rate-limit must be >= 1")
    checkpoint_path = args.database or args.output.with_suffix(".sqlite")
    checkpoint = Checkpoint(checkpoint_path)
    try:
        checkpoint.seed([args.individual])
        checkpoint.retry_failed()
        username = input("Enter FamilySearch username: ")
        password = getpass.getpass("Enter FamilySearch password: ")
        session = Session(
            username, password, rate_limit=args.rate_limit, delay=0.2
        )
        del password
        if not session.logged:
            parser.exit(2, "Could not log in to FamilySearch.\n")
        print(f"Checkpoint: {checkpoint.path}", file=sys.stderr)
        try:
            exhausted = crawl(checkpoint, session, max_people=args.max_people)
        except KeyboardInterrupt:
            exhausted = False
            print("\nPaused. Writing GEDCOM snapshot...", file=sys.stderr)
        n, families = assemble(
            checkpoint, session, args.output,
            no_notes=args.no_notes, no_sources=args.no_sources,
        )
        pending = checkpoint.count("pending")
        failed = checkpoint.count("failed")
        print(
            f"Saved {n} people and {families} families to {args.output}. "
            f"Pending: {pending}; failed: {failed}.",
            file=sys.stderr,
        )
        if not exhausted:
            print(
                "Not yet exhaustive. Run the SAME command again to resume "
                "from the SQLite checkpoint.",
                file=sys.stderr,
            )
    finally:
        checkpoint.close()


if __name__ == "__main__":
    main()
