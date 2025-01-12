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
	@pipreqs sportscanner/ --savepath "requirements.txt" --force --encoding=utf-8

setup: health
	@python -m pip install --upgrade pip
	@pip install -r requirements.txt
	@pip install -e .
	@$(support-libs)

test:
	@pytest . -v --disable-warnings

reset:
	@echo "Truncates database tables and sets metadata to Obsolete"
	@python sportscanner/crawlers/database.py

run:
	@docker run --env-file .env -p 8501:8501 sportscanner

develop:
	@echo "Launching in development mode (connected to SQLiteDB)"
	@DB_CONNECTION_STRING=sqlite:///sportscanner.db \
		python -m streamlit run sportscanner/frontend/app.py

format:
	@isort -r sportscanner/ *.py
	@black sportscanner/
