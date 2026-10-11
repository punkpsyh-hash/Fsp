"""Executable specification; not a production API or persistence layer."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Candidate:
    id: str
    specialization: str
    confirmed_grade: str | None
    verified_skills: frozenset[str]
    test_score: float
    fsp_signal: float = 0
    freshness: float = 0
    published: bool = False
    formats: frozenset[str] = frozenset({"remote"})
    salary_min: int = 0

    def __post_init__(self):
        if not 0 <= self.test_score <= 100:
            raise ValueError("test_score")
        if not 0 <= self.fsp_signal <= 1 or not 0 <= self.freshness <= 1:
            raise ValueError("signal")
        if self.salary_min < 0:
            raise ValueError("salary_min")


@dataclass(frozen=True)
class Need:
    specialization: str
    grade: str
    must: frozenset[str]
    desired: frozenset[str]
    salary_to: int
    format: str = "remote"


def rank(candidates: list[Candidate], need: Need):
    rows = []
    for c in candidates:
        if not c.published or c.confirmed_grade != need.grade:
            continue
        if c.specialization != need.specialization or not need.must <= c.verified_skills:
            continue
        if need.format not in c.formats or c.salary_min > need.salary_to:
            continue
        desired = need.must | need.desired
        overlap = len(desired & c.verified_skills) / len(desired) if desired else 1
        score = round(45 * c.test_score / 100 + 35 * overlap + 10 * c.fsp_signal + 10 * c.freshness, 3)
        rows.append({"id": c.id, "score": score, "matched": sorted(desired & c.verified_skills),
                     "missing": sorted(desired - c.verified_skills), "fsp_bonus": 10 * c.fsp_signal,
                     "components": {"assessment": round(45*c.test_score/100,3),
                                    "skills": round(35*overlap,3),
                                    "fsp": round(10*c.fsp_signal,3),
                                    "freshness": round(10*c.freshness,3)}})
    return sorted(rows, key=lambda r: (-r["score"], r["id"]))


GRADE_RANK = {"junior": 0, "middle": 1}


def grade_result(current: str | None, requested: str, passed: bool,
                 last_changed: datetime | None, now: datetime):
    """Failed attempts never downgrade; initial confirmation has no cooldown.

    The 90-day limit applies to moving up. A candidate may confirm a lower grade at once
    (ТЗ: «пройти тест на уровень ниже»), but that move restarts the limit for moving up.
    """
    if requested not in {"junior", "middle"}:
        raise ValueError("unsupported_grade")
    if not passed:
        return current
    if current == requested:
        return current
    if current and last_changed and GRADE_RANK[requested] > GRADE_RANK[current] and now < last_changed + timedelta(days=90):
        raise ValueError("grade_cooldown")
    if current and last_changed is None:
        raise ValueError("missing_grade_history")
    return requested


@dataclass
class Invitation:
    id: str
    company_id: str
    candidate_id: str
    salary_from: int
    salary_to: int
    expires_at: datetime
    vacancy_id: str | None = None
    status: str = "sent"
    grants: set[str] = field(default_factory=set)

    def __post_init__(self):
        # bool is a subclass of int; salaries must be actual integer amounts.
        if type(self.salary_from) is not int or type(self.salary_to) is not int:
            raise ValueError("salary_type")
        if self.salary_from <= 0 or self.salary_to < self.salary_from:
            raise ValueError("salary_range")

    def decide(self, actor: str, decision: str, now: datetime):
        if actor != self.candidate_id:
            raise PermissionError("not_owner")
        if decision not in {"accepted", "declined"}:
            raise ValueError("decision")
        if self.status == decision:
            return self.status
        if self.status not in {"sent", "viewed"}:
            raise ValueError("terminal_state")
        if now >= self.expires_at:
            self.status = "expired"
            raise ValueError("expired")
        self.status = decision
        if decision == "accepted":
            self.grants.add(self.company_id)
        return self.status

    def contact_visible(self, company_id: str):
        return self.status == "accepted" and company_id in self.grants

    def revoke_contact(self, actor: str):
        if actor != self.candidate_id:
            raise PermissionError("not_owner")
        self.grants.clear()
