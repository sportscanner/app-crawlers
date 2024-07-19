define support-libs
	@pip install black
	@pip install isort
	@pip install pytest
endef

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs shuttlebot/ --savepath "requirements.txt" --force --encoding=utf-8

setup: health
	@python -m pip install --upgrade pip
	@pip install -r requirements.txt
	@pip install -e .
	@$(support-libs)

test:
	@pytest . -v --disable-warnings

reset:
	@echo "Truncates database tables and sets metadata to Obsolete"
	@python shuttlebot/backend/database.py

run:
	@docker run --env-file .env -p 8501:8501 shuttlebot

develop:
	@echo "Launching in development mode (Docker Build/Run)"
	@echo "Refine this command to use DuckDB for local mode and connect to volume"
	@docker build -t shuttlebot .
	@docker run --env-file .env -p 8501:8501 shuttlebot


format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/
