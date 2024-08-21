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

setup: health requirements.txt
	@python -m pip install --upgrade pip
	@pip install -r requirements.txt
	@pip install -e .
	@$(support-libs)

test:
	@pytest . -v --disable-warnings

reset:
	@echo "Truncates database tables and sets metadata to Obsolete"
	@DB_CONNECTION_STRING=sqlite:///sportscanner.db \
		python shuttlebot/backend/database.py

run:
	@docker run --env-file .env -p 8501:8501 shuttlebot

develop:
	@lsof -i :8501 -t | xargs kill -9
	@echo "Launching in development mode (connected to SQLiteDB)"
	@DB_CONNECTION_STRING=sqlite:///sportscanner.db \
		python -m streamlit run shuttlebot/frontend/app.py

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/

clean:
	@rm -rf shuttlebot.egg-info
	@rm -rf build
	@rm -rf dist