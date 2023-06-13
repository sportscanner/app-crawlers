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
	@playwright install chromium

run: setup
	@python main.py

format:
	@isort -r src/ tests/ *.py
	@black src/ tests/