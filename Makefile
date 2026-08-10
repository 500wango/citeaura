.PHONY: dev test migrate worker beat preflight

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
	celery -A api.worker.celery_app beat --loglevel=INFO --schedule=/tmp/citeaura-celerybeat-schedule

preflight:
	python3 scripts/production_preflight.py --env-file $${ENV_FILE:-.env.production}
