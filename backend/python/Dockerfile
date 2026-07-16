FROM python:3.12-slim

WORKDIR /app/backend/python

COPY backend/python/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir -e .[dev]

COPY backend/python ./ 

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--reload"]
