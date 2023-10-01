SUPPORT_LIBS := black isort flake8 autopep8

health:
	@make --version
	@python --version

freeze:
	@pip install pipreqs
	@pipreqs . --savepath "requirements.txt" --force --encoding=utf-8

setup: health
	@pip install -r requirements.txt
	@pip install $(SUPPORT_LIBS)

format:
	@isort -rc shuttlebot/ *.py
	@autopep8 --in-place --recursive shuttlebot/
	@black shuttlebot/
	@flake8 .

run: setup
	@python -m streamlit run shuttlebot/webapp/app.py
