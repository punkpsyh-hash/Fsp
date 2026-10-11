import unittest
from datetime import datetime, timedelta, timezone
from src.domain import Candidate, Need, rank, grade_result, Invitation

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


class DomainTests(unittest.TestCase):
    def offer(self, **kw):
        args = dict(id="i1", company_id="x", candidate_id="a", salary_from=100000,
                    salary_to=150000, expires_at=NOW + timedelta(days=7))
        args.update(kw)
        return Invitation(**args)

    def test_no_vacancy_needed(self):
        self.assertIsNone(self.offer().vacancy_id)

    def test_salary_invalid_ranges(self):
        for low, high in [(0, 1), (-1, 2), (200, 100)]:
            with self.subTest(low=low), self.assertRaises(ValueError):
                self.offer(salary_from=low, salary_to=high)

    def test_salary_not_float_or_bool(self):
        for value in [True, 10.5, "100"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.offer(salary_from=value)

    def test_hidden_before_accept(self):
        self.assertFalse(self.offer().contact_visible("x"))

    def test_only_sender_gets_contacts(self):
        i = self.offer()
        i.decide("a", "accepted", NOW)
        self.assertTrue(i.contact_visible("x"))
        self.assertFalse(i.contact_visible("y"))

    def test_candidate_ownership(self):
        with self.assertRaises(PermissionError):
            self.offer().decide("b", "accepted", NOW)

    def test_decline_keeps_contact_hidden(self):
        i = self.offer()
        i.decide("a", "declined", NOW)
        self.assertFalse(i.contact_visible("x"))

    def test_accept_idempotent(self):
        i = self.offer()
        i.decide("a", "accepted", NOW)
        i.decide("a", "accepted", NOW)
        self.assertEqual(i.grants, {"x"})

    def test_terminal_decision_conflict(self):
        i = self.offer()
        i.decide("a", "accepted", NOW)
        with self.assertRaises(ValueError):
            i.decide("a", "declined", NOW)

    def test_expiration_boundary(self):
        i = self.offer(expires_at=NOW)
        with self.assertRaises(ValueError):
            i.decide("a", "accepted", NOW)
        self.assertEqual(i.status, "expired")

    def test_contact_revoke(self):
        i = self.offer()
        i.decide("a", "accepted", NOW)
        i.revoke_contact("a")
        self.assertFalse(i.contact_visible("x"))

    def test_failed_does_not_downgrade(self):
        self.assertEqual(grade_result("middle", "junior", False, NOW, NOW), "middle")
        self.assertIsNone(grade_result(None, "middle", False, None, NOW))

    def test_initial_grade_without_cooldown(self):
        self.assertEqual(grade_result(None, "junior", True, None, NOW), "junior")

    def test_cooldown_boundary(self):
        with self.assertRaises(ValueError):
            grade_result("junior", "middle", True, NOW, NOW + timedelta(days=90, seconds=-1))
        self.assertEqual(grade_result("junior", "middle", True, NOW, NOW + timedelta(days=90)), "middle")

    def test_unsupported_grade(self):
        with self.assertRaises(ValueError):
            grade_result(None, "senior", True, None, NOW)

    def test_rank_filters_and_no_fsp(self):
        need = Need("backend", "junior", frozenset({"python"}), frozenset({"sql"}), 150000)
        def c(cid, **changes):
            args = dict(id=cid, specialization="backend", confirmed_grade="junior",
                        verified_skills=frozenset({"python", "sql"}), test_score=90, published=True)
            args.update(changes)
            return Candidate(**args)
        rows = rank([c("ok"), c("claimed", confirmed_grade=None), c("private", published=False),
                     c("wrong", specialization="frontend"), c("cost", salary_min=160000),
                     c("format", formats=frozenset({"office"})), c("missing", verified_skills=frozenset())], need)
        self.assertEqual([r["id"] for r in rows], ["ok"])
        self.assertEqual(rows[0]["fsp_bonus"], 0)

    def test_sort_ties_deterministic(self):
        args = dict(specialization="backend", confirmed_grade="junior", verified_skills=frozenset(),
                    test_score=80, published=True)
        need = Need("backend", "junior", frozenset(), frozenset(), 100)
        self.assertEqual([r["id"] for r in rank([Candidate("z", **args), Candidate("a", **args)], need)], ["a", "z"])


if __name__ == "__main__":
    unittest.main()
