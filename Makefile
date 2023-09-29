define support-libs
	@pip install black
	@pip install isort
endef

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs . --savepath "requirements.txt" --force --encoding=utf-8

setup: health
	@pip install -r requirements.txt
	@$(support-libs)

run: setup
	@python -m streamlit run shuttlebot/webapp/app.py

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/