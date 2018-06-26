'''
	Computes a mass balance for COD-CH4 in the reactor area for any range of dates
	takes dates as inputs and outputs a summary file with mass balance info
'''

from __future__ import print_function
import matplotlib
import matplotlib.gridspec as gridspec
matplotlib.use("TkAgg",force=True) 
import matplotlib.pyplot as plt
import matplotlib.ticker as tkr
import matplotlib.dates as dates
import pylab as pl
import numpy as np
import scipy as sp
from scipy import interpolate as ip
import pandas as pd
import datetime as datetime
from datetime import timedelta
from datetime import datetime as dt
from pandas import read_excel
import os
import sys
import math
import functools
from tkinter.filedialog import askopenfilename
from tkinter.filedialog import asksaveasfilename
from tkinter.filedialog import askdirectory
from scipy import stats 

import cr2c_labdata as pld
import cr2c_hmidata as hmi
import cr2c_fielddata as fld
from cr2c_hmidata import hmi_data_agg as hmi_run


class cr2c_validation:

	def __init__(
		self, 
		outdir = None, 
		hmi_path = None, 
		run_agg_feeding = False, 
		run_agg_gasprod = False, 
		run_agg_temp = False,
		run_agg_press = False
	):
		
		if not outdir:
			tkTitle = 'Directory to output summary statistics/plots to'
			print(tkTitle)
			outdir = askdirectory(title = tkTitle)

		self.outdir = outdir
		self.hmi_path = hmi_path
		self.run_agg_feeding = run_agg_feeding
		self.run_agg_gasprod = run_agg_gasprod
		self.run_agg_temp = run_agg_temp
		self.afbr_vol = 1100 # in L
		self.afmbr_vol = 1700 # in L
		self.react_vol = 2800 # in L
		self.cod_bal_wkly = pd.DataFrame([])


	def adj_Hcp(self, Hcp_gas, deriv_gas, temp):
		return Hcp_gas*math.exp(deriv_gas*(1/(273 + temp) - (1/298)))


	def clean_varname(self, varname):
		varname_cln = fld.rmChars('-:?[]()<>.,','',varname)
		varname_cln = fld.rmChars(' ','_',varname_cln)
		return varname_cln


	def est_diss_ch4(self, temp, percCH4):
		
		# =======> UNITS OF INPUT VARIABLES <=======
		# gasVol in sL/m 
		# temp in C 
		# percents as decimals x 100
		# Assumed Henry's constants (from Sander 2015)
		# Units of mM/atm @ 25 degrees C
		Hcp_CH4 = 1.4
		# Assumed Clausius-Clapeyron Constants (dlnHcp/d(l/T))
		deriv_ccCH4 = 1900
		# Volume of gas at STP (L/mol)
		Vol_STP = 22.4
		# Adjust gas constants to temperature
		Hcp_CH4_adj = self.adj_Hcp(Hcp_CH4, deriv_ccCH4, temp)
		# Moles of CH4: 1 mole of CH4 is 64 g of BOD
		CH4_gas_atm = percCH4/100
		# Assuming 1atm in reactors 
		# (this is a good assumption, even 10 inches on manometer is equivalent to just 0.02 atm)
		COD_diss_conc = CH4_gas_atm*Hcp_CH4_adj*64

		return COD_diss_conc


	# Function to estimate the sum of a set of variables in a pandas dataframe
	def get_sumvar(self, df, coefs):

		nvars = len(coefs)

		# Make sure there are as many coefficients as variables being summed
		# Need to make this a proper error message
		if len(df.columns) != nvars:
			print('The number of coefficients and DataFrame columns must be equal!')
			sys.exit()

		# Convert the list of coefficients to a length nvars vector
		coefs = np.array(coefs).reshape(nvars,1)
		# Create nvar copies of that vector
		coefcop = np.tile(coefs,(1,nvars))
		# Get all pairwise products of coefficients
		coefmat = np.matmul(coefcop,np.eye(nvars)*coefs)
		# Get covariance matrix from columns in dataset
		cov = df.cov().values
		# Sum the elementwise coefficient products by the covariances to get variance of sum
		sumvar = np.multiply(cov, coefmat).sum().sum()

		return sumvar


	def get_cod_bal(
		self,
		end_dt_str,
		nweeks,
		plot = True,
		table = True
	):
		
		# Window for moving average calculation
		ma_win = 1
		end_dt   = dt.strptime(end_dt_str,'%m-%d-%y').date()
		start_dt = end_dt - timedelta(days = 7*nweeks)
		start_dt = start_dt
		start_dt_str = dt.strftime(start_dt, '%m-%d-%y')
		start_dt_query = start_dt - timedelta(days = ma_win)
		start_dt_qstr = dt.strftime(start_dt_query,'%m-%d-%y')

		# HMI element IDs for gas, temperature and influent/effluent flow meters 
		gas_elids  = ['FT700','FT704']
		temp_elids = ['AT304','AT310']
		inf_elid   = 'FT202'
		eff_elid   = 'FT305'
		# Length of time period for which data are being queried
		perLen = 1
		# Type of time period for which data are being queried
		tperiod = 'HOUR'

		# Reactor volumes
		l_p_gal = 3.78541 # Liters/Gallon
		# L in a mol of gas at STP
		Vol_STP = 22.4

		#=========================================> HMI DATA <=========================================
		
		# If requested, run the hmi_data_agg script for the reactor meters and time period of interest
		if self.run_agg_feeding or self.run_agg_gasprod or self.run_agg_temp:
			get_hmi = hmi_run(start_dt_str, end_dt_str, hmi_path = self.hmi_path)
		if self.run_agg_feeding:
			get_hmi.run_report(
				[perLen]*2, # Number of hours you want to average over
				[tperiod]*2, # Type of time period (can be "hour" or "minute")
				[inf_elid, eff_elid], # Sensor ids that you want summary data for (have to be in HMI data file obviously)
				['water']*2, # Type of sensor (case insensitive, can be water, gas, pH, conductivity, temp, or tmp
			)	
		if self.run_agg_gasprod:
			get_hmi.run_report(
				[perLen]*len(gas_elids), # Number of hours you want to average over
				[tperiod]*len(gas_elids), # Type of time period (can be "hour" or "minute")
				gas_elids, # Sensor ids that you want summary data for (have to be in HMI data file obviously)
				['gas']*len(gas_elids), # Type of sensor (case insensitive, can be water, gas, pH, conductivity, temp, or tmp
			)
		if self.run_agg_temp:
			get_hmi.run_report(
				[perLen]*len(temp_elids), # Number of hours you want to average over
				[tperiod]*len(temp_elids), # Type of time period (can be "hour" or "minute")
				temp_elids, # Sensor ids that you want summary data for (have to be in HMI data file obviously)
				['temp']*len(temp_elids), # Type of sensor (case insensitive, can be water, gas, pH, conductivity, temp, or tmp
			)

		# Read in the data
		gasprod_dat = hmi.get_data(
			gas_elids,
			[perLen]*len(gas_elids),
			[tperiod]*len(gas_elids), 
			start_dt_str = start_dt_str, 
			end_dt_str = end_dt_str
		)
		# Do the same for feeding and temperature
		feeding_dat = hmi.get_data(
			[inf_elid, eff_elid],
			[perLen]*2, 
			[tperiod]*2, 
			start_dt_str = start_dt_str,
			end_dt_str = end_dt_str
		)
		temp_dat = hmi.get_data(
			temp_elids,
			[perLen]*len(temp_elids), 
			[tperiod]*len(temp_elids), 
			start_dt_str = start_dt_str,
			end_dt_str = end_dt_str
		) 
		# Prep the HMI data
		gasprod_dat['Meas Biogas Prod'] = (gasprod_dat['FT700'] + gasprod_dat['FT704'])*60*perLen
		gasprod_dat['Date'] = gasprod_dat['Time'].dt.date
		gasprod_dat_cln = gasprod_dat[['Date','Meas Biogas Prod']]
		gasprod_dat_cln = gasprod_dat_cln.groupby('Date').sum()
		gasprod_dat_cln.reset_index(inplace = True)

		# Feeding HMI Data
		feeding_dat['Flow In']  = feeding_dat[inf_elid]*60*perLen*l_p_gal
		feeding_dat['Flow Out'] = feeding_dat[eff_elid]*60*perLen*l_p_gal
		feeding_dat['Date'] = feeding_dat['Time'].dt.date
		feeding_dat_cln = feeding_dat[['Date','Flow In','Flow Out']]
		feeding_dat_cln = feeding_dat_cln.groupby('Date').sum()
		feeding_dat_cln.reset_index(inplace = True)

		# Reactor Temperature HMI data
		temp_dat['Reactor Temp (C)'] = \
			(temp_dat['AT304']*self.afbr_vol + temp_dat['AT310']*self.afmbr_vol)/self.react_vol
		temp_dat['Date'] = temp_dat['Time'].dt.date
		temp_dat_cln = temp_dat[['Date','Reactor Temp (C)']]
		temp_dat_cln = temp_dat_cln.groupby('Date').mean()
		temp_dat_cln.reset_index(inplace = True)

		# List of hmi dataframes
		hmi_dflist = [feeding_dat_cln, gasprod_dat_cln, temp_dat_cln]
		# Merge hmi datasets
		hmidat_ud = functools.reduce(
			lambda left,right: pd.merge(left,right, on = 'Date', how = 'outer'), 
			hmi_dflist
		)

		#=========================================> HMI DATA <=========================================

		#=========================================> LAB DATA <=========================================
		# Get lab data from file on box and filter to desired dates
		labdat  = pld.get_data(['COD','TSS_VSS','Sulfate','GasComp'])

		# COD data
		cod_dat = labdat['COD']
		cod_dat['Date'] = cod_dat['Date_Time'].dt.date
		# Drop duplicates
		cod_dat.drop_duplicates(keep = 'first', inplace = True)
		# Get average of multiple values taken on same day
		cod_dat = cod_dat.groupby(['Date','Stage','Type']).mean()
		# Convert to wide to get COD in and out of the reactors
		cod_dat_wide = cod_dat.unstack(['Stage','Type'])
		cod_dat_wide['CODt MS'] = cod_dat_wide['Value']['Microscreen']['Total']
		# Weighted aveage COD concentrations in the reactors
		cod_dat_wide['CODt R'] = \
			(cod_dat_wide['Value']['AFBR']['Total']*self.afbr_vol +\
			cod_dat_wide['Value']['Duty AFMBR MLSS']['Total']*self.afmbr_vol)/\
			(self.react_vol)
		cod_dat_wide['CODt Out'] = cod_dat_wide['Value']['Duty AFMBR Effluent']['Total']
		cod_dat_wide.reset_index(inplace = True)
		cod_dat_cln = cod_dat_wide[['Date','CODt MS','CODt R','CODt Out']]
		cod_dat_cln.columns = ['Date','CODt MS','CODt R','CODt Out']

		# Gas Composition Data
		gc_dat = labdat['GasComp']
		gc_dat['Date'] = gc_dat['Date_Time'].dt.date
		gc_dat = gc_dat.loc[(gc_dat['Type'].isin(['Methane (%)','Carbon Dioxide (%)']))]
		gc_dat = gc_dat.groupby(['Date','Type']).mean()
		gc_dat_wide = gc_dat.unstack('Type')
		gc_dat_wide['CH4%'] = gc_dat_wide['Value']['Methane (%)']
		gc_dat_wide['CO2%'] = gc_dat_wide['Value']['Carbon Dioxide (%)']
		gc_dat_wide.reset_index(inplace = True)
		gc_dat_cln = gc_dat_wide[['Date','CH4%','CO2%']]
		gc_dat_cln.columns = ['Date','CH4%','CO2%']

		# VSS Data
		vss_dat = labdat['TSS_VSS']
		vss_dat['Date'] = vss_dat['Date_Time'].dt.date
		# Drop duplicates
		vss_dat.drop_duplicates(keep = 'first', inplace = True)
		# Get average of multiple values taken on same day
		vss_dat = vss_dat.groupby(['Date','Stage','Type']).mean()

		# Convert to wide to get COD in and out of the reactors
		vss_dat_wide = vss_dat.unstack(['Stage','Type'])
		# Weighted aveage COD concentrations in the reactors
		vss_dat_wide['VSS R'] = \
			(vss_dat_wide['Value']['AFBR']['VSS']*self.afbr_vol +\
			vss_dat_wide['Value']['Duty AFMBR MLSS']['VSS']*self.afmbr_vol)/\
			(self.afbr_vol + self.afmbr_vol)
		vss_dat_wide['VSS Out'] = vss_dat_wide['Value']['Duty AFMBR Effluent']['VSS']
		vss_dat_wide.reset_index(inplace = True)
		vss_dat_cln = vss_dat_wide[['Date','VSS R','VSS Out']]
		vss_dat_cln.columns = ['Date','VSS R','VSS Out']	

		# Solids Wasting Data
		waste_dat = fld.get_data(['AFMBR_Volume_Wasted_Gal'])
		# waste_dat = waste_dat.loc[:,['Timestamp','AFMBR_Volume_Wasted_Gal']]

		waste_dat['Date'] = pd.to_datetime(waste_dat['Timestamp']).dt.date
		waste_dat['AFMBR Volume Wasted (Gal)'] = waste_dat['AFMBR_Volume_Wasted_Gal'].astype('float')
		waste_dat['Wasted (L)'] = waste_dat['AFMBR Volume Wasted (Gal)']*l_p_gal
		waste_dat_cln = waste_dat[['Date','Wasted (L)']]

		# Sulfate data
		so4_dat = labdat['Sulfate']
		so4_dat['Date'] = so4_dat['Date_Time']
		so4_dat.set_index(['Date','Stage'], inplace = True)
		so4_dat_wide = so4_dat.unstack(['Stage'])
		so4_dat_wide['SO4 MS'] = so4_dat_wide['Value']['Microscreen']
		so4_dat_wide.reset_index(inplace = True)
		so4_dat_cln = so4_dat_wide[['Date','SO4 MS']]
		so4_dat_cln.columns = ['Date','SO4 MS']
		so4_dat_cln.loc[:,'Date'] = so4_dat_cln['Date'].dt.date
		
		# List of lab dataframes
		lab_dflist = [cod_dat_cln, gc_dat_cln, waste_dat_cln, so4_dat_cln, vss_dat_cln]

		# Merge lab datasets
		labdat = functools.reduce(lambda left,right: pd.merge(left,right, on='Date', how = 'outer'), lab_dflist)
		# Get daily average of readings if multiple readings in a day (also prevents merging issues!)
		labdat_ud = labdat.groupby('Date').mean()
		labdat_ud.reset_index(inplace = True)
		#=========================================> LAB DATA <=========================================

		#=======================================> MERGE & PREP <=======================================		
		
		# Merge Lab and HMI
		cod_bal_dat = labdat_ud.merge(hmidat_ud, on = 'Date', how = 'outer')
		# Dedupe (merging many files, so any duplicates can cause big problems!)
		cod_bal_dat.drop_duplicates(inplace = True)

		# Convert missing wasting data to 0 (assume no solids wasted that day)
		cod_bal_dat.loc[np.isnan(cod_bal_dat['Wasted (L)']),'Wasted (L)'] = 0
		# Fill in missing lab data
		# First get means of observed data
		cod_bal_means = \
			cod_bal_dat[[
				'CH4%','CO2%',
				'CODt MS','CODt R','CODt Out',
				'VSS R','VSS Out',
				'SO4 MS'
			]].mean()
		# Then interpolate
		cod_bal_dat.sort_values(['Date'], inplace = True)
		cod_bal_dat.set_index('Date', inplace = True)
		cod_bal_dat[[
			'CH4%','CO2%',
			'CODt MS','CODt R','CODt Out',
			'VSS R','VSS Out',
			'SO4 MS'
		]] = \
			cod_bal_dat[[
				'CH4%','CO2%',
				'CODt MS','CODt R','CODt Out',
				'VSS R','VSS Out',
				'SO4 MS'
			]].interpolate()

		# Then fill remaining missing values with the means of all variables
		fill_values = {
			'CH4%': cod_bal_means['CH4%'],
			'CO2%': cod_bal_means['CO2%'],
			'CODt MS': cod_bal_means['CODt MS'],
			'CODt R': cod_bal_means['CODt R'],
			'CODt Out': cod_bal_means['CODt Out'],
			'VSS R': cod_bal_means['VSS R'],
			'VSS Out': cod_bal_means['VSS Out'],
			'SO4 MS': cod_bal_means['SO4 MS']
		}
		cod_bal_dat.fillna(value = fill_values, inplace = True)

		# Get moving average of COD in reactors (data bounce around a lot)
		cod_cols = ['CODt MS','CODt R','CODt Out']
		cod_bal_dat[cod_cols] = cod_bal_dat[cod_cols].rolling(ma_win).mean()
		# Reset index
		cod_bal_dat.reset_index(inplace = True)
		# Put dates into weekly bins (relative to end date), denoted by beginning of week
		cod_bal_dat['Weeks Back'] = \
			pd.to_timedelta(np.floor((cod_bal_dat['Date'] - end_dt)/np.timedelta64(7,'D'))*7, unit = 'D')
		cod_bal_dat['Week Start'] = end_dt + cod_bal_dat['Weeks Back']
		cod_bal_dat = cod_bal_dat.loc[
			(cod_bal_dat['Date'] >= start_dt) & (cod_bal_dat['Date'] <= end_dt),
			:
		]

		#=======================================> MERGE & PREP <=======================================	

		#========================================> COD Balance <=======================================	
		# Note: dividing by 1E6 to express in kg
		# COD coming in from the Microscreen
		cod_bal_dat['COD In']   = cod_bal_dat['CODt MS']*cod_bal_dat['Flow In']/1E6
		# COD leaving the reactor
		cod_bal_dat['COD Out']  = cod_bal_dat['CODt Out']*cod_bal_dat['Flow Out']/1E6
		# COD wasted
		cod_bal_dat['COD Wasted'] = cod_bal_dat['CODt R']*cod_bal_dat['Wasted (L)']/1E6
		# COD content of gas (assumes that volume given by flowmeter is in STP)
		cod_bal_dat['Biogas']   = cod_bal_dat['Meas Biogas Prod']*cod_bal_dat['CH4%']/100/Vol_STP*64/1000
		# COD content of dissolved methane (estimated from temperature of reactors)
		cod_diss_conc = map(
			self.est_diss_ch4,
			cod_bal_dat['Reactor Temp (C)'].values, 
			cod_bal_dat['CH4%'].values
		)

		cod_bal_dat['Dissolved CH4'] = np.array(list(cod_diss_conc))*cod_bal_dat['Flow Out']/1E6
		# COD from sulfate reduction (1.5g COD per g SO4, units are in mg/L S)
		cod_bal_dat['Sulfate Reduction'] = cod_bal_dat['SO4 MS']*cod_bal_dat['Flow In']/1.5/1E6*48/16
		#========================================> COD Balance <=======================================	

		# Convert to weekly data
		cod_bal_wkly = cod_bal_dat.groupby('Week Start').sum(numeric_only = True)
		cod_bal_wkly.reset_index(inplace = True)
		cod_bal_wkly.loc[:,'Week Start'] = cod_bal_wkly['Week Start'].dt.date
		cod_bal_wkly = cod_bal_wkly.loc[cod_bal_wkly['Week Start'] < end_dt,:]

		#===========================================> Plot! <==========================================
		if plot:
			fig, ax = plt.subplots()
			title = fig.suptitle('Weekly COD Mass Balance', fontsize = 14, fontweight = 'bold', y = 0.95)
			nWeeks = np.arange(len(cod_bal_wkly))
			bWidth = 0.8
			pBiogas = plt.bar(nWeeks,cod_bal_wkly['Biogas'], bWidth)
			bottomCum = cod_bal_wkly['Biogas'].values
			pOut = plt.bar(nWeeks,cod_bal_wkly['COD Out'], bWidth, bottom = bottomCum)
			bottomCum += cod_bal_wkly['COD Out']
			pDiss = plt.bar(nWeeks,cod_bal_wkly['Dissolved CH4'], bWidth, bottom = bottomCum)
			bottomCum += cod_bal_wkly['Dissolved CH4']
			pWasted = plt.bar(nWeeks,cod_bal_wkly['COD Wasted'], bWidth, bottom = bottomCum)
			bottomCum += cod_bal_wkly['COD Wasted']
			pSO4 = plt.bar(nWeeks,cod_bal_wkly['Sulfate Reduction'], bWidth, bottom = bottomCum)
			pIn = plt.scatter(nWeeks,cod_bal_wkly['COD In'], c = 'r')
			plt.xticks(nWeeks,cod_bal_wkly['Week Start'], rotation = 45) 
			lgd = ax.legend(
				# (pIn,pBiogas[0],pOut[0],pDiss[0],pWasted[0],pSO4[0]),
				(pIn,pSO4[0],pWasted[0],pDiss[0],pOut[0],pBiogas[0]),
				('COD In','Sulfate Reduction','Solids Wasting','Dissolved CH4','COD Out','Biogas'),
				loc= 'center left',
				bbox_to_anchor = (1, 0.5), 
				fancybox = True, 
				shadow = True, 
				ncol = 1
			)
			plt.ylabel('kg of COD Equivalents',fontweight = 'bold')
			plt.xlabel('Week Start Date', fontweight = 'bold')

			plt.savefig(
				os.path.join(self.outdir, 'COD Balance.png'),
				bbox_extra_artists=(lgd,title,),
				width = 50,
				height = 50,
				bbox_inches = 'tight'
			) 
			plt.close()
		#===========================================> Plot! <==========================================		
		self.cod_bal_wkly = cod_bal_wkly

		if table:
			cod_bal_wkly[['Week Start','COD In','COD Out','Biogas','COD Wasted','Dissolved CH4','Sulfate Reduction']].\
			to_csv(
				os.path.join(self.outdir, 'COD Balance.csv'),
				index = False,
				encoding = 'utf-8'				
			)

	# Calculate basic biotechnology parameters to monitor biology in reactors
	def get_biotech_params(
		self,
		end_dt_str,
		nWeeks,
		plot = True,
		table = True
	):
		
		if self.cod_bal_wkly.empty:
			self.get_cod_bal(end_dt_str, nWeeks, plot = False)

		# Dividing by 1E6 and 7 because units are totals for week and are in mg/L
		# whereas COD units are in kg
		self.cod_bal_wkly['gVSS wasted/gCOD Removed'] = \
			(
				self.cod_bal_wkly['VSS R']*self.cod_bal_wkly['Wasted (L)'] + 
				self.cod_bal_wkly['VSS Out']*self.cod_bal_wkly['Flow Out']
			)/1E6/7/\
			(self.cod_bal_wkly['COD In'] - self.cod_bal_wkly['COD Out'] - self.cod_bal_wkly['Sulfate Reduction'])

		# No need to divide VSS concentration by 1E6 or 7 because same units in numerator and denominator
		self.cod_bal_wkly['VSS SRT (days)'] = \
			self.cod_bal_wkly['VSS R']*(self.afbr_vol + self.afmbr_vol)/\
			(
				self.cod_bal_wkly['VSS R']*self.cod_bal_wkly['Wasted (L)'] + \
				self.cod_bal_wkly['VSS Out']*self.cod_bal_wkly['Flow Out']
			)*7

		vss_params = self.cod_bal_wkly[['Week Start','VSS SRT (days)','gVSS wasted/gCOD Removed']]

		if plot:
			fig, (ax1, ax2) = plt.subplots(2, 1, sharey = False)
			title = fig.suptitle(
				'Weekly VSS Wasting Parameters (last 8 weeks)',
				fontweight = 'bold',
				fontsize = 14,
				y = 0.95

			)
			fig.subplots_adjust(top = 0.85)
			ax1.plot(
				vss_params['Week Start'], 
				vss_params['gVSS wasted/gCOD Removed'],
				linestyle = '-', marker = "o"
			)
			ax1.grid(True, axis = 'y', linestyle = '--')
			plt.sca(ax1)
			ax1.xaxis.set_ticklabels([])
			plt.ylabel('gVSS wast./gCOD rem.')
			plt.ylim(ymin = 0)
			ax2.plot(
				vss_params['Week Start'], 
				vss_params['VSS SRT (days)'],
				linestyle = '-', marker = "o"
			)
			ax2.grid(True, axis = 'y', linestyle = '--')
			plt.sca(ax2)
			plt.xticks(rotation = 45)
			plt.ylabel('VSS SRT (d)') 
			plt.ylim(ymin = 0)
			plt.xlabel('Week Start Date')
			plt.savefig(
				os.path.join(self.outdir, 'VSS Removal.png'),
				width = 30,
				height = 120,
				bbox_extra_artists=(title,),
				bbox_inches = 'tight'
			) 
			plt.close()

		if table:
			vss_params.to_csv(
				os.path.join(self.outdir, 'VSS Parameters.csv'),
				index = False,
				encoding = 'utf-8'
			)


	'''
	Verify pressure sensor readings from HMI data and manometer readings from Google sheets.
	Calculate water head from pressure sensor readings, and compare it with the manometer readings.
	Plot the merged data to show results.
	'''
	def instr_val(
		self,
		valtypes,
		start_dt_str,
		end_dt_str,
		hmi_elids,
		fld_varnames = None,
		ltypes = None,
		lstages = None,
		run_hmi_report = False,
		hmi_path = None
	):


		# Validation data are from field measurements (daily log sheet)
		if fld_varnames:

			query_varnames = ['Barometer Pressure (mmHg)']
			for varname in fld_varnames:
				# Sometimes the user needs to specify a PAIR of variables (eg pressure upstream AND downstream of pump)
				if type(varname) == tuple:
					query_varnames.append(varname[0])
					query_varnames.append(varname[1])
				# Otherwise just single variable name
				else:
					query_varnames.append(varname)

			# Clean the query variables
			query_varnames = [self.clean_varname(varname) for varname in query_varnames]
			# Query the field data (using clean variable names)
			valdat = fld.get_data()[['Timestamp'] + query_varnames]
			# Create time variable with minute resolution from field data Timestamp variable
			valdat['Time'] = pd.to_datetime(valdat['Timestamp']).values.astype('datetime64[m]')
			# Replace missing barometric pressure readings with the mean psi at sea level
			valdat.loc[:,'Barometer_Pressure_mmHg'] = pd.to_numeric(valdat['Barometer_Pressure_mmHg'], errors = 'coerce')
			valdat.loc[np.isnan(valdat['Barometer_Pressure_mmHg']),'Barometer_Pressure_mmHg'] = 760
			
			# Loop through field variables to convert to numeric and calculate differences (if necessary)
			for varInd,varname in enumerate(fld_varnames):
				if type(varname) == tuple:
					valdat[hmi_elids[varInd] + 'VAL'] = \
						pd.to_numeric(valdat[self.clean_varname(varname[1])], errors = 'coerce') - \
						pd.to_numeric(valdat[self.clean_varname(varname[0])], errors = 'coerce')
				else:
					valdat[hmi_elids[varInd] + 'VAL'] = pd.to_numeric(valdat[self.clean_varname(varname)], errors = 'coerce')

			valdat = valdat[['Time','Barometer_Pressure_mmHg'] + [elid + 'VAL' for elid in hmi_elids]]
		
		# Validation data are from lab measurements
		elif ltypes or lstages:

			valdatLong = pd.concat([pld.get_data([ltype])[ltype] for ltype in ltypes], axis = 0)
			valdatLong = valdatLong.loc[valdatLong['Stage'].isin(lstages),:]
			# Convert to wide format
			# Calculate mean by obsid to account for possibility of multiple PH measurements taken for single sample
			valdatLong = valdatLong.groupby(['Date_Time','Stage','Type','obs_id']).mean()
			valdatWide = valdatLong.unstack(['Type','Stage'])
			valdatWide.reset_index(inplace = True)
			# valdat = valdatWide['Date_Time']
			valdat = pd.DataFrame(valdatWide['Date_Time'].values, columns = ['Time'])
			valdatColnames = [hmi_elids[lind] + 'VAL' for lind,ltype in enumerate(ltypes)]
			for lind,ltype in enumerate(ltypes):
				valdat[valdatColnames[lind]] = valdatWide['Value'][ltype][lstages[lind]]
			valdat = valdat[['Time'] + valdatColnames]


		# Expand valdat to get copies of each logged value for each of:
		# 10 minutes before and 10 minutes after it was entered into the google form
		valdatList = []
		for minDiff in range(-10,11):
			valdatDiff = valdat.copy()
			valdatDiff['Time']  = valdatDiff['Time'] + timedelta(seconds = minDiff*60)
			valdatList.append(valdatDiff)
		valdatAll = pd.concat(valdatList, axis = 0)

		# Get hmi data for the element ids whose measurements are being validated
		nelids = len(hmi_elids)
		# Run hmi report if requested (minute level)
		if run_hmi_report:

			hmi_run = hmi.hmi_data_agg(start_dt_str, end_dt_str, hmi_path = hmi_path)
			hmi_run.run_report(
				[1]*nelids, # Number of minutes you want to average over
				['MINUTE']*nelids, # Type of time period (can be "hour" or "minute")
				hmi_elids, # Sensor ids that you want summary data for (have to be in HMI data file obviously)
				valtypes # Type of sensor (case insensitive, can be water, gas, pH, conductivity, temp, or tmp
			)

		# Retrieve data from SQL file
		hmidat = hmi.get_data(
			hmi_elids,
			[1]*nelids,
			['MINUTE']*nelids,
			valtypes,
			start_dt_str = start_dt_str,
			end_dt_str = end_dt_str
		)

		# Merge the hmi data with the validation data
		valdatMerged = hmidat.merge(valdatAll, on = 'Time', how = 'inner')
		# Merge all values on a day (since we are validating on a -10 to +10 minute window)
		valdatMerged.loc[:,'Date'] = valdatMerged['Time'].dt.date
		# Take average of time Window
		valdatMerged = valdatMerged.groupby('Date').mean()
		valdatMerged.reset_index(inplace = True)
		valdatMerged.loc[:,'Date'] = pd.to_datetime(valdatMerged['Date'])

		# Loop through each instrument to compute error and output plots 
		# IF evidence of a significant difference between validated vs hmi or if instrument drift over time
		for elInd, elid in enumerate(hmi_elids):
			if valtypes[elInd] == 'PRESSURE':
				# Convert barometric pressure readings to psi
				valdatMerged.loc[:,'Barometer_Pressure_mmHg'] = valdatMerged['Barometer_Pressure_mmHg']*0.0193368
				# Convert pressure to inches of head
				valdatMerged.loc[:,elid] = (valdatMerged[elid] - valdatMerged['Barometer_Pressure_mmHg'])*27.7076

			# Compute the percentage error (HMI measurement vs validation)
			valdatMerged.loc[:,'error'] = (valdatMerged[elid] - valdatMerged[elid + 'VAL'])/valdatMerged[elid + 'VAL']
			
			# Subset to the element of interest
			valdatSub = valdatMerged.loc[:,['Date', elid, elid + 'VAL','error']]
			valdatSub.replace([np.inf, -np.inf], np.nan, inplace = True)
			valdatSub.dropna(inplace = True)

			# Only continue if there are observations (sometimes there arent...)
			if valdatSub.size > 0:
				# Convert time to numeric variable
				valX = pd.to_numeric(valdatSub.loc[:,'Date'])/(10**9*3600*24)
				# Perform 2-sample t-test for difference in means
				tStatMeans, pvalMeans = stats.ttest_ind(valdatSub[elid].values,valdatSub[elid + 'VAL'].values)
				# Regress error on time (to test for drift), divide by 10**9*3600*24 so coefficients are in terms of days
				slope, intercept, Rsq, pValTrend, stdErr = stats.linregress(valX, valdatSub['error'].values)
				
				# If drift is significant at the 10% level, or if means are significantly different, produce a plot with a warning
				if pValTrend < 0.1  or pvalMeans < 0.1:
					fig, ax = plt.subplots(1,1)
					gs1 = gridspec.GridSpec(1, 1)
					fig.subplots_adjust(top = 0.90, right = 0.7)
					title = fig.suptitle(
						'Instrument Validation: {0}'.format(elid),
						fontweight = 'bold',
						fontsize = 12,
						y = 0.99
					)
					dates = [pd.to_datetime(date) for date in valdatSub['Date'].dt.date.values]
					measure = ax.scatter(dates,valdatSub[elid], marker = 'o')
					validated = ax.scatter(dates,valdatSub[elid + 'VAL'], color = 'r', marker = 'o')
					ax.text(
						0.8,0.15, 
						'p-Value (Trend): {0}'.format(round(pValTrend,3)), 
						bbox=dict(facecolor='black', alpha = 0.1),
						transform = ax.transAxes
					)
					ax.text(
						0.8,0.05, 
						'p-Value (Diff.): {0}'.format(round(pvalMeans,3)),
						bbox=dict(facecolor='black', alpha = 0.1),
						transform = ax.transAxes
					)
					plt.xlim(min(dates) - timedelta(days = 1),max(dates) + timedelta(days = 1))
					plt.xticks(rotation = 45)
					lgd = ax.legend(
						('HMI Value','Validated Measure'),
						loc= 'center left',
						bbox_to_anchor = (0.75, 0.90), 
						fancybox=True
					)
					plt.tight_layout()

					# Output plot to directory of choice
					plot_filename  = "InstrumentValidation_{0}.png".format(elid)
					fig = matplotlib.pyplot.gcf()
					fig.set_size_inches(10, 5)
					plt.savefig(
						os.path.join(self.outdir, plot_filename),
						bbox_extra_artists=(lgd,title)
					)
					plt.close()

		return


# val = cr2c_validation(outdir = '/Users/josebolorinos/Google Drive/Codiga Center/Miscellany')
# val.instr_val(
# 	valtypes = ['PH','PH'],
# 	start_dt_str = '4-15-18',
# 	end_dt_str = '5-15-18',
# 	hmi_elids = ['AT203','AT305'],
# 	ltypes = ['PH','PH'],
# 	lstages = ['Microscreen','AFBR']
# 	# run_hmi_report = True,
# 	# hmi_path = '/Users/josebolorinos/Google Drive/Codiga Center/HMI Data/Reactor Feeding - Raw_20180516121705.csv'
# )
# # val.instr_val(
# # 	valtypes = ['DPI','DPI','PRESSURE','PRESSURE'],
# # 	start_dt_str = '4-15-18',
# # 	end_dt_str = '5-15-18',
# # 	hmi_elids = ['DPIT300','DPIT301','PIT700','PIT704'],
# # 	fld_varnames = [('Before Pump: R300','After Pump: R300'),('Before Pump: R301','After Pump: R301'),'Manometer Pressure: R300','Manometer Pressure: R301'],
# # 	# run_hmi_report = True,
# # 	# hmi_path = '/Users/josebolorinos/Google Drive/Codiga Center/HMI Data/Reactor Feeding - Raw_20180516121705.csv'
# # )



