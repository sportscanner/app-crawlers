## Shuttlebot - badminton slots finder
![example workflow](https://github.com/yasir-khalid/shuttlebot/actions/workflows/Automated-PR-tests.yml/badge.svg) ![example workflow](https://github.com/yasir-khalid/shuttlebot/actions/workflows/deploy-to-registry.yml/badge.svg)

 
### What is it about?
[Shuttlebot](https://shuttle-bot.onrender.com/) is a webapp that helps badminton players find
available badminton slots for the upcoming week, across London,
with the option to search for consecutively available slots

The webapp is developed on top of Streamlit `(using Python >= 3.10)` and employs concurrent concepts of Async to parse different websites for badminton slots availability in smaller response times. Async in Python allows the program to proceed while it **await**s for the web requests to be processed, enabling quick response times.

### Features
- Currently supports `20` badminton centres across London
- Option to filter available badminton slots based on given time ranges
- searches badminton slots for the upcoming 6-7 days depending on published slots by providers
> This means the number of API calls become `20 sports centres` **x** `6-days` **~** 120, therefore the need for Asynchronous to improve UX
- Displays the location metadata (in miles) on how far a badminton centre is from the user,
  based on postcode search (Postcode search supported by `https://postcodes.io/`)

### App deployment lifecycle
![Doodles (2)](https://github.com/yasir-khalid/shuttlebot/assets/29762458/5020fac5-f409-476b-b5d5-5b9b485ec09e)

### How to get started locally?

1. Clone the project
```commandline
  git clone https://github.com/yasir-khalid/shuttlebot.git
```

#### Using docker to run the app
Ensure you have Docker installed on your machine
```commandline
docker build -t shuttlebot .
docker run -p 8501:8501 shuttlebot
```
App will be available at: http://localhost:8501/

---

#### Running app in local environment

2. Go to the project directory `cd shuttlebot/`
3. Install dependencies

```commandline
  pip install -r requirements.txt
```

4. Launch the webapp on localhost

```commandline
  python -m streamlit run shuttlebot/frontend/app.py
```
App will be available at: http://localhost:8501/

---

#### Make targets to launch the app
The project has a `Makefile` with pre-defined **make targets** which can help launch all the above
commands quite easily. In order to use this, you need to have **Make** install on your machine
```commandline
make setup
make run
```
App will be available at: http://localhost:8501/

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.


## Authors
- [Yasir Khalid](https://www.linkedin.com/in/yasir-khalid)
