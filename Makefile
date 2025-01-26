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
	@python sportscanner/storage/postgres/database.py

run:
	@docker run --env-file .env \
		-v $(pwd)/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json:/app/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json \
		-p 8080:80 app-crawlers

develop:
	@echo "Launching in development mode (connected to SQLiteDB)"
	@DB_CONNECTION_STRING=sqlite:///sportscanner.db \
		python -m streamlit run sportscanner/frontend/app.py

format:
	@isort -r sportscanner/ *.py
	@black sportscanner/
