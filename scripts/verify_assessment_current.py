"""Текущая конечная диагностика scenarios-v6, не human pilot и не гарантия от решателя.

Проверяет содержимое приватных snapshots независимым oracle, публичную проекцию
и два ограниченных переноса опубликованного ключа между разными seed. Исторические
отчёты v4/v5 этот скрипт не читает и не перезаписывает.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.server.assessment import CATALOG, VERSION, evaluate, public_question_form, questions
from tests.test_assessment_scenarios import encoded, oracle, shown_python_result


EXPECTED_VERSION = "scenarios-v6"
PUBLIC_FIELDS = {"id", "skill", "title", "options"}
CONFIRMATION_BAND = 6
HASHED_SOURCES = (
    "src/server/app.py",
    "src/server/assessment.py",
    "src/server/assessment_scenarios.py",
    "tests/test_assessment_scenarios.py",
    "scripts/verify_assessment_current.py",
)


def validate_form(seed: int, grade: str, specialization: str):
    private = questions(seed, grade, specialization, VERSION)
    public = public_question_form(private)
    assert len(private) == len(public) == 12
    assert len({row["id"] for row in private}) == 12
    assert Counter(row["skill"] for row in private) == Counter(
        {skill: 4 for skill in CATALOG[specialization]["skills"]}
    )
    answers = {}
    for saved, issued in zip(private, public):
        assert set(issued) == PUBLIC_FIELDS
        assert saved["id"] == issued["id"]
        assert saved["title"] == issued["title"]
        assert saved["options"] == issued["options"]
        expected = encoded(oracle(saved))
        assert expected == saved["answer"]
        if saved["family"].startswith("py-"):
            assert encoded(shown_python_result(saved)) == expected
        assert len(issued["options"]) == len(set(issued["options"])) == 4
        assert issued["options"].count(expected) == 1
        answers[saved["id"]] = expected
    assert evaluate(seed, grade, answers, specialization, VERSION, form=private)["score"] == 100
    return private, public


def copied_answers(form, key, strategy):
    return {
        row["id"]: key[row["family"]]
        if strategy == "literal"
        else row["options"][key[row["family"]]]
        for row in form
        if strategy != "literal" or key[row["family"]] in row["options"]
    }


def transfer_case(specialization: str, grade: str, donors, receivers, confirmations, strategy: str):
    scores = []
    passing_pairs = []
    confirmation_pairs = []
    second_form_pairs = []
    immediate_confirmations = 0
    borderline_pairs = 0
    threshold = 70 if grade == "junior" else 80
    for donor_seed, donor in donors:
        key = {
            row["family"]: row["answer"] if strategy == "literal" else row["options"].index(row["answer"])
            for row in donor
        }
        for receiver_seed, form in receivers:
            copied = copied_answers(form, key, strategy)
            result = evaluate(receiver_seed, grade, copied, specialization, VERSION, form=form)
            scores.append(result["score"])
            if result["passed"]:
                passing_pairs.append(
                    {"donor_seed": donor_seed, "receiver_seed": receiver_seed, "score": result["score"]}
                )
            if result["passed"] and abs(result["score"] - threshold) > CONFIRMATION_BAND:
                immediate_confirmations += 1
            if abs(result["score"] - threshold) <= CONFIRMATION_BAND:
                borderline_pairs += 1
                confirmation_seed, confirmation_form = confirmations[receiver_seed]
                second = evaluate(
                    confirmation_seed,
                    grade,
                    copied_answers(confirmation_form, key, strategy),
                    specialization,
                    VERSION,
                    form=confirmation_form,
                )
                combined = round((result["score"] + second["score"]) / 2, 2)
                second_form_pairs.append(
                    {
                        "donor_seed": donor_seed,
                        "receiver_seed": receiver_seed,
                        "confirmation_seed": confirmation_seed,
                        "stage_scores": [result["score"], second["score"]],
                        "combined_score": combined,
                        "confirmed": combined >= threshold,
                    }
                )
                if combined >= threshold:
                    confirmation_pairs.append(second_form_pairs[-1])
    return {
        "specialization": specialization,
        "grade": grade,
        "strategy": strategy,
        "pairs": len(scores),
        "passes": len(passing_pairs),
        "immediate_confirmations": immediate_confirmations,
        "borderline_pairs": borderline_pairs,
        "confirmed_after_second": len(confirmation_pairs),
        "policy_confirmations": immediate_confirmations + len(confirmation_pairs),
        "minimum_score": min(scores),
        "maximum_score": max(scores),
        "mean_score": round(sum(scores) / len(scores), 2),
        "passing_pairs": passing_pairs,
        "second_form_pairs": second_form_pairs,
        "confirmation_pairs": confirmation_pairs,
    }


def build_report(donor_count: int, receiver_count: int, receiver_start: int):
    assert VERSION == EXPECTED_VERSION, (
        f"Диагностика предназначена для {EXPECTED_VERSION}; текущая версия {VERSION}. "
        "Создайте новый протокол вместо перезаписи этого."
    )
    donor_seeds = range(donor_count)
    receiver_seeds = range(receiver_start, receiver_start + receiver_count)
    assert set(donor_seeds).isdisjoint(receiver_seeds)
    matrices = []
    transfers = []
    for specialization in CATALOG:
        for grade in ("junior", "middle"):
            signatures = set()
            receivers = []
            for seed in receiver_seeds:
                private, public = validate_form(seed, grade, specialization)
                receivers.append((seed, private))
                signatures.add(json.dumps(public, ensure_ascii=False, sort_keys=True))
            matrices.append(
                {
                    "specialization": specialization,
                    "grade": grade,
                    "forms": receiver_count,
                    "distinct_forms": len(signatures),
                    "questions": 12,
                    "per_skill": 4,
                    "independent_oracles": "passed",
                    "public_fields": sorted(PUBLIC_FIELDS),
                }
            )
            donors = [
                (seed, questions(seed, grade, specialization, VERSION)) for seed in donor_seeds
            ]
            confirmations = {
                seed: (
                    1000 + seed,
                    validate_form(1000 + seed, grade, specialization)[0],
                )
                for seed in receiver_seeds
            }
            for strategy in ("literal", "position"):
                transfers.append(
                    transfer_case(
                        specialization, grade, donors, receivers, confirmations, strategy
                    )
                )
    return {
        "type": "current_assessment_answer_transfer_diagnostic",
        "blueprint_version": VERSION,
        "method": {
            "donor_seeds": [donor_seeds.start, donor_seeds.stop - 1],
            "receiver_seeds": [receiver_seeds.start, receiver_seeds.stop - 1],
            "donors_per_case": donor_count,
            "receivers_per_case": receiver_count,
            "strategies": ["literal", "position"],
            "literal": "Текст эталона переносится по private family, только если такой option есть у получателя.",
            "position": "Индекс верного option донора переносится на option с тем же индексом у получателя.",
            "confirmation_policy": {
                "implementation": "src/server/app.py assessment submit stage 1/2",
                "band_points": CONFIRMATION_BAND,
                "thresholds": {"junior": 70, "middle": 80},
                "paired_confirmation_seed": "1000 + receiver_seed",
                "decision": "Вне полосы проход подтверждается сразу; внутри полосы итог равен среднему двух форм и сравнивается с порогом.",
                "scope": "Считается score-policy при чистом integrity; hold по сигналам прокторинга здесь не моделируется.",
            },
            "content_check": "Private snapshot решён независимым oracle; candidate DTO содержит только id/skill/title/options.",
        },
        "forms_total": receiver_count * len(CATALOG) * 2,
        "confirmation_forms_total": receiver_count * len(CATALOG) * 2,
        "matrices": matrices,
        "transfer": {
            "pairs_total": sum(row["pairs"] for row in transfers),
            "passes_total": sum(row["passes"] for row in transfers),
            "immediate_confirmations_total": sum(
                row["immediate_confirmations"] for row in transfers
            ),
            "confirmed_after_second_total": sum(
                row["confirmed_after_second"] for row in transfers
            ),
            "policy_confirmations_total": sum(
                row["policy_confirmations"] for row in transfers
            ),
            "results": transfers,
        },
        "source_sha256": {
            name: sha256((ROOT / name).read_bytes()).hexdigest() for name in HASHED_SOURCES
        },
        "limitations": [
            "Конечная детерминированная выборка seed; отсутствие прохода не является универсальной гарантией.",
            "Проверяются только literal и position key transfer, не общий алгоритм решения, LLM, человек или второе устройство.",
            "Independent oracle подтверждает вычисление эталона, но не профессиональную сложность, Junior/Middle и психометрическую калибровку.",
            "Полные формы могут различаться, хотя отдельные семейства и сценарии повторяются; item-bank exposure измеряется отдельно.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donors", type=int, default=20)
    parser.add_argument("--receivers", type=int, default=100)
    parser.add_argument("--receiver-start", type=int, default=100)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assessment-v6-results.json")
    args = parser.parse_args()
    if not 1 <= args.donors <= 100 or not 1 <= args.receivers <= 1000:
        parser.error("Нужно 1 <= donors <= 100 и 1 <= receivers <= 1000")
    report = build_report(args.donors, args.receivers, args.receiver_start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "version": report["blueprint_version"],
                "forms": report["forms_total"],
                "transfer_pairs": report["transfer"]["pairs_total"],
                "transfer_passes": report["transfer"]["passes_total"],
                "policy_confirmations": report["transfer"]["policy_confirmations_total"],
                "output": str(args.output),
                "limitations": report["limitations"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
