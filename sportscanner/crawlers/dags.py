from dagster import asset
from pandas import DataFrame, read_html, get_dummies
from sklearn.linear_model import LinearRegression

@asset
def country_populations() -> DataFrame:
    df = read_html("https://tinyurl.com/mry64ebh")[0]
    df.columns = ["country", "pop2022", "pop2023", "change", "continent", "region"]
    df["change"] = df["change"].str.rstrip("%").str.replace("−", "-").astype("float")
    return df

@asset
def continent_change_model(country_populations: DataFrame) -> LinearRegression:
    data = country_populations.dropna(subset=["change"])
    return LinearRegression().fit(get_dummies(data[["continent"]]), data["change"])

@asset
def continent_stats(country_populations: DataFrame, continent_change_model: LinearRegression) -> DataFrame:
    result = country_populations.groupby("continent").sum()
    result["pop_change_factor"] = continent_change_model.coef_
    return result