define support-libs
	@pip install black
	@pip install isort
endef

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs . --savepath "requirements.txt" --force

setup: health
	@pip install -r requirements.txt
	@$(support-libs)

run: setup
	@python main.py

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/