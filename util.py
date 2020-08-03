import bisect
import collections
import datetime
import logging
import math
import re
import time
import unicodedata
import urllib.parse

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import sqlalchemy
from sqlalchemy import exc, sql
from unidecode import unidecode


class NoDoiException(Exception):
    pass

# from http://stackoverflow.com/a/3233356/596939
def update_recursive_sum(d, u):
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            r = update_recursive_sum(d.get(k, {}), v)
            d[k] = r
        else:
            if k in d:
                d[k] += u[k]
            else:
                d[k] = u[k]
    return d

# returns dict with values that are proportion of all values
def as_proportion(my_dict):
    if not my_dict:
        return {}
    total = sum(my_dict.values())
    resp = {}
    for k, v in my_dict.items():
        resp[k] = round(float(v)/total, 2)
    return resp

def calculate_percentile(refset, value):
    if value is None:  # distinguish between that and zero
        return None

    matching_index = bisect.bisect_left(refset, value)
    percentile = float(matching_index) / len(refset)
    # print u"percentile for {} is {}".format(value, percentile)

    return percentile

def clean_html(raw_html):
  cleanr = re.compile('<.*?>')
  cleantext = re.sub(cleanr, '', raw_html)
  return cleantext

# good for deduping strings.  warning: output removes spaces so isn't readable.
def normalize(text):
    response = text.lower()
    response = unidecode(str(response))
    response = clean_html(response)  # has to be before remove_punctuation
    response = remove_punctuation(response)
    response = re.sub(r"\b(a|an|the)\b", "", response)
    response = re.sub(r"\b(and)\b", "", response)
    response = re.sub(r"\s+", "", response)
    return response

def normalize_simple(text):
    response = text.lower()
    response = remove_punctuation(response)
    response = re.sub(r"\b(a|an|the)\b", "", response)
    response = re.sub(r"\s+", "", response)
    return response

def remove_punctuation(input_string):
    # from http://stackoverflow.com/questions/265960/best-way-to-strip-punctuation-from-a-string-in-python
    no_punc = input_string
    if input_string:
        no_punc = "".join(e for e in input_string if (e.isalnum() or e.isspace()))
    return no_punc

# from http://stackoverflow.com/a/11066579/596939
def replace_punctuation(text, sub):
    punctutation_cats = set(['Pc', 'Pd', 'Ps', 'Pe', 'Pi', 'Pf', 'Po'])
    chars = []
    for my_char in text:
        if unicodedata.category(my_char) in punctutation_cats:
            chars.append(sub)
        else:
            chars.append(my_char)
    return "".join(chars)


# from http://stackoverflow.com/a/22238613/596939
def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError ("Type not serializable")

def conversational_number(number):
    words = {
        "1.0": "one",
        "2.0": "two",
        "3.0": "three",
        "4.0": "four",
        "5.0": "five",
        "6.0": "six",
        "7.0": "seven",
        "8.0": "eight",
        "9.0": "nine",
    }

    if number < 1:
        return round(number, 2)

    elif number < 1000:
        return int(math.floor(number))

    elif number < 1000000:
        divided = number / 1000.0
        unit = "thousand"

    else:
        divided = number / 1000000.0
        unit = "million"

    short_number = '{}'.format(round(divided, 2))[:-1]
    if short_number in words:
        short_number = words[short_number]

    return short_number + " " + unit



def safe_commit(db):
    try:
        db.session.commit()
        return True
    except (KeyboardInterrupt, SystemExit):
        # let these ones through, don't save anything to db
        raise
    except sqlalchemy.exc.DataError:
        db.session.rollback()
        print("sqlalchemy.exc.DataError on commit.  rolling back.")
    except Exception:
        db.session.rollback()
        print("generic exception in commit.  rolling back.")
        logging.exception("commit error")
    return False




def is_doi_url(url):
    # test urls at https://regex101.com/r/yX5cK0/2
    p = re.compile(r"https?:\/\/(?:dx.)?doi.org\/(.*)")
    matches = re.findall(p, url.lower())
    if len(matches) > 0:
        return True
    return False

def clean_doi(dirty_doi):
    if not dirty_doi:
        raise NoDoiException("There's no DOI at all.")

    dirty_doi = remove_nonprinting_characters(dirty_doi)
    dirty_doi = dirty_doi.strip()
    dirty_doi = dirty_doi.lower()

    # test cases for this regex are at https://regex101.com/r/zS4hA0/1
    p = re.compile(r'.*?(10.+)')

    matches = re.findall(p, dirty_doi)
    if len(matches) == 0:
        raise NoDoiException("There's no valid DOI.")

    match = matches[0]

    try:
        resp = str(match, "utf-8")  # unicode is valid in dois
    except (TypeError, UnicodeDecodeError):
        resp = match

    # remove any url fragments
    if "#" in resp:
        resp = resp.split("#")[0]

    return resp


def pick_best_url(urls):
    if not urls:
        return None

    #get a backup
    response = urls[0]

    # now go through and pick the best one
    for url in urls:
        # doi if available
        if "doi.org" in url:
            response = url

        # anything else if what we currently have is bogus
        if response == "http://www.ncbi.nlm.nih.gov/pmc/articles/PMC":
            response = url

    return response

def date_as_iso_utc(datetime_object):
    if datetime_object is None:
        return None

    date_string = "{}{}".format(datetime_object, "+00:00")
    return date_string


def dict_from_dir(obj, keys_to_ignore=None, keys_to_show="all"):

    if keys_to_ignore is None:
        keys_to_ignore = []
    elif isinstance(keys_to_ignore, str):
        keys_to_ignore = [keys_to_ignore]

    ret = {}

    if keys_to_show != "all":
        for key in keys_to_show:
            ret[key] = getattr(obj, key)

        return ret


    for k in dir(obj):
        value = getattr(obj, k)

        if k.startswith("_"):
            pass
        elif k in keys_to_ignore:
            pass
        # hide sqlalchemy stuff
        elif k in ["query", "query_class", "metadata"]:
            pass
        elif callable(value):
            pass
        else:
            try:
                # convert datetime objects...generally this will fail becase
                # most things aren't datetime object.
                ret[k] = time.mktime(value.timetuple())
            except AttributeError:
                ret[k] = value
    return ret


def median(my_list):
    """
    Find the median of a list of ints

    from https://stackoverflow.com/questions/24101524/finding-median-of-list-in-python/24101655#comment37177662_24101655
    """
    my_list = sorted(my_list)
    if len(my_list) < 1:
            return None
    if len(my_list) %2 == 1:
            return my_list[((len(my_list)+1)/2)-1]
    if len(my_list) %2 == 0:
            return float(sum(my_list[(len(my_list)/2)-1:(len(my_list)/2)+1]))/2.0


def underscore_to_camelcase(value):
    words = value.split("_")
    capitalized_words = []
    for word in words:
        capitalized_words.append(word.capitalize())

    return "".join(capitalized_words)

def chunks(l, n):
    """
    Yield successive n-sized chunks from l.

    from http://stackoverflow.com/a/312464
    """
    for i in range(0, len(l), n):
        yield l[i:i+n]

def page_query(q, page_size=1000):
    offset = 0
    while True:
        r = False
        print("util.page_query() retrieved {} things".format(page_query()))
        for elem in q.limit(page_size).offset(offset):
            r = True
            yield elem
        offset += page_size
        if not r:
            break

def elapsed(since, round_places=2):
    return round(time.time() - since, round_places)



def truncate(str, max=100):
    if len(str) > max:
        return str[0:max] + "..."
    else:
        return str


def str_to_bool(x):
    if x.lower() in ["true", "1", "yes"]:
        return True
    elif x.lower() in ["false", "0", "no"]:
        return False
    else:
        raise ValueError("This string can't be cast to a boolean.")

# from http://stackoverflow.com/a/20007730/226013
ordinal = lambda n: "%d%s" % (n,"tsnrhtdd"[(n/10%10!=1)*(n%10<4)*n%10::4])

#from http://farmdev.com/talks/unicode/
def to_unicode_or_bust(obj, encoding='utf-8'):
    if isinstance(obj, str):
        if not isinstance(obj, str):
            obj = str(obj, encoding)
    return obj

def remove_nonprinting_characters(input, encoding='utf-8'):
    input_was_unicode = True
    if isinstance(input, str):
        if not isinstance(input, str):
            input_was_unicode = False

    unicode_input = to_unicode_or_bust(input)

    # see http://www.fileformat.info/info/unicode/category/index.htm
    char_classes_to_remove = ["C", "M", "Z"]

    response = ''.join(c for c in unicode_input if unicodedata.category(c)[0] not in char_classes_to_remove)

    if not input_was_unicode:
        response = response.encode(encoding)

    return response

# getting a "decoding Unicode is not supported" error in this function?
# might need to reinstall libaries as per
# http://stackoverflow.com/questions/17092849/flask-login-typeerror-decoding-unicode-is-not-supported
class HTTPMethodOverrideMiddleware(object):
    allowed_methods = frozenset([
        'GET',
        'HEAD',
        'POST',
        'DELETE',
        'PUT',
        'PATCH',
        'OPTIONS'
    ])
    bodyless_methods = frozenset(['GET', 'HEAD', 'OPTIONS', 'DELETE'])

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        method = environ.get('HTTP_X_HTTP_METHOD_OVERRIDE', '').upper()
        if method in self.allowed_methods:
            method = method.encode('ascii', 'replace')
            environ['REQUEST_METHOD'] = method
        if method in self.bodyless_methods:
            environ['CONTENT_LENGTH'] = '0'
        return self.app(environ, start_response)


# could also make the random request have other filters
# see docs here: https://github.com/CrossRef/rest-api-doc/blob/master/rest_api.md#sample
# usage:
# dois = get_random_dois(50000, from_date="2002-01-01", only_journal_articles=True)
# dois = get_random_dois(100000, only_journal_articles=True)
# fh = open("data/random_dois_articles_100k.txt", "w")
# fh.writelines(u"\n".join(dois))
# fh.close()
def get_random_dois(n, from_date=None, only_journal_articles=True):
    dois = []
    while len(dois) < n:
        # api takes a max of 100
        number_this_round = min(n, 100)
        url = "http://api.crossref.org/works?sample={}".format(number_this_round)
        if only_journal_articles:
            url += "&filter=type:journal-article"
        if from_date:
            url += ",from-pub-date:{}".format(from_date)
        print(url)
        print("calling crossref, asking for {} dois, so far have {} of {} dois".format(
            number_this_round, len(dois), n))
        r = requests.get(url)
        items = r.json()["message"]["items"]
        dois += [item["DOI"].lower() for item in items]
    return dois

def get_tree(page):
    page = page.replace("&nbsp;", " ")  # otherwise starts-with for lxml doesn't work
    try:
        tree = html.fromstring(page)
    except etree.XMLSyntaxError as e:
        print("not parsing, beause XMLSyntaxError in get_tree: {}".format(e))
        tree = None
    return tree

def get_link_target(url, base_url, strip_jsessionid=True):
    if strip_jsessionid:
        url = re.sub(r";jsessionid=\w+", "", url)
    if base_url:
        url = urllib.parse.urljoin(base_url, url)

    return url


def run_sql(db, q):
    q = q.strip()
    if not q:
        return
    print("running {}".format(q))
    start = time.time()
    try:
        con = db.engine.connect()
        trans = con.begin()
        con.execute(q)
        trans.commit()
    except exc.ProgrammingError as e:
        print("error {} in run_sql, continuting".format(e))
    finally:
        con.close()
    print("{} done in {} seconds".format(q, elapsed(start, 1)))

def get_sql_answer(db, q):
    row = db.engine.execute(sql.text(q)).first()
    return row[0]

def get_sql_answers(db, q):
    rows = db.engine.execute(sql.text(q)).fetchall()
    if not rows:
        return []
    return [row[0] for row in rows]

def get_multiple_authors(authors):
    parsed_authors = [author['name'] for author in authors]
    return ', '.join(set(parsed_authors))

def validate_author_url(author_url):
    if author_url and author_url.startswith('twitter://'):
        screen_name = re.findall('screen_name=([A-Za-z0-9_]{1,15}$)', author_url)[0]
        return 'http://www.twitter.com/{}'.format(screen_name)
    else:
        return author_url

def validate_subject_url(author_url, subject_url):
    if subject_url.startswith('twitter://'):
        screen_name = re.findall(r'twitter.com\/([A-Za-z0-9_]{1,15}$)', author_url)[0]
        status_id = re.findall(r'status\?id=(\d+$)', subject_url)[0]
        return 'http://twitter.com/{}/statuses/{}'.format(screen_name, status_id)
    else:
        return subject_url

def requests_retry_session(
    retries=3,
    backoff_factor=0.1,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session