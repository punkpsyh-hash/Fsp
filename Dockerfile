ARG NODE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ARG PYTHON_IMAGE=python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
COPY src src
COPY requirements/examples/bank-contest.json requirements/examples/bank-contest.json
COPY migrations migrations
COPY alembic.ini .
COPY design/assets/editorial.png design/assets/editorial.png
# DejaVu — локальный шрифт для кириллических PDF, не внешний asset.
COPY resources/DejaVuSans.ttf /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
COPY resources/DejaVu-LICENSE.txt /usr/share/fonts/truetype/dejavu/DejaVu-LICENSE.txt
# Только по запросу: тесты, контракты, ranking и конкурсные PDF.
FROM backend AS tools
LABEL org.fsp.project="career-profile" org.fsp.component="tools"
RUN pip install --no-cache-dir --only-binary=:all: python-docx==1.2.0 lxml==6.1.3
COPY tests/ tests/
COPY compose.yaml compose.runner-tcg.yaml compose.verify.yaml compose.isolated.yaml compose.llm.yaml compose.remote-llm.yaml compose.delivery.yaml compose.jury.yaml compose.jury-relay.yaml compose.jury-public-demo.yaml compose.jury-individual.yaml ./
COPY docker/model.Dockerfile docker/model.Dockerfile
COPY docker/jury/ docker/jury/
COPY scripts/ scripts/
COPY ml/ ml/
COPY contracts/ contracts/
COPY docs/*.md docs/*.json docs/
COPY docs/api-examples.http docs/api-examples.http
COPY docs/assets/screenshots/ docs/assets/screenshots/
COPY docs/assets/diagrams/ docs/assets/diagrams/
COPY requirements/sources.json requirements/sources.json
COPY requirements/examples/ requirements/examples/
COPY requirements/pilot/README.md requirements/pilot/observations.csv requirements/pilot/
COPY resources/ resources/
COPY web/package.json web/package-lock.json web/
COPY web/scripts/scenario-oracle.mjs web/scripts/scenario-oracle.mjs
COPY README.md ./
USER 10001:10001
CMD ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]

# Готовые UI и API: Node, тесты и документы не копируются в рабочий образ.
FROM backend AS runtime
COPY --from=frontend /build/web/dist/ web/dist/
COPY resources/licenses/third-party/web/ web/dist/licenses/
COPY scripts/entrypoint.sh /usr/local/bin/fsp-entrypoint
RUN chmod 755 /usr/local/bin/fsp-entrypoint
USER 10001:10001
EXPOSE 8470
ENTRYPOINT ["/usr/local/bin/fsp-entrypoint"]
