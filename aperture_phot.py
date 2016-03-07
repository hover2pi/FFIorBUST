import numpy as np
import matplotlib.pyplot as plt
import os, time
import astropy.io.fits as pf
from glob import glob
from scipy.spatial import cKDTree
from photutils import daofind, aperture_photometry, detect_threshold, CircularAperture
from astropy.wcs import WCS
from astropy.wcs.utils import pixel_to_skycoord
from astropy.visualization import scale_image
from astropy.stats import sigma_clipped_stats
from astropy.visualization import SqrtStretch
from astropy.visualization.mpl_normalize import ImageNormalize
from astropy.table import vstack, Table, Column

'''
This is a module to extract light curves from all objects in 53 Kepler Full Frame Image exposures.

Authors: Joe Filippazzo, Brigitta Sipocz, Jim Davenport, Jennifer Cash (2016)

Example:

import aperture_phot as ap
ex = ap.exposure(filepath)        # Load the fits file into an exposure class
ex.extension(4)                   # Run DAOfind on the extension of the given index and add to the source_tables list
ex.source_tables                  # Print the list of source_tables 

''' 

def get_KIC():
  # Load the whole KIC
  print 'Loading 13 million KIC targets. This takes about 2 minutes...'
  KIC = np.genfromtxt('./data/kic.txt', delimiter='|', max_rows=1E6, names=True, deletechars='kic_')
  # KIC = np.genfromtxt('./data/kic.txt', delimiter='|', names=True, deletechars='kic_')
  KIC = Table(KIC, names=KIC.dtype.names)
  KICcoords = np.array([KIC['ra'].data,KIC['de'].data]).T
  print 'KIC loaded!\n'
  
  return KICcoords

def light_curves(KIC, match_radius=0.005, search_radius=0.001, output_data=False):
  '''
  Plot and save all possible light curves from the Kepler Full Frame Images
  
  Parameters
  ----------
  search_radius: float
    The search radius in degrees to use when cross matching Kepler Input Catalog and Full Frame Image exposures
  KIC: sequence (optional)
    An array of (ra,dec) tuples for all targets in the Kepler Input Catalog
  output_data: bool
    Return the data
    
  Returns
  -------
  sources: dict
    A dictionary of the ra, dec and light curve for each detected source
  
  '''
  exposures, sources = {}, {}
    
  # Analyze all exposures
  for filepath in glob('./data/*.fits'):
    
    # Create exposure class
    ex = exposure(filepath)
    print 'Starting exposure {}'.format(ex.date_str)
    
    # Get photometry for all 85 extensions
    # for idx in range(1,86): 
    for idx in [3]: 
      print 'Analyzing extension {}'.format(idx)
      try: ex.extension(idx)
      except: pass
    
    # Add data to a master dictionary
    exposures[ex.date_str] = ex.source_table
    print 'Finished exposure {}\n'.format(ex.date_str)
  
  # Do some stuff to match objects across exposures
  for source in KIC:
    RA, DEC = source
    name = '{:012.8f}'.format(RA)+('-' if DEC<0 else '+')+'{:012.8f}'.format(abs(DEC))
    light_curve = []
    
    # Iterate through exposures to collect time-series detections
    for name,exp in exposures.items():   
      
      # Only consider the sources in a small circle around the KIC source coordinates
      ra, dec, phot = np.array([exp['ra'],exp['dec'],exp['aperture_sum']])
      ra = ra[np.where(np.logical_and(ra<RA+search_radius,ra>RA-search_radius))]
      dec = dec[np.where(np.logical_and(dec<DEC+search_radius,dec>DEC-search_radius))]
      
      # Create an array of detection coordinates
      detections = np.array([ra,dec]).T
  
      if any(ra) and any(dec):
        # Create k-d tree of sources in the neighborhood
        tree = cKDTree(detections)

        # Find distance and index of nearest neighbor then grab its coordinates and magnitude from the exposure
        distance, index = tree.query(source)
        coords, magnitude = tree.data[index], phot[index]
  
        # If the distance is within the specified search radius, add it to the light curve
        # if distance<search_radius: light_curve.append((exp.datetime,magnitude))
        light_curve.append((exp.datetime,magnitude))

      else: pass
    
    # If there are any detections across the exposures, plot the light curve
    if any(light_curve):
      # Add the light curve to the sources dictionary
      sources[name] = {i:KIC[2][i] for i in KIC.dtype.names}
      sources[name]['light_curve'] = light_curve
   
      # Plot the light curve of all exposures and save it
      plt.plot(*light_curve.T)
      plt.title(name)
      plt.savefig('./plots/{}.png'.format(name))
      plt.close()
      
      print 'Light curve for {} generated!'.format(name)
  
  if output_data: return sources

class exposure:
  def __init__(self, filepath, verbose=False):
    '''
    Creates an exposure class which has many extensions.
    
    Parameters
    ----------
    filepath: str
      Path to the fits file of a single exposure
    verbose: bool
      Print some info to visually inspect
    
    '''
    self.source_table = Table(names=['aperture_sum','xcenter','ycenter','ra','dec'])
    
    # Open the file and print the info
    self.hdulist = pf.open(filepath)
    if verbose:
      self.hdulist.info()
    
    # Get the datetime of the exposure from the filename
    self.date_str = os.path.basename(filepath).replace('_ffi-cal.fits','').replace('kplr','')
    self.datetime = time.strptime(self.date_str, '%Y%j%H%M%S')
        
  def extension(self, extension_idx, threshold='', FWHM=3.0, sigma=3.0, snr=50., plot=False):
    '''
    A method to run aperatue photometry routines on an individual extension and save the results to the exposure class
    
    Parameters
    ----------
    extension_idx: int
      Index of the extension
    threshold: float (optional)
      The absolute image value above which to select sources
    FWHM: float
      The full width at half maximum
    sigma: float
      Number of standard deviations to use for background estimation
    snr: float
      The signal-to-noise ratio to use in the threshold detection
    plot: bool
      Plot the field with identified sources circled      

    Returns
    -------
    source_list: table
      A source list for the image

    '''

    # Define the data array
    data = self.hdulist[extension_idx].data.astype(np.float)
    
    # Extract the header and create a WCS object
    hdr = self.hdulist[extension_idx].header
    wcs = WCS(hdr)

    # Estimate the background and background noise
    mean, median, std = sigma_clipped_stats(data, sigma=sigma, iters=5)

    # Calculate the detection threshold and FWHM if not provided
    if not threshold: threshold = np.mean(detect_threshold(data, snr=snr))
    
    # Print the parameters being used
    for p,v in zip(['mean','median','std','threshold','FWHM'],[mean,median,std,threshold,FWHM]): print '{!s:10}: {:.3f}'.format(p,v)

    # Subtract background and generate sources list of all detections
    sources = daofind(data-median, threshold, FWHM)
    
    # Map RA and Dec to pixels
    positions = (sources['xcentroid'], sources['ycentroid'])
    skycoords = pixel_to_skycoord(*positions, wcs=wcs)
    
    # Calculate magnitudes at given source positions
    apertures = CircularAperture(positions, r=2.)
    photometry_table = aperture_photometry(data, apertures)
    
    # 'skycoords' IRCS object is problematic for stacking tables so for now we'll just add the ra and dec
    # photometry_table['sky_center'] = skycoords
    photometry_table['ra'], photometry_table['dec'] = skycoords.ra, skycoords.dec
    
    # Update data in the exposure object
    self.source_table = vstack([self.source_table,photometry_table], join_type='inner')  
    
    # Plot the sources
    if plot:
      norm = ImageNormalize(stretch=SqrtStretch())
      plt.imshow(data, cmap='Greys', origin='lower', norm=norm)
      apertures.plot(color='blue', lw=1.5, alpha=0.5)
    
    print '{!s:10}: {}'.format('sources',len(sources))
  