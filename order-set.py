#!/usr/bin/env python
 
"""
Requirements: Python 2.6 or simplejson from http://pypi.python.org/pypi/simplejson
"""
 
API_VERSION="1.2.2"
API_URL="https://api.smugmug.com/services/api/json/%s/" % API_VERSION
 
import sys
import re
import urllib
import urllib2
import urlparse
import hashlib
import os
import logging
import ConfigParser
import argparse
 
try:
    import json
except:
    import simplejson as json
 
def safe_geturl(request):
    global su_cookie
 
    # Try up to five times
    for x in range(5):
        try:
            response_obj = urllib2.urlopen(request)
            response = response_obj.read()
            result = json.loads(response)
 
            # Test for presence of _su cookie and consume it
            meta_info = response_obj.info()
            if meta_info.has_key("set-cookie"):
                match = re.search("(_su=\S+);", meta_info["set-cookie"])
                if match and match.group(1) != "_su=deleted":
                    su_cookie = match.group(1)
 
            # Code 15 = list empty (which is okay)
            if result["stat"] != "ok" and result["code"] != 15:
                raise Exception("Bad result code")
 
            return result
        except:
            if x < 4:
                logging.warn("Failed; retrying.")
            else:
                logging.warn("Failed; giving up.")
                logging.debug("Request: %s" % request.get_full_url())
 
                try:
                    logging.debug("Response was: %s" % response)
                except:
                    pass
 
                return result
 
def smugmug_request(method, params):
    global su_cookie
 
    paramstrings = [urllib.quote(key) + "=" + urllib.quote(str(params[key])) for key in params]
    paramstrings += ["method=" + method]
 
    url = urlparse.urljoin(API_URL, "?" + "&".join(paramstrings))
    request = urllib2.Request(url)
 
    if su_cookie:
        request.add_header("Cookie", su_cookie)
 
    return safe_geturl(request)
 
def parse_config():
    config = ConfigParser.ConfigParser()
 
    config.read(os.path.join(os.path.dirname(sys.argv[0]), "smugmug.cfg"))
     
    return config
 
if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
 
    # Parse the command line
    argparser = argparse.ArgumentParser(description="Bulk upload photos to SmugMug.")
    argparser.add_argument("-c", help="Name of category to scan.")
    argparser.add_argument("-s", help="Name of subcategory to scan.")
    argparser.add_argument("-a", help="Album name to operate on.")
 
    args = argparser.parse_args()

    su_cookie = None
 
    config = parse_config()
 
    result = smugmug_request("smugmug.login.withPassword", {"APIKey": config.get("SmugMug", "api key"), "EmailAddress": config.get("SmugMug", "email"), "Password": config.get("SmugMug", "password")})
    session = result["Login"]["Session"]["id"]

    # Loop through all albums
    albums = smugmug_request("smugmug.albums.get", {"SessionID" : session})
    for album in albums["Albums"]:
        # Check if a category applies
        if args.c:
            if album["Category"]["Name"] != args.c: continue
            if args.s:
                try:
                    if album["SubCategory"]["Name"] != args.s: continue
                except KeyError:
                    continue

        if args.a and album["Title"] != args.a: continue
 
        logging.info("""Setting sort order in album, "%s" """ % album["Title"])
        result = smugmug_request("smugmug.albums.changeSettings", {"SessionID": session, "AlbumID": album["id"], "SoftDirection": "false", "SortMethod": "DateTimeOriginal"})
 
    logging.info("Complete")
 
    sys.exit(0)
