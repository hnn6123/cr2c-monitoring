''' 
	This script calculates totals and averages for any given HMI data point(s), 
	time period, and date range for which a raw eDNA query has been run (and a csv file
	for that query obtained)
	If desired, also outputs plots and summary tables
'''

from __future__ import print_function
import matplotlib
matplotlib.use("TkAgg",force=True) 
import matplotlib.pyplot as plt
import matplotlib.ticker as tkr
import matplotlib.dates as dates
import pylab as pl
import numpy as np
import pandas as pd
import datetime as datetime
from datetime import datetime as dt
from datetime import timedelta as tdelt
from pandas import read_excel
import get_lab_data as gld
import sqlite3
import os
import sys
from tkinter.filedialog import askopenfilename
from tkinter.filedialog import askdirectory

class hmi_data_agg:

	def __init__(self, qtype, stype):

		self.qtype = qtype.upper()
		self.stype = stype.upper()


	def prep_data(self, elid):

		# Set high and low limits for sensors based on type (water, gas, ph, conductivity, temp)
		if self.stype == 'WATER':
			hi_limit = 200
			lo_limit = 0.2
		elif self.stype == 'GAS':
			hi_limit = 10
			lo_limit = 0.005
		elif self.stype == 'PH':
			hi_limit = 10
			lo_limit = 4
		elif self.stype == 'TEMP':
			hi_limit = 50
			lo_limit = 0
		elif self.stype == 'PRESSURE':
			hi_limit = 16
			lo_limit = 13.4
		elif self.stype == 'TMP':
			hi_limit = 20
			lo_limit = -20

		# Load data
		try:
			self.hmi_data = pd.read_csv(self.hmi_path)
		except FileNotFoundError:
			print('Please choose an existing input file with the HMI data')
			sys.exit()

		# Load variables and set output variable names
		varname = 'CR2C.CODIGA.{0}.SCALEDVALUE {1} [{2}]'
		self.xvar = elid + '_ts'
		self.yvar = elid + '_value'	

		# Rename variable
		self.hmi_data[self.yvar] = \
			self.hmi_data[varname.format(elid,'Value', self.qtype)]
		# Set low/negative values to 0 (if a flow, otherwise remove) and remove unreasonably high values
		if self.stype in ['GAS','WATER']:
			self.hmi_data.loc[self.hmi_data[self.yvar] < lo_limit, self.yvar] = 0
		else:
			self.hmi_data.loc[self.hmi_data[self.yvar] < lo_limit, self.yvar] = np.NaN	
		self.hmi_data.loc[self.hmi_data[self.yvar] > hi_limit, self.yvar] = np.NaN	

		# Rename and format corresponding timestamp variable 
		self.hmi_data[self.xvar ] = \
			self.hmi_data[varname.format(elid, 'Time', self.qtype)]
		self.hmi_data[self.xvar ] = \
			pd.to_datetime(self.hmi_data[self.xvar])

		# Filter dataset to clean values, time period and variable selected
		self.hmi_data = self.hmi_data.loc[
			(self.hmi_data[self.xvar] >= self.start_dt - datetime.timedelta(days = 1)) &
			(self.hmi_data[self.xvar] <= self.end_dt + datetime.timedelta(days = 1))
			, 
			[self.xvar, self.yvar]
		]
		# Eliminate missing values and reset index
		self.hmi_data.dropna(axis = 0, how = 'any', inplace = True)
		self.hmi_data.reset_index(inplace = True)

		# Get numeric time elapsed
		self.first_ts = self.hmi_data[self.xvar][0]
		self.last_ts  = self.hmi_data[self.xvar][len(self.hmi_data) - 1]

		# Check to make sure that the totals/averages do not include the first
		# and last days for which data are available (just to ensure accuracy)
		if self.first_ts >= self.start_dt or self.last_ts <= self.end_dt:
			start_dt_warn = self.first_ts + np.timedelta64(1,'D')
			end_dt_warn   =  self.last_ts - np.timedelta64(1,'D')
			start_dt_warn = dt.strftime(start_dt_warn, '%m-%d-%y')
			end_dt_warn = dt.strftime(end_dt_warn, '%m-%d-%y')
			warn_msg = \
				'Given the range of data available for {0}, accurate aggregate values can only be obtained for: {1} to {2}'
			print(warn_msg.format(elid, start_dt_warn, end_dt_warn))
		

	def get_tot_var(
		self, 
		tperiod,
		elid, 
		agg_type
	):

		# Calculate time elapsed in seconds
		self.hmi_data['tel'] = \
			(self.hmi_data[self.xvar] - self.first_ts)/\
			np.timedelta64(1,'s')
		self.hmi_data['minute'] = self.hmi_data[self.xvar].values.astype('datetime64[m]')
		# Calculate time elapsed in seconds at the beginning of the given minute
		self.hmi_data['tel_mstrt'] = \
			(self.hmi_data['minute'] - self.first_ts)/\
			np.timedelta64(1,'s')
		
		# Create a variable giving the totalized component for the given section (tel to tel_next)
		self.hmi_data['tot'] =\
			(self.hmi_data['tel'].shift(-1) - self.hmi_data['tel'])*\
			(self.hmi_data[self.yvar].shift(-1) + self.hmi_data[self.yvar])/2

		# Adjust the totalized component at the beginning of each minute (add the levtover time since 00:00)
		self.hmi_data.loc[self.hmi_data['tel_mstrt'] != self.hmi_data['tel_mstrt'].shift(1),'tot'] = \
			self.hmi_data['tot'] +\
			(self.hmi_data['tel'] - self.hmi_data['tel_mstrt'])*\
			0.5*(
				self.hmi_data[self.yvar] +\
				self.hmi_data[self.yvar].shift(1) +\
				(self.hmi_data[self.yvar] - self.hmi_data[self.yvar].shift(1))/\
				(self.hmi_data['tel'] - self.hmi_data['tel'].shift(1))*\
				(self.hmi_data['tel_mstrt'] - self.hmi_data['tel'].shift(1))
			)
		
		# Adjust the totalized component at the end of each minute (subtract the time after 00:00)
		self.hmi_data.loc[self.hmi_data['tel_mstrt'] != self.hmi_data['tel_mstrt'].shift(-1),'tot'] = \
			self.hmi_data['tot'] -\
			(self.hmi_data['tel'].shift(-1) - self.hmi_data['tel_mstrt'] - 60)*\
			0.5*(
				self.hmi_data[self.yvar] + \
				self.hmi_data[self.yvar].shift(-1) + \
				(self.hmi_data[self.yvar].shift(-1) - self.hmi_data[self.yvar])/\
				(self.hmi_data['tel'].shift(-1) - self.hmi_data['tel'])*\
				(self.hmi_data['tel_mstrt'] + 60 - self.hmi_data['tel'])
			)

		# Compute the area under the curve for each time period
		nperiods = (self.end_dt - self.start_dt).days*24/tperiod
		nperiods = int(nperiods)
		tots_res = []
		for period in range(nperiods):
			start_tel = (self.start_dt - self.first_ts) / np.timedelta64(1,'s') + period*3600*tperiod
			end_tel = start_tel + 3600*tperiod
			start_ts = self.start_dt + datetime.timedelta(hours = period*tperiod)
			ip_sec = self.hmi_data.loc[
				(self.hmi_data['tel'] >= start_tel) & 
				(self.hmi_data['tel'] <= end_tel),
				'tot'
			]
			ip_tot = ip_sec.sum()/60 # Dividing by 60 because flowrates are in Gal/min or L/min
			if agg_type == 'AVERAGE':
				ip_tot = ip_tot/(60*tperiod)
			tots_row = [start_ts, ip_tot, len(ip_sec)]
			tots_res.append(tots_row)

		# Convert to pandas dataframe	
		tots_res = pd.DataFrame(tots_res, columns = ['Time', 'Value', 'observed'])
		# # Convert rows with no data to missing
		tots_res.loc[tots_res['observed'] == 0,'Value'] = np.NaN
		# Fill in these rows by interpolating between values
		# First declare as time series
		tots_res.set_index('Time', inplace = True)
		# Use built in interpolation functionality for time series
		tots_res.loc[:,'Value'] = tots_res.interpolate()
		# Convert back to df (with time as variable)
		tots_res.reset_index(inplace = True)
		return tots_res[['Time','Value']]


	def run_report(
		self,
		tperiod,
		elids,
		agg_types,
		start_dt_str,
		end_dt_str,
		hmi_path = None,
		output_csv = None
	):

		# Select input data file
		if hmi_path:
			self.hmi_path = hmi_path
			self.hmi_dir = os.path.dirname(hmi_path)
		else:
			self.hmi_path = askopenfilename(title = 'Select HMI data input file')
			self.hmi_dir = os.path.dirname(self.hmi_path)

		# Retrieve sql table directory
		table_dir = gld.get_indir()
		
		# Get dates and date strings for output filenames
		self.start_dt = dt.strptime(start_dt_str,'%m-%d-%y')
		self.end_dt = dt.strptime(end_dt_str,'%m-%d-%y')

		agg_types = [agg_type.upper() for agg_type in agg_types]

		for elid, agg_type in zip(elids, agg_types):

			# Get prepped data
			self.prep_data(elid)
			# Get totalized values'
			tots_res = self.get_tot_var(tperiod, elid, agg_type)
			# Load data to SQL
			os.chdir(table_dir)
			conn = sqlite3.connect('cr2c_hmi_agg_data.db')
			tots_res.to_sql('{0}_{1}s_{2}hour'.format(elid, agg_type, tperiod), conn, if_exists = 'append', index = False)


if __name__ == '__main__':

	# hmi_dat = hmi_data_agg(
	# 	'raw', # Type of eDNA query (case insensitive, can be raw, 1 min, 1 hour)
	# 	'gas' # Type of sensor (case insensitive, can be water, gas, pH, conductivity or temperature
	# )
	# hmi_dat.run_report(
	# 	1, # Number of hours you want to sum/average over
	# 	['FT700','FT704'], # Sensor ids that you want summary data for (have to be in HMI data file obviously)
	# 	['total','total'], # Type of aggregate function you want (can be total or average)
	# 	'10-21-17', # Start of date range you want summary data for
	# 	'10-28-17' # End of date range you want summary data for)
	# )
	# hmi_dat = hmi_data_agg(
	# 	'raw', # Type of eDNA query (case insensitive, can be raw, 1 min, 1 hour)
	# 	'water' # Type of sensor (case insensitive, can be water, gas, pH, conductivity or temperature
	# )
	# hmi_dat.run_report(
	# 	1, # Number of hours you want to sum/average over
	# 	['FT202','FT305'], # Sensor ids that you want summary data for (have to be in HMI data file obviously)
	# 	['total','total'], # Type of aggregate function you want (can be total or average)
	# 	'10-21-17', # Start of date range you want summary data for
	# 	'10-28-17' # End of date range you want summary data for)
	# )
	# hmi_dat = hmi_data_agg(
	# 	'raw', # Type of eDNA query (case insensitive, can be raw, 1 min, 1 hour)
	# 	'tmp' # Type of sensor (case insensitive, can be water, gas, pH, conductivity or temperature
	# )
	# hmi_dat.run_report(
	# 	1, # Number of hours you want to sum/average over
	# 	['AIT302'], # Sensor ids that you want summary data for (have to be in HMI data file obviously)
	# 	['average'], # Type of aggregate function you want (can be total or average)
	# 	'10-12-17', # Start of date range you want summary data for
	# 	'10-28-17' # End of date range you want summary data for)
	# )
