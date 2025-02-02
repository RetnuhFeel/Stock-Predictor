#####################################
### stock-predictor version 0.0.1 ###
#########################################################################
### The goal of this software is to predict future stock prices based ###
### on historical data. Initially yahoo finance will be used as the   ###
### data source, but this project should be flexible enough to use    ###
### other data sources.                                               ###
#########################################################################

### Import necessary modules ###
import pandas as pd  # for data manipulation
import numpy as np  # for numerical ops
import matplotlib as mpl  # for plotting
#import seaborn as sb
import sklearn as skl  # for machine learning models
import yfinance as yfin  # for fetching stock data

# define ticker symbol
ticker_symbol = "AAPL"

# create a ticker object
ticker = yfin.Ticker(ticker_symbol)

# define timeframe, can be: "1d", "1mo", "1y", etc
tf = "1y"

# fetch historical stock data for given timeframe
historical_data = ticker.history(period=tf)
print("Historical data:")
print(historical_data)

# fetch basic financials
financials = ticker.financials
print("\nFinancials:")
print(financials)

actions = ticker.actions
print("\nStock Actions:")
print(actions)
