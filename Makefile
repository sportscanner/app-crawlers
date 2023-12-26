define support-libs
	@pip install black
	@pip install isort
endef

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs shuttlebot/ --savepath "requirements.txt" --force --encoding=utf-8

setup: health
	@pip install -r requirements.txt
	@$(support-libs)

run:
	@python -m streamlit run shuttlebot/frontend/app.py

build:
	@docker build -t shuttlebot .
	@docker run -p 8501:8501 shuttlebot

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/
