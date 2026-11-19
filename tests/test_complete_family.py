"""Regression tests for complete family traversal (no FamilySearch login required)."""
import tempfile
import unittest
from pathlib import Path

from getmyancestors.complete_family import (
    Checkpoint,
    ReplaySession,
    crawl,
    related_people,
)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.records = {
            "AAAA-111": {
                "persons": [{"id": "AAAA-111"}],
                "relationships": [
                    {
                        "id": "couple-1",
                        "person1": {"resourceId": "AAAA-111"},
                        "person2": {"resourceId": "BBBB-222"},
                    }
                ],
            },
            "BBBB-222": {
                "persons": [{"id": "BBBB-222"}],
                "childAndParentsRelationships": [
                    {
                        "id": "parent-1",
                        "parent1": {"resourceId": "CCCC-333"},
                        "child": {"resourceId": "BBBB-222"},
                    }
                ],
            },
            "CCCC-333": {
                "persons": [{"id": "CCCC-333"}],
                "childAndParentsRelationships": [
                    {
                        "id": "parent-2",
                        "parent1": {"resourceId": "CCCC-333"},
                        "child": {"resourceId": "DDDD-444"},
                    }
                ],
            },
            "DDDD-444": {"persons": [{"id": "DDDD-444"}]},
        }

    def get_url(self, url, headers=None, no_api=False):
        self.calls.append(url)
        return self.records.get(url.split("=")[-1])


class CompleteFamilyTests(unittest.TestCase):
    def test_discovers_parents_children_and_spouses(self):
        self.assertEqual(
            related_people(
                {
                    "childAndParentsRelationships": [
                        {
                            "parent1": {"resourceId": "BBBB-222"},
                            "parent2": {"resourceId": "CCCC-333"},
                            "child": {"resourceId": "AAAA-111"},
                        }
                    ],
                    "relationships": [
                        {
                            "person1": {"resourceId": "AAAA-111"},
                            "person2": {"resourceId": "DDDD-444"},
                        }
                    ],
                }
            ),
            {"AAAA-111", "BBBB-222", "CCCC-333", "DDDD-444"},
        )

    def test_traverses_through_spouse_to_in_laws_and_other_children(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Checkpoint(Path(folder) / "family.sqlite")
            session = FakeSession()
            try:
                store.seed(["AAAA-111"])
                self.assertTrue(crawl(store, session, max_people=0, progress=0))
                self.assertEqual(store.count("done"), 4)
                self.assertEqual(store.count("pending"), 0)
                self.assertEqual(len(session.calls), 4)
            finally:
                store.close()

    def test_resumes_without_fetching_previous_people(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "family.sqlite"
            store = Checkpoint(path)
            try:
                store.seed(["AAAA-111"])
                self.assertFalse(crawl(store, FakeSession(), max_people=2, progress=0))
                self.assertEqual(store.count("done"), 2)
            finally:
                store.close()

            store = Checkpoint(path)
            try:
                session = FakeSession()
                self.assertTrue(crawl(store, session, max_people=0, progress=0))
                self.assertEqual(store.count("done"), 4)
                self.assertEqual(
                    session.calls,
                    [
                        "/platform/tree/persons?pids=CCCC-333",
                        "/platform/tree/persons?pids=DDDD-444",
                    ],
                )
            finally:
                store.close()

    def test_replay_can_combine_cached_person_responses(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Checkpoint(Path(folder) / "family.sqlite")
            try:
                session = FakeSession()
                for identifier in ("AAAA-111", "BBBB-222"):
                    store.save_response(
                        "/platform/tree/persons?pids=" + identifier,
                        session.records[identifier],
                    )
                replay = ReplaySession(session, store)
                response = replay.get_url(
                    "/platform/tree/persons?pids=AAAA-111,BBBB-222"
                )
                self.assertEqual(
                    {p["id"] for p in response["persons"]},
                    {"AAAA-111", "BBBB-222"},
                )
                self.assertEqual(len(response["relationships"]), 1)
                self.assertEqual(len(response["childAndParentsRelationships"]), 1)
                self.assertEqual(session.calls, [])
            finally:
                store.close()

    def test_unavailable_people_are_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Checkpoint(Path(folder) / "family.sqlite")
            try:
                store.seed(["ZZZZ-999"])
                self.assertFalse(crawl(store, FakeSession(), max_people=0, progress=0))
                self.assertEqual(store.count("failed"), 1)
                self.assertEqual(store.count("pending"), 0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
