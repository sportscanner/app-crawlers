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
	@$(support-libs)

test:
	@pytest . -v --disable-warnings

reset:
	@echo "Truncates database tables and sets metadata to Obsolete"
	@python shuttlebot/backend/database.py

development:
	@echo "Launching in development mode (Docker Build/Run)"
	@echo "Connected to SQLiteDB for local storage"
	@docker build -t shuttlebot-dev -f Dockerfile .
#	@docker run -e DB_CONNECTION_STRING=sqlite:///sportscanner.db -p 8501:8501 \
 		-v $(pwd)/shuttlebot/frontend:/app/shuttlebot/frontend shuttlebot-dev

#production:
#	@echo "Launching in production mode (connected to remote database)"
#	@docker build -t shuttlebot -f Dockerfile.prod .
#	@docker run --env-file .env -p 8501:8501 shuttlebot

run:
	@DB_CONNECTION_STRING=sqlite:///sportscanner.db \
		python -m streamlit run shuttlebot/frontend/app.py

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/

prune:
	@docker container rm -f $(docker container ls -aq)
	@docker image rm -f $(docker image ls -q)