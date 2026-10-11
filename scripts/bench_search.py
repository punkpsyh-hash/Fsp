"""Замер времени подбора на N синтетических опубликованных профилях (SQLite, TestClient)."""
import argparse
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402
from src.server.app import create_app  # noqa: E402
from src.server.models import Base, Contact, Profile, User, now  # noqa: E402

SKILLS = {'backend': ['python', 'sql', 'http'], 'frontend': ['javascript', 'html', 'http'], 'qa': ['testing', 'sql', 'http']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=int, default=1000)
    parser.add_argument('--queries', type=int, default=40)
    args = parser.parse_args()
    rng = random.Random(7)
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app('sqlite:///' + str(Path(tmp) / 'bench.sqlite'), demo=True)
        Base.metadata.create_all(app.state.engine)
        with TestClient(app) as client:
            with app.state.factory() as db:
                for i in range(args.profiles):
                    spec = rng.choice(list(SKILLS))
                    uid = f'bench-{i}'
                    db.add(User(id=uid, email=uid + '@example.invalid', role='candidate', label=uid, verified=True))
                    db.flush()
                    db.add(Profile(user_id=uid, specialization=spec, claimed_grade='junior', confirmed_grade=rng.choice(['junior', 'middle']),
                                   skills=rng.sample(SKILLS[spec], rng.randint(1, 3)), published=True, test_score=rng.randint(60, 100),
                                   assessed_at=now(), fsp_signal=rng.choice([0, 0, 0.3, 0.8])))
                    db.add(Contact(user_id=uid, value=uid + '@example.invalid'))
                db.commit()
            client.post('/api/v1/auth/demo-login', json={'user_id': 'demo-employer-x'})
            csrf = client.get('/api/v1/me').json()['csrf']
            times = []
            for _ in range(args.queries):
                started = time.perf_counter()
                response = client.post('/api/v1/company/searches', json={'specialization': 'backend', 'grade': 'junior'}, headers={'X-CSRF-Token': csrf})
                assert response.status_code == 201, response.text
                times.append((time.perf_counter() - started) * 1000)
            times.sort()
            print(f'profiles={args.profiles} rows={len(response.json()["rows"])} median={statistics.median(times):.0f} ms '
                  f'p95={times[int(len(times) * 0.95) - 1]:.0f} ms')


if __name__ == '__main__':
    main()
