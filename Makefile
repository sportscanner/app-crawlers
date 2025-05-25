define support-libs
	@pip install black
	@pip install isort
	@pip install pytest
endef

LATEST_COMMIT_ID := $(shell git rev-parse --short HEAD)

version:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs sportscanner/ --savepath "requirements.txt" --force --encoding=utf-8


setup: version
	@python -m pip install --upgrade pip
	@pip install --no-cache-dir -r requirements.txt
	@playwright install chromium
	@pip install -e .
	@$(support-libs)

test:
	@pytest . -v --disable-warnings


reset-database-tables:
	@echo "Truncates database tables and sets metadata to Obsolete"
	@python sportscanner/storage/postgres/database.py


dev-api-server:
	@echo "Locally running API server on localhost (connected databases: prod)"
	@fastapi dev sportscanner/api/root.py


api-server-container:
	@echo "Running container for image (tag: latest) to launch API server (Environment: prod)"
	@docker run --network=host --rm --platform=linux/amd64 --env-file .env \
		-v ~/developer/repository/sportscanner/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json:/app/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json \
		-p 8000:80 ghcr.io/sportscanner/app-crawlers:latest

crawler-pipeline-container:
	@echo "Running container for image (tag: latest) to run data crawlers pipeline (Environment: prod)"
	@docker run --rm --platform=linux/amd64 --network=host --env-file .env \
		-v ~/developer/repository/sportscanner/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json:/app/sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json \
		ghcr.io/sportscanner/app-crawlers:latest \
		python sportscanner/crawlers/pipeline.py

build-docker-image:
	@echo "Starting image build with ID: $(LATEST_COMMIT_ID)"
	@docker build --no-cache --platform=linux/amd64 \
		-t ghcr.io/sportscanner/app-crawlers:latest \
		-t ghcr.io/sportscanner/app-crawlers:$(LATEST_COMMIT_ID) .

push-image-to-repository:
	@echo "Pushing image to Image repository with tags: [latest, $(LATEST_COMMIT_ID)]"
	@docker push ghcr.io/sportscanner/app-crawlers:latest
	@docker push ghcr.io/sportscanner/app-crawlers:$(LATEST_COMMIT_ID)


format:
	@isort -r sportscanner/ *.py
	@black sportscanner/
