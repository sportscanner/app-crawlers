define support-libs
	@pip install black
	@pip install isort
endef

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@export PYTHONIOENCODING=utf-8
	@pipreqs . --savepath "requirements.txt" --force

setup: health
	@pip install -r requirements.txt
	@$(support-libs)

run:
	@python -m shuttlebot.scanner.script

format:
	@isort -r shuttlebot/ *.py
	@black shuttlebot/