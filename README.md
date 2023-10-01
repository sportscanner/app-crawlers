
# Shuttlebot - badminton slots finder

[Shuttlebot](https://shuttle-bot.onrender.com/) is a webapp that helps badminton players in London find consecutively available badminton slots for the upcoming week, during specific time frames and locations.

The webapp is developed on top of Streamlit `(using Python >= 3.10)` and employs concurrent concepts of Async to parse different websites for badminton slots availability in smaller response times. 
## Run Locally

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
  python -m streamlit run shuttlebot/webapp/app.py
```
App will be available at: http://localhost:8501/


## Authors

- [Yasir Khalid](https://www.linkedin.com/in/yasir-khalid)

