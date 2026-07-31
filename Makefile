.PHONY: dev test migrate worker beat

dev:
	uvicorn api.main:app --reload

test:
	python3 -m pytest api/tests -v
	cd engine && python3 -m unittest discover -s tests

migrate:
	alembic upgrade head

worker:
	celery -A api.worker.celery_app worker --loglevel=INFO

beat:
	celery -A api.worker.celery_app beat --loglevel=INFO --schedule=/tmp/disvorai-celerybeat-schedule
