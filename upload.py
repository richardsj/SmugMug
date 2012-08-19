#!/usr/bin/env python

"""
Requirements: Python 2.6 or simplejson from http://pypi.python.org/pypi/simplejson
"""

API_VERSION="1.2.2"
API_URL="https://api.smugmug.com/hack/json/1.2.0/"
UPLOAD_URL="http://upload.smugmug.com/photos/xmlrawadd.mg"

import sys
import re
import urllib
import urllib2
import urlparse
import hashlib
import traceback
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

    # Try up to three times
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
            if result["stat"] != "ok":
                raise Exception("Bad result code")
            return result
        except:
            if x < 4:
                print "  ... failed, retrying"
            else:
                print "  ... failed, giving up"
                print "  Request was:"
                print "  " + request.get_full_url()

                try:
                    print "  Response was:"
                    print response
                except:
                    pass

                traceback.print_exc()
                return result

def smugmug_request(method, params):
    global su_cookie

    paramstrings = [urllib.quote(key) + "=" + urllib.quote(params[key]) for key in params]
    paramstrings += ["method=" + method]

    url = urlparse.urljoin(API_URL, "?" + "&".join(paramstrings))
    request = urllib2.Request(url)

    if su_cookie:
        request.add_header("Cookie", su_cookie)

    return safe_geturl(request)

def parse_config():

    config = ConfigParser.ConfigParser()

    config.read(os.path.join(os.path.dirname(sys.argv[0]), "smugup.cfg"))
    
    return config

if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Parse the command line
    argparser = argparse.ArgumentParser(description="Bulk upload photos to SmugMug.")
    argparser.add_argument("album", help="Name of album to upload to.  If the album does not exist, it will be created.")
    argparser.add_argument("photos", nargs="+", help="Space separated list of photos to upload.")

    args = argparser.parse_args()

    if not args.album and not args.photos:
        print argparser.usage
        sys.exit(1)

    album_name = args.album
    su_cookie = None

    config = parse_config()

    result = smugmug_request("smugmug.login.withPassword", {"APIKey": config.get("SmugMug", "api key"), "EmailAddress": config.get("SmugMug", "email"), "Password": config.get("SmugMug", "password")})
    session = result["Login"]["Session"]["id"]

    result = smugmug_request("smugmug.albums.get", {"SessionID" : session})
    album_id = None
    for album in result["Albums"]:
        if album["Title"] == album_name:
            album_id = album["id"]
            break

    if album_id is None:
        logging.info("""Album, "%s" was not found.  Creating.""" % album_name)
        # Create the album
        new_album = smugmug_request("smugmug.albums.create", {"SessionID": session, "FamilyEdit": str(config.getboolean("Albums", "family edit")), "FriendEdit": str(config.getboolean("Albums", "friends edit")), "Public": str(config.getboolean("Albums", "public")), "Title": album_name})
        album_id = new_album["Album"]["id"]

    for filename in args.photos:
        data = open(filename, "rb").read()
        print "Uploading " + filename

        upload_request = urllib2.Request(UPLOAD_URL, data, { "Content-Length": len(data), "Content-MD5": hashlib.md5(data).hexdigest(), "Content-Type": "none", "X-Smug-SessionID": session, "X-Smug-Version": API_VERSION, "X-Smug-ResponseType": "JSON", "X-Smug-AlbumID": album_id, "X-Smug-FileName": os.path.basename(filename) })

        result = safe_geturl(upload_request)
        if result["stat"] == "ok":
            print "  ... successful"

    print "Done"

    sys.exit(0)
