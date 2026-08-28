.PHONY: dev test migrate worker beat preflight check-work-root create-admin reset-admin-password reset-admin-password-prod grant-plan-prod

dev:
	uvicorn api.main:app --reload

test:
	python3 -m pytest api/tests -v
	cd engine && python3 -m unittest discover -s tests

migrate:
	alembic upgrade head

worker:
	celery -A api.worker.celery_app worker --loglevel=INFO --pool=prefork

beat:
	celery -A api.worker.celery_app beat --loglevel=INFO --schedule=/tmp/citeaura-celerybeat-schedule

preflight:
	python3 scripts/production_preflight.py --env-file $${ENV_FILE:-.env.production} --tls-mode external

check-work-root:
	@test "$${WORK_ROOT:-$$(pwd)/work}" != "$$(pwd)/engine/work" || { printf 'WORK_ROOT must not point at engine/work for SaaS runs; use with_tenant_context.\n' >&2; exit 2; }

create-admin:
	python3 -m api.admin.cli create --email "$${EMAIL}" --role "$${ROLE:-superadmin}"

reset-admin-password:
	python3 -m api.admin.cli reset-password --email "$${EMAIL}"

reset-admin-password-prod:
	@test -n "$(EMAIL)" || { printf 'EMAIL is required\n' >&2; exit 2; }
	docker compose --env-file "$(or $(ENV_FILE),.env.production)" -f docker-compose.prod.yml exec api \
		python3 -m api.admin.cli reset-password --email "$(EMAIL)"

grant-plan-prod:
	@test -n "$(EMAIL)" || { printf 'EMAIL is required\n' >&2; exit 2; }
	@test -n "$(PLAN)" || { printf 'PLAN is required\n' >&2; exit 2; }
	docker compose --env-file "$(or $(ENV_FILE),.env.production)" -f docker-compose.prod.yml exec api \
		python3 -m api.admin.cli grant-plan --email "$(EMAIL)" --plan "$(PLAN)" $(if $(TENANT_ID),--tenant-id "$(TENANT_ID)")
