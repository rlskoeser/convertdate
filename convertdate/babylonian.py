# -*- coding: utf-8 -*-
from __future__ import division
from math import ceil, floor, trunc
from itertools import chain
from .data import babylonian_data as data
from . import dublin, julian, gregorian
from .utils import amod
from pkg_resources import resource_stream
from csv import DictReader
import ephem
import codecs

MOON = ephem.Moon()
SUN = ephem.Sun()

# At JDC 1000.0, it was 1000.125 in Babylon
# AST = Babylon's time zone
AST_ADJUSTMENT = 0.125

# todo:
# from_jd (seleucid, arascid, regnal year)

PARKER_DUBBERSTEIN = dict()

# Example row:
# -604: {
#   'ruler': 'NABOPOLASSAR',
#   'year': -604,
#   'regnalyear': '21',
#   'months': {
#       1: 1500913.5,
#       2: 1500942.5,
#       3: 1500972.5,
#       4: 1501001.5,
#       5: 1501031.5,
#       6: 1501061.5,
#       7: 1501090.5,
#       8: 1501120.5,
#       9: 1501149.5,
#       10: 1500814.5,
#       11: 1500843.5,
#       12: 1500873.5,
#   },
# }


def load_parker_dubberstein():
    '''Read the P-D "Table for the Restatement of Babylonian
    Dates in Terms of the Julian Calendar" into a dict.
    At the risk of being somewhat tortured in the conversions,
    the data is being generally preserved in the format they presented
    '''
    global PARKER_DUBBERSTEIN

    # Each row of P-D represents a babylonian year, which usually starts around
    # the Vernal Equinox
    if len(PARKER_DUBBERSTEIN) == 0:
        # header row:
        # ruler,regnalyear,astroyear,1,2,3,4,5,6,7,8,9,10,11,12,13,14
        # 12,13,14 will generally be in the next JYear
        with resource_stream('convertdate', 'data/parker-dubberstein.csv') as f:
            stringreader = codecs.getreader('ascii')
            reader = DictReader(stringreader(f))
            for row in reader:
                new = dict()
                year = int(row['jyear'])
                new['ruler'] = row['ruler']
                new['regnalyear'] = row['regnalyear']
                new['months'] = {}

                for monthid in [str(x) for x in range(1, 14)]:
                    if row.get(monthid):
                        jmonth, jday = row.get(monthid).split('/')
                        jmonth, jday = int(jmonth), int(jday)

                        # Have we swung over into the next year?
                        if jmonth < int(monthid):
                            jyear = year + 1
                        else:
                            jyear = year

                        new['months'][int(monthid)] = julian.to_jd(jyear, jmonth, jday)

                PARKER_DUBBERSTEIN[year] = new

    return PARKER_DUBBERSTEIN


def observer(date=None):
    BABYLON = ephem.Observer()
    # OMFG I can't believe ephem uses d:mm:ss, wtf
    BABYLON.lat = '32:32:11'
    BABYLON.lon = '44:25:15'
    BABYLON.elevation = 32.536389

    if date:
        BABYLON.date = date

    return BABYLON


def metonic_number(julianyear):
    '''The start year of the current metonic cycle and the current year (1-19) in the cycle'''
    # Input should be the JY of the first day of the Babylonian year in question
    # Add 1 because cycle runs 1-19 in Parker & Dubberstein
    return 1 + ((julianyear - 14) % 19)


def metonic_start(julianyear):
    '''The julian year that the metonic cycle of input began'''
    return julianyear - metonic_number(julianyear) + 1


def intercalate(julianyear, plain=None):
    '''For a Julian year, use the intercalation pattern to return a dict of the months'''
    number = metonic_number(julianyear)
    start = metonic_start(julianyear)
    return intercalation(number, start, plain)


def intercalation(mnumber, mstart=0, plain=None):
    '''A list of months for a given year (number) in a particular metonic cycle (start).
    Defaults to the standard intercalation'''

    if mstart < -633:
        raise IndexError("Input year out of range. The Babylonian calendar doesn't go that far back")

    pattern = data.intercalations.get(mstart, data.standard_intercalation)
    patternkey = pattern.get(mnumber)

    return intercalation_pattern(patternkey, plain)


def intercalation_pattern(key, plain=None):
    if plain:
        base_list = data.ASCII_MONTHS
    else:
        base_list = data.MONTHS

    month, index = data.INTERCALARIES.get(key, (None, None))

    if month:
        months = base_list[:index] + [month] + base_list[index:]
    else:
        months = base_list

    return dict(list(zip(list(range(1, len(months) + 1)), months)))


def standard_metonic_month_list():
    return list(chain(*[list(intercalation(y).values()) for y in range(1, 20)]))


def _number_months(metonic_year):
    '''Number of months in the metonic year in the standard system'''
    if metonic_year in data.standard_intercalation:
        return 13
    else:
        return 12


def _valid_regnal(julianyear):
    if julianyear < -625 or julianyear > -145:
        return False
    return True


def regnalyear(julianyear):
    '''Determine regnal year based on a Julian year, -200 == 200 BC'''

    if _valid_regnal(julianyear):
        pass
    else:
        return (False, False)

    if julianyear in list(data.rulers.keys()):
        rulername = data.rulers[julianyear]
        ryear = 1
    else:
        key = max([r for r in data.rulers if r <= julianyear])
        ryear = julianyear - key + 1
        rulername = data.rulers[key]

    # Doesn't follow the rules, this guy.
    if rulername == 'Nabopolassar':
        ryear = ryear - 1

    if rulername == 'Alexander the Great':
        ryear = ryear + 6

    if rulername == 'Philip III Arrhidaeus':
        ryear = ryear + 1

    if rulername == 'Alexander IV Aegus':
        ryear = ryear + 1

    return (ryear, rulername)


def _regnal_epoch(ruler):
    '''Return the year that a ruler's epoch began'''

    invert = dict((v, k) for k, v in list(data.rulers.items()))
    epoch = invert[ruler] - 1

    # Doesn't follow the rules, these guys
    if ruler == 'Nabopolassar':
        return epoch + 1

    if ruler == 'Alexander the Great':
        return epoch - 6

    if ruler == 'Philip III Arrhidaeus':
        return epoch - 1

    if ruler == 'Alexander IV Aegus':
        return epoch - 1

    return epoch


def _set_epoch(era=None):
    era = era or ''
    era = era.lower()

    if era == 'arsacid':
        return data.ARSACID_EPOCH
    elif era == 'nabonassar':
        return data.NABONASSAR_EPOCH
    elif era == 'nabopolassar':
        return data.NABOPOLASSAR_EPOCH
    else:
        return data.SELEUCID_EPOCH


def from_jd(cjdn, era=None, plain=None):
    '''Calculate Babylonian date from Julian Day Count'''

    era = era or 'AG'

    if era.lower() == 'seleucid':
        era = 'AG'

    if cjdn > data.JDC_START_OF_ANALEPTIC:
        return _from_jd_analeptic(cjdn, era, plain)

    if cjdn < data.JDC_START_OF_REGNAL:
        raise IndexError('Date is too early for the Babylonian calendar')

    jyear = julian.from_jd(cjdn)[0]

    parkerdub = load_parker_dubberstein()

    # There's no row for the very last year in P-D's table
    if jyear == 46:
        jyear = jyear - 1

    pd = parkerdub[jyear]

    # Hop back to the previous row
    if cjdn < min(pd['months'].values()):
        jyear = jyear - 1
        pd = parkerdub[jyear]

    # The JDC of the months' first days => BMonth number (1..13)
    inverted = dict((v, k) for k, v in list(pd['months'].items()))

    # Start of the current month is highest JD not over input JDC
    start_of_month = max(mj for mj in list(inverted.keys()) if mj <= cjdn)

    # index of current month
    bmonth = inverted[start_of_month]

    # Get month name, taking into account intercalary months
    month_name = intercalate(jyear, plain).get(bmonth)

    # day of the month
    bday = cjdn - start_of_month + 1

    if era == 'regnal':
        by, era = regnalyear(jyear)
    else:
        by = jyear - _set_epoch(era)

    return (by, month_name, int(bday), era)


def to_jd(year, month, day, era=None, ruler=None):
    era = era or ''

    if era.lower() not in ['arsacid', 'seleucid', 'ag', 'regnal'] or era.lower == 'ag':
        era = 'AG'

    if era == 'regnal':
        if not ruler:
            raise ValueError("Missing argument for 'ruler'")
        epoch = _regnal_epoch(ruler)

    else:
        epoch = _set_epoch(era)

    if era.lower() in ['ag', 'seleucid'] and year > 356:
        return _to_jd_analeptic(year, month, day, era=era)

    jyear = year + epoch

    # Find the row in parker-dubberstein's table that matches
    # our julian year and month.
    parkerdub = load_parker_dubberstein()

    try:
        pdentry = parkerdub[jyear]['months'][month]
    except KeyError:
        return _to_jd_analeptic(year, month, day, era=era)

    return pdentry + day - 1


def _to_jd_analeptic(year, month, day, era):
    if era == 'regnal':
        raise ValueError('Regnal era not valid for this date')

    if era.lower() not in ['arsacid', 'nabonassar', 'seleucid']:
        era = 'seleucid'

    epoch = _set_epoch(era)
    jyear = year + epoch

    # Py 2/3 compat. This is a bad way to do things?
    try:
        stringmonth = type(month) in [str, unicode]
    except NameError:
        stringmonth = type(month) in [str]

    if stringmonth:
        months = intercalate(jyear)
        inverted = dict((v, k) for k, v in list(months.items()))

        try:
            month = inverted[month]
        except KeyError:
            months = intercalate(jyear, plain=1)
            inverted = dict((v, k) for k, v in list(months.items()))

            month = inverted[month]
        except Exception as e:
            raise e

    start_year = dublin.from_julian(jyear, 5, 1)
    moon = _nvnm_after_pve(start_year)

    for x in range(1, month):
        moon = ephem.next_new_moon(moon)

    pvnm = previous_visible_nm(moon + 2)

    outdc = floor(pvnm + day) - 0.5

    return dublin.to_jd(outdc)


def to_julian(year, month, day, era=None, ruler=None):
    return julian.from_jd(to_jd(year, month, day, era, ruler))


def to_gregorian(year, month, day, era=None, ruler=None):
    return gregorian.from_jd(to_jd(year, month, day, era=era, ruler=ruler))


def from_julian(y, m, d, era=None, plain=None):
    return from_jd(julian.to_jd(y, m, d), era, plain=plain)


def from_gregorian(y, m, d, era=None, plain=None):
    return from_jd(gregorian.to_jd(y, m, d), era, plain=plain)


def _visible_nm(dc, func):
    starting_nm = func(dc)
    babylon = observer()
    babylon.date = babylon.next_setting(SUN, start=starting_nm)
    MOON.compute(babylon)

    if MOON.alt < 0:
        # Moon is down when the sun goes down.
        # Does it rise before morning?
        if babylon.next_rising(MOON) < babylon.next_rising(SUN):
            pass
        else:
            babylon.date = babylon.next_setting(SUN)

    # In Bab reckoning, the day started at sundown
    # For record-keeping, we use midnight (day count = x.5)
    return ephem.Date(trunc(babylon.date) - 0.5)


def previous_visible_nm(dc):
    '''The previous time the new moon was visible in Babylon'''
    func = ephem.previous_new_moon
    return _visible_nm(dc, func)


def next_visible_nm(dc):
    '''The next time the new moon will be visible in Babylon'''
    func = ephem.next_new_moon
    return _visible_nm(dc, func)


def _nvnm_after_pve(dc):
    prev_equinox = ephem.previous_vernal_equinox(dc)
    return next_visible_nm(prev_equinox)


def moons_between_dates(start, end):
    '''Number of moons observed in Babylon between 2 ephem.Dates'''
    count = -1

    while start < end:
        start = ephem.next_new_moon(start)
        count += 1

    return count


def _from_jd_analeptic(jdc, era=None, plain=None):
    '''Given a Julian Day Count, calculate the Babylonian date analeptically, with choice of eras'''
    # Calcuate the dublin day count, used in ephem
    # We're going to return the date for noon
    jdc = int(jdc) + 0.5
    era = era or 'AG'

    dublincount = ephem.Date(dublin.from_jd(jdc))

    gyear, gmonth, gday = gregorian.from_jd(jdc)

    # Are we before or after the first NM after the VE of this Gregorian year?
    # three possible parts of the year we can fall in:
    # A: between Jan 1 and the Vernal Equinox
    # B: between the V.E. and its next new moon
    # C: between that new moon and Dec 31
    new_moon = _nvnm_after_pve(dublincount)

    # Group A
    # Offset the year
    if new_moon.datetime().year < gyear:
        gyear = gyear - 1

    # Group B
    # reset, so we count from the previous year's VE's NNM
    # Also, offset the year
    if new_moon > dublincount:
        gyear = gyear - 1
        new_moon = _nvnm_after_pve(dublincount - 31)

    # Group A, B or C
    # Loop through the new moons since the start of the year
    # count forward until we're in the current month
    mooncount = 0
    while new_moon <= dublincount:
        mooncount = 1 + mooncount
        new_moon = ephem.next_new_moon(new_moon)

    monthstart = previous_visible_nm(dublincount)

    months = intercalate(gyear, plain)
    # Sometimes this happens.
    # Jump to the previous month, accounting that we might be at month 1
    if dublincount < monthstart:
        mooncount = amod(mooncount - 1, len(months))
        monthstart = previous_visible_nm(dublincount - 1)

    try:
        month_name = months[mooncount]
    except KeyError:
        if mooncount > len(months):
            mooncount = mooncount - len(months)
            gyear += 1
            months = intercalate(gyear, plain)
        month_name = months[mooncount]

    day_count = int(ceil(dublincount - monthstart)) + 1

    epoch = _set_epoch(era)

    return gyear - epoch, month_name, day_count, era


def day_duration(jdc):
    '''The start and end times of the Babylonian day that overlaps with noon on the day of the input.
    For best results, pass a Julian Day Count with a decimal of .5 (e.g. 1737937.5)
    '''
    ddc = dublin.from_jd(jdc)
    babylon = observer(ddc)

    start = babylon.previous_setting(SUN)
    end = babylon.next_setting(SUN)

    return dublin.to_datetime(start), dublin.to_datetime(end)
