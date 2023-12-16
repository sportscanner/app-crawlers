# Shuttlebot - badminton slots finder

### What is it about?
[Shuttlebot](https://shuttle-bot.onrender.com/) is a webapp that helps badminton players find available badminto slots for the upcoming week (across London), with the option to search for consecutively available slots (example: 6.00pm-6.40pm and 6.40pm-7.20pm)

The webapp is developed on top of Streamlit `(using Python >= 3.10)` and employs concurrent concepts of Async to parse different websites for badminton slots availability in smaller response times. Async in Python allows the program to proceed while it **await**s for the web requests to be processed, enabling quick response times.

![image](https://github.com/yasir-khalid/shuttlebot/assets/29762458/d3da88b2-4390-460a-942c-57dbba14a94e)

## How to get started locally?

Clone the project

```bash
  git clone https://github.com/yasir-khalid/shuttlebot.git
```

Go to the project directory

```bash
  cd shuttlebot/
```

Install dependencies

```bash
  pip install -r requirements.txt
```

Launch the webapp on localhost

```bash
  python -m streamlit run shuttlebot/frontend/app.py
```
App will be available at: http://localhost:8501/

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

## Tests

Currently there is a Make target, that is responsible for linting and formatting of the code using *isort* and *black*. There is a Github CI setup, that triggers when the code is pushed to the repository and analyses the code using *pylint*
```bash
  pip install -r requirements.txt
```

## Authors

- [Yasir Khalid](https://www.linkedin.com/in/yasir-khalid)
