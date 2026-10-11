from typing import Annotated, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Grade = Literal["junior", "middle"]
Format = Literal["remote", "hybrid", "office"]
Specialization = Literal["backend", "frontend", "qa", "design"]
Skill = Literal["python", "sql", "javascript", "html", "testing", "http", "ux", "ui"]
DeclaredSkill = Literal["python", "sql", "javascript", "html", "testing", "http", "ux", "ui",
                        "react", "vue", "angular", "typescript", "nodejs", "nextjs", "css", "tailwind",
                        "fastapi", "django", "flask", "go", "java", "kotlin", "csharp", "php", "rust", "spring",
                        "postgresql", "mongodb", "redis", "kafka", "rabbitmq", "graphql",
                        "docker", "kubernetes", "linux", "cicd", "git", "aws",
                        "selenium", "playwright", "cypress", "pytest", "postman", "jmeter",
                        "figma", "prototyping", "designsystem", "uxresearch", "accessibility"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Email(Input):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def demo_address(cls, value):
        if not value.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Используйте синтетический адрес name@example.invalid")
        value = value.strip().lower()
        # В dev-пилоте реальные адреса и ПДн не принимаются.
        local, separator, domain = value.partition("@")
        if (separator != "@" or domain != "example.invalid" or len(local) > 64
                or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*", local, re.ASCII)):
            raise ValueError("Используйте синтетический адрес name@example.invalid")
        return value


class Register(Email):
    role: Literal["candidate", "employer"]
    label: str = Field(min_length=2, max_length=120)
    consent: Literal[True]
    password: str | None = Field(default=None, min_length=12, max_length=128, repr=False)


class PasswordLogin(Email):
    password: str = Field(min_length=1, max_length=128, repr=False)


class DemoLogin(Input):
    user_id: str


class Verify(Input):
    token: str = Field(min_length=20, max_length=128)


class ResumeInput(Input):
    full_name: str = Field(default="Синтетический кандидат", min_length=2, max_length=120)
    years_experience: StrictInt = Field(default=0, ge=0, le=60)
    roles: list[Literal["developer", "tester", "team-lead", "analyst", "designer"]] = Field(default_factory=list, max_length=4)
    soft_skills: list[Literal["communication", "teamwork", "planning", "mentoring"]] = Field(default_factory=list, max_length=4)
    education: str = Field(default="", max_length=1000)
    about: str = Field(default="", max_length=2000)
    declared_skills: list[DeclaredSkill] = Field(default_factory=list, max_length=20)

    @field_validator("declared_skills")
    @classmethod
    def unique_declared_skills(cls, value):
        return list(dict.fromkeys(value))


class ProfileInput(Input):
    industry: Literal["it"] = "it"
    specialization: Specialization = "backend"
    claimed_grade: Grade
    salary_min: StrictInt = Field(ge=0, le=10000000)
    formats: list[Format] = Field(min_length=1, max_length=3)
    contact: str = Field(max_length=254)
    resume: ResumeInput = Field(default_factory=ResumeInput)

    @field_validator("contact")
    @classmethod
    def contact_address(cls, value):
        return Email.demo_address(value)


class ConsentInput(Input):
    published: bool
    text_version: Literal["demo-consent-v1"] = "demo-consent-v1"


class AttemptInput(Input):
    specialization: Specialization = "backend"
    grade: Grade
    vacancy_id: str | None = Field(default=None, max_length=64)


class Answers(Input):
    answers: dict[str, str] = Field(max_length=12)


class DraftAnswers(Answers):
    expected_revision: StrictInt = Field(ge=0)


class IntegrityEvent(Input):
    type: Literal["hidden", "visible", "blur", "focus", "copy", "cut", "paste", "contextmenu",
                  "shortcut", "fullscreen_exit", "heartbeat", "answer"]
    t: StrictInt = Field(ge=0, le=86_400_000, description="мс от открытия попытки на клиенте")
    d: StrictInt | None = Field(default=None, ge=0, le=3_600_000, description="длительность отсутствия, мс (visible)")
    q: str | None = Field(default=None, max_length=80, description="id вопроса (answer)")


class IntegrityBatch(Input):
    events: list[IntegrityEvent] = Field(min_length=1, max_length=100)


class ExplanationOut(BaseModel):
    text: str
    source: Literal["template", "llm", "llm-mock"]
    model: str | None = None
    fallback_reason: str | None = None


class IntegrityAck(BaseModel):
    recorded: int


class FspToken(Input):
    grant_type: Literal["authorization_code"]
    client_id: str = Field(max_length=80)
    code: str = Field(min_length=10, max_length=200)
    code_verifier: str = Field(min_length=20, max_length=200)


class FspTokenOut(BaseModel):
    token_type: Literal["Bearer"]
    sub: str
    scope: str
    mock: Literal[True]


class SearchInput(Input):
    specialization: Specialization = "backend"
    grade: Grade = "junior"
    must_skills: list[Skill] = Field(default_factory=lambda: ["python"], max_length=6)
    desired_skills: list[Skill] = Field(default_factory=lambda: ["sql"], max_length=6)
    work_tasks: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=6)
    salary_to: StrictInt = Field(default=200000, ge=1, le=10000000)
    format: Format = "remote"
    fsp_only: bool = False

    @field_validator("work_tasks")
    @classmethod
    def unique_work_tasks(cls, value):
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def relevant_skills(self):
        from .assessment import CATALOG
        if not set(self.must_skills+self.desired_skills)<=set(CATALOG[self.specialization]['skills']):
            raise ValueError("Навыки не относятся к выбранной специализации")
        from .work_requirements import resolve
        resolve(self.work_tasks, self.specialization)
        return self


class CompanyInput(Input):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=20, max_length=4000)
    industry: str = Field(min_length=2, max_length=120)
    contact: str = Field(max_length=254)

    @field_validator("contact")
    @classmethod
    def synthetic_contact(cls, value):
        return Email.demo_address(value)


class NeedInput(SearchInput):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20, max_length=4000)


class VacancyInput(Input):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20, max_length=4000)
    specialization: Specialization
    grade: Grade
    skills: list[Skill] = Field(min_length=1, max_length=6)
    format: Format
    salary_from: StrictInt = Field(ge=1, le=10000000)
    salary_to: StrictInt = Field(ge=1, le=10000000)
    salary_basis: Literal["gross", "net"]
    status: Literal["draft", "published", "closed"] = "draft"
    expected_version: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def salary_range(self):
        if self.salary_to < self.salary_from:
            raise ValueError("Верхняя граница зарплаты ниже нижней")
        from .assessment import CATALOG
        if not set(self.skills)<=set(CATALOG[self.specialization]['skills']):
            raise ValueError("Стек вакансии не относится к специализации")
        return self


class ApplicationDecision(Input):
    status: Literal["viewed", "accepted", "declined"]


class TaskInput(Input):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20, max_length=2000)
    specialization: Specialization
    grade: Grade
    rubric: str = Field(min_length=20, max_length=2000)
    published: bool = False


class TaskAnswer(Input):
    answer: str = Field(min_length=20, max_length=4000)


class TaskReview(Input):
    score: StrictInt = Field(ge=0, le=100)
    feedback: str = Field(min_length=20, max_length=2000)


class OfferInput(Input):
    candidate_id: str = Field(max_length=64)
    description: str = Field(min_length=20, max_length=4000)
    salary_from: StrictInt = Field(ge=1, le=10000000)
    salary_to: StrictInt = Field(ge=1, le=10000000)
    salary_basis: Literal["gross", "net"]
    vacancy_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def salary_range(self):
        if self.salary_to < self.salary_from:
            raise ValueError("Верхняя граница зарплаты ниже нижней")
        return self


class Decision(Input):
    decision: Literal["accepted", "declined"]
