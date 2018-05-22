import numpy as np
import obspy
import os
import mpi4py as MPI
from mpi4py import MPI
import matplotlib.pyplot as plt
import geographiclib.geodesic as geo
from obspy.geodetics import degrees2kilometers

from Inversion_problems import Inversion_problem
from Misfit import Misfit
from Source_code import Source_code
from Plots import Plots
from Seismogram import Seismogram


class MH_algorithm:
    def __init__(self, PARAMETERS, sampler, db, data, traces):
        self.db = db
        self.par = PARAMETERS
        self.sampler = sampler
        self.d_obs = data
        self.traces = traces
        self.dt = 1 / (traces[0].meta.sampling_rate)

        # Misfit Variance, which should not differ during the MC algorithm:
        d_obs_mean = np.mean(self.d_obs)
        self.var = self.sampler['var_est'] * d_obs_mean

    def model_samples(self):
        epi_sample = np.random.uniform(self.sampler['epi']['range_min'], self.sampler['epi']['range_max'])
        depth_sample = np.around(
            np.random.uniform(self.sampler['depth']['range_min'], self.sampler['depth']['range_max']), decimals=1)

        # Time sampler:
        year = self.par['origin_time'].year  # Constant
        month = self.par['origin_time'].month  # Constant
        day = self.par['origin_time'].day  # Constant
        hour = self.par['origin_time'].hour  # Constant
        sec = int(np.random.uniform(self.par['origin_time'].second, self.sampler['time_range']))
        if sec > int(59):
            sec_new = 59 - sec
            min = self.par['origin_time'].minute + 1  # Constant
        else:
            sec_new = sec
            min = min = self.par['origin_time'].minute
        time_sample = obspy.UTCDateTime(year, month, day, hour, min, sec_new)

        return epi_sample, depth_sample, time_sample

    def model_samples_sdr(self):
        strike_sample = np.random.uniform(self.sampler['strike']['range_min'], self.sampler['strike']['range_max'])
        dip_sample = np.random.uniform(self.sampler['dip']['range_min'], self.sampler['dip']['range_max'])
        rake_sample = np.random.uniform(self.sampler['rake']['range_min'], self.sampler['rake']['range_max'])
        return strike_sample, dip_sample, rake_sample

    def generate_G(self, epi, depth, t):
        azimuth = self.par['az']

        gf = self.db.get_greens_function(epicentral_distance_in_degree=epi, source_depth_in_m=depth,
                                         origin_time=t, kind=self.par['kind'], kernelwidth=self.par['kernelwidth'],
                                         definition=self.par['definition'])
        tss = gf.traces[0].data
        zss = gf.traces[1].data
        rss = gf.traces[2].data
        tds = gf.traces[3].data
        zds = gf.traces[4].data
        rds = gf.traces[5].data
        zdd = gf.traces[6].data
        rdd = gf.traces[7].data
        zep = gf.traces[8].data
        rep = gf.traces[9].data

        G_z = gf.traces[0].meta['npts']
        G_r = gf.traces[0].meta['npts'] * 2
        G_t = gf.traces[0].meta['npts'] * 3
        G = np.ones((G_t, 5))
        G[0:G_z, 0] = zss * (0.5) * np.cos(2 * np.deg2rad(azimuth)) - zdd * 0.5
        G[0:G_z, 1] = - zdd * 0.5 - zss * (0.5) * np.cos(2 * np.deg2rad(azimuth))
        # G[0:G_z, 1] =  zdd * (1/3) + zep * (1/3)
        G[0:G_z, 2] = zss * np.sin(2 * np.deg2rad(azimuth))
        G[0:G_z, 3] = -zds * np.cos(np.deg2rad(azimuth))
        G[0:G_z, 4] = -zds * np.sin(np.deg2rad(azimuth))

        G[G_z:G_r, 0] = rss * (0.5) * np.cos(2 * np.deg2rad(azimuth)) - rdd * 0.5
        G[G_z:G_r, 1] = -0.5 * rdd - rss * (0.5) * np.cos(2 * np.deg2rad(azimuth))
        # G[G_z:G_r, 1] =  rdd * (1/3) + rep * (1/3)
        G[G_z:G_r, 2] = rss * np.sin(2 * np.deg2rad(azimuth))
        G[G_z:G_r, 3] = -rds * np.cos(np.deg2rad(azimuth))
        G[G_z:G_r, 4] = -rds * np.sin(np.deg2rad(azimuth))

        G[G_r:G_t, 0] = -tss * (0.5) * np.sin(2 * np.deg2rad(azimuth))
        G[G_r:G_t, 1] = tss * (0.5) * np.sin(2 * np.deg2rad(azimuth))
        # G[G_r:G_t, 1] =   0
        G[G_r:G_t, 2] = tss * np.cos(2 * np.deg2rad(azimuth))
        G[G_r:G_t, 3] = tds * np.sin(2 * np.deg2rad(azimuth))
        G[G_r:G_t, 4] = -tds * np.cos(2 * np.deg2rad(azimuth))
        return G

    def G_function(self, epi, depth, t, sdr, window):
        if sdr == True:
            epi_m = degrees2kilometers(epi, radius=3389.5) * 1000
            dict = geo.Geodesic(a=3389.5, f=0).ArcDirect(lat1=self.par['la_r'], lon1=self.par['lo_r'], azi1=self.par['baz'],
                                                      a12=epi_m, outmask=1929)
            strike, dip, rake = self.model_samples_sdr()
            d_syn, traces, sources = self.seis.get_seis_manual(la_s=dict['lat2'], lo_s=dict['lon2'], depth=depth,
                                                               strike=strike, dip=dip, rake=rake,
                                                               time=t, sdr=sdr)
            if window == True:
                d_syn_window = self.window.get_windows(traces, epi, depth)
                return d_syn_window, np.array([strike, dip, rake])
            else:
                return d_syn, np.array([strike, dip, rake])
        else:
            G = self.generate_G(epi, depth, t)
            if window == True:
                G_window = self.window.get_G(self.traces, G, epi, depth)
                G = G_window
            moment = self.inv.Solve_damping_smoothing(self.d_obs, G)
            # TODO - choose a range for moment with the help of the Resolution Matrix
            d_syn = np.matmul(G, moment)
            return d_syn, moment

    def write_par(self, txt_file):
        txt_file.write("%s\n\r" % self.par['VELOC'])  # Velocity model used
        # txt_file.write("%.4f\n\r" % self.par['MO'])  #
        txt_file.write("%.4f\n\r" % self.par['alpha'])  #
        txt_file.write("%.4f\n\r" % self.par['beta'])  #
        txt_file.write("%.4f\n\r" % self.par['az'])  #
        txt_file.write("%i\n\r" % self.par['depth_s'])  #
        txt_file.write("%.4f\n\r" % self.par['epi'])  #
        txt_file.write(
            "%s,%s,%s\n\r" % (self.par['components'][0], self.par['components'][1], self.par['components'][2]))  #
        txt_file.write("%.4f\n\r" % self.par['la_r'])  #
        txt_file.write("%.4f\n\r" % self.par['la_s'])  #
        txt_file.write("%.4f\n\r" % self.par['lo_s'])  #
        txt_file.write("%.4f\n\r" % self.par['lo_r'])  #
        txt_file.write("%.4f\n\r" % self.par['m_pp'])  #
        txt_file.write("%.4f\n\r" % self.par['m_rp'])  #
        txt_file.write("%.4f\n\r" % self.par['m_rr'])  #
        txt_file.write("%.4f\n\r" % self.par['m_rt'])  #
        txt_file.write("%.4f\n\r" % self.par['m_tp'])  #
        txt_file.write("%.4f\n\r" % self.par['m_tt'])  #
        txt_file.write("%i\n\r" % self.par['strike'])  #
        txt_file.write("%i\n\r" % self.par['rake'])  #
        txt_file.write("%i\n\r" % self.par['dip'])  #
        txt_file.write("%s\n\r" % self.par['filter'])  #
        txt_file.write("%s\n\r" % self.par['definition'])  #
        txt_file.write("%s\n\r" % self.par['kind'])  #
        txt_file.write("%s\n\r" % self.par['network'])  #
        txt_file.write("%s\n\r" % self.sampler['filename'])  #
        txt_file.write("%s\n\r" % self.sampler['directory'])  #
        txt_file.write("%s\n\r" % self.sampler['filepath'])  #
        txt_file.write("%i\n\r" % self.sampler['sample_number'])  #
        txt_file.write("%.4f\n\r" % self.sampler['var_est'])  #
        txt_file.write("%i\n\r" % self.sampler['epi']['range_max'])  #
        txt_file.write("%i\n\r" % self.sampler['epi']['range_min'])  #
        txt_file.write("%i\n\r" % self.sampler['epi']['step'])  #
        txt_file.write("%i\n\r" % self.sampler['depth']['range_max'])  #
        txt_file.write("%i\n\r" % self.sampler['depth']['range_min'])  #
        txt_file.write("%i\n\r" % self.sampler['depth']['step'])
        txt_file.write("%i,%i,%i,%i,%i,%i\n\r" % (
        self.par['origin_time'].year, self.par['origin_time'].month, self.par['origin_time'].day,
        self.par['origin_time'].hour, self.par['origin_time'].minute, self.par['origin_time'].second))  #

    def write_sample(self, yaml_file, epi, depth, min, sec, Xi, moment, sdr):
        if sdr == True:
            yaml_file.write("%.4f,%.4f,%i,%i,%.4f,%.4f,%.4f,%.4f\n\r" % (epi, depth, min, sec, Xi, moment[0], moment[1],
                                                                         moment[2]))
        else:
            yaml_file.write("%.4f,%.4f,%i,%i,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n\r" % (
                epi, depth, min, sec, Xi, moment[0], moment[1], moment[2], moment[3], moment[4]))

    def processing(self, savepath, window, plot_modus=False, sdr=False, misfit='L2'):
        self.inv = Inversion_problem(self.par)  # Inversion Problem
        self.seis = Seismogram(self.par, self.db)  # For generating seismogram
        if window == True:
            self.window = Source_code(self.par['VELOC_taup'])  # Acces the window code
            self.d_obs = self.window.get_windows(self.traces, self.par['epi'], self.par['depth_s'])
        with open(savepath, 'w') as yaml_file:
            self.write_par(yaml_file)  # Writes all the parameters used for this inversion
            ## Starting parameters and create A START MODEL (MODEL_OLD):
            epi_old, depth_old, time_old = self.model_samples()
            if window == True:
                d_syn_old, moment_old = self.G_function(epi_old, depth_old, time_old, sdr, window)
                if plot_modus == True:
                    f, (ax1, ax2, ax3) = plt.subplots(3, sharex=True, sharey=True)
                    plot_seis = Plots()
                    plot_seis.plot_seismogram_during_MH(ax1, ax2, ax3, d_syn_old, self.traces, savepath)
            else:
                d_syn_old, moment_old = self.G_function(epi_old, depth_old, time_old, sdr, window)
                if plot_modus == True:
                    f, (ax1, ax2, ax3) = plt.subplots(3, sharex=True, sharey=True)
                    plot_seis = Plots()
                    plot_seis.plot_seismogram_during_MH(ax1, ax2, ax3, d_syn_old, self.traces, savepath)

            misfits = Misfit()
            if misfit == 'L2':
                Xi_old = misfits.get_xi(self.d_obs, d_syn_old, self.var,self.dt)
            elif misfit == 'CC':
                Xi_old, time_shift_old = misfits.get_CC(self.d_obs, d_syn_old, self.dt)
            else:
                raise ValueError('misfit is not specified correctly, choose either: L2 or CC in string format')

            if sdr == True:
                self.write_sample(yaml_file, epi_old, depth_old, time_old.minute, time_old.second, Xi_old,
                                  moment_old, sdr)
                # moment_old[0] = strike
                # moment_old[1] = dip
                # moment_old[2] = rake
            else:
                self.write_sample(yaml_file, epi_old, depth_old, time_old.minute, time_old.second, Xi_old,
                                  moment_old, sdr)
                # moment_old[0] = Mxx
                # moment_old[1] = Myy
                # moment_old[2] = Mxy
                # moment_old[3] = Mxz
                # moment_old[4] = Myz

            for i in range(self.sampler['sample_number']):
                epi, depth, time = self.model_samples()
                if window == True:
                    d_syn, moment = self.G_function(epi, depth, time, sdr, window)

                else:
                    d_syn, moment = self.G_function(epi, depth, time, sdr, window)

                if misfit == 'L2':
                    Xi_new = misfits.get_xi(self.d_obs, d_syn, self.var,self.dt)
                elif misfit == 'CC':
                    Xi_new, time_shift_old = misfits.get_CC(self.d_obs, d_syn, self.dt)
                random = np.random.random_sample((1,))
                if Xi_new < Xi_old or (Xi_old / Xi_new) > random:
                    if plot_modus == True:
                        plot_seis.plot_seismogram_during_MH(ax1, ax2, ax3, d_syn, self.traces, savepath)
                    if sdr == True:
                        self.write_sample(yaml_file, epi, depth, time.minute, time.second, Xi_new, moment, sdr)
                    else:
                        self.write_sample(yaml_file, epi, depth, time.minute, time.second, Xi_new, moment, sdr)
                    Xi_old = Xi_new
                    epi_old = epi
                    depth_old = depth
                    time_old = time
                    moment_old = moment
                else:
                    if sdr == True:
                        self.write_sample(yaml_file, epi_old, depth_old, time_old.minute, time_old.second, Xi_old,
                                          moment_old, sdr)
                    else:
                        self.write_sample(yaml_file, epi_old, depth_old, time_old.minute, time_old.second, Xi_old,
                                          moment_old, sdr)
                    continue

            if plot_modus == True:
                final_plot = True
                plot_seis.plot_seismogram_during_MH(ax1, ax2, ax3, self.d_obs, self.traces, savepath, final_plot)
        yaml_file.close()

    def test_samples(self):
        # This function just saves the different samples, important to check how we sample!
        self.inv = Inversion_problem(self.par)
        filepath = self.sampler['directory'] + '/sampler_test_sdr.txt'
        with open(filepath, 'w') as yaml_file:
            ## Starting parameters and create A START MODEL (MODEL_OLD):
            # epi_old, depth_old, time_old = self.model_samples()
            strike_old, dip_old, rake_old, time_old = self.model_samples_sdr()
            yaml_file.write("%.4f,%.4f,%.4f,%.4f\n\r" % (strike_old, dip_old, rake_old, time_old.timestamp))

            for i in range(1000):
                strike, dip, rake, time = self.model_samples_sdr()
                yaml_file.write("%.4f,%.4f,%.4f,%.4f\n\r" % (strike, dip, rake, time.timestamp))
        yaml_file.close()

    # ---------------------------------------------------------------------------------------------------------------------#
    #                                                 RUN parallel                                                         #
    # ---------------------------------------------------------------------------------------------------------------------#
    def do_parallel(self, window=True, sdr=False, plot_modus=False, misfit='L2'):
        # Misfit options:
        #   - 'L2' - L2_Norm
        #   - 'CC' - Cross_correlation

        comm = MPI.COMM_WORLD
        rank = comm.Get_rank()
        size = comm.Get_size()

        print("Rank", rank, "Size", size)
        if sdr == True:
            dir_proc = self.sampler['directory'] + '/proc_sdr'
        else:
            dir_proc = self.sampler['directory'] + '/proc'
        if not os.path.exists(dir_proc):
            os.makedirs(dir_proc)
        filepath_proc = dir_proc + '/file_proc_%i.txt' % rank
        try:
            self.processing(filepath_proc, window=window, plot_modus=plot_modus, sdr=sdr, misfit=misfit)
        except TypeError:
            print ("TypeError in rank: %i" % rank)
            self.processing(filepath_proc, window=window, plot_modus=plot_modus, sdr=sdr, misfit=misfit)

        comm.bcast()  # All the processor wait until they are all at this point
        if rank == 0:
            print ("The .txt files are saved in: %s" % dir_proc)
