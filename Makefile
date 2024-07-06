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
	@echo "Launching webapp connected to database"
	@python -m streamlit run shuttlebot/frontend/app.py

develop: reset run

build:
	@docker build -t shuttlebot .
	@docker run -p 8501:8501 shuttlebot

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/
