#!/usr/bin/env python

"""
Requirements: Python 2.6 or simplejson from http://pypi.python.org/pypi/simplejson
"""

API_VERSION="1.2.2"
API_URL="https://api.smugmug.com/services/api/json/%s/" % API_VERSION
UPLOAD_URL="http://upload.smugmug.com/"

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
    argparser.add_argument("album", help="Name of album to upload to.  If the album does not exist, it will be created.")
    argparser.add_argument("photos", nargs="+", help="Space separated list of photos to upload.")

    args = argparser.parse_args()

    if not args.album and not args.photos:
        print argparser.usage
        sys.exit(1)

    # Remove duplicates from the command line
    args.photos = set(args.photos)

    album_name = args.album
    su_cookie = None

    config = parse_config()

    result = smugmug_request("smugmug.login.withPassword", {"APIKey": config.get("SmugMug", "api key"), "EmailAddress": config.get("SmugMug", "email"), "Password": config.get("SmugMug", "password")})
    session = result["Login"]["Session"]["id"]

    result = smugmug_request("smugmug.albums.get", {"SessionID" : session})
    album_id = None
    hashes = []
    for album in result["Albums"]:
        if album["Title"] == album_name:
            album_id = album["id"]

            album_data = smugmug_request("smugmug.images.get", {"SessionID": session, "AlbumID": album_id, "AlbumKey": album["Key"], "Heavy": "true"})

            # Produce a list of MD5 hashes for existing images online
            if album_data["stat"] == "ok":
                logging.info("Compiling existing image hashes")
                hashes = [item["MD5Sum"] for item in album_data["Images"]]

            break

    if album_id is None:
        logging.info("""Album, "%s" was not found.  Creating.""" % album_name)
        # Create the album
        new_album = smugmug_request("smugmug.albums.create", {"SessionID": session, "FamilyEdit": str(config.getboolean("Albums", "family edit")), "FriendEdit": str(config.getboolean("Albums", "friends edit")), "Public": str(config.getboolean("Albums", "public")), "Title": album_name})
        album_id = new_album["Album"]["id"]

    for filename in args.photos:
        logging.info("Uploading %s" % filename)

        # Open the file and produce an MD5 hash
        data = open(filename, "rb").read()
        upload_md5 = hashlib.md5(data).hexdigest()

        # Check to see if the hash already exists online.
        if upload_md5 in hashes:
            logging.warn("Image already appears to exist.  Skipping")
            continue

        # Upload the image
        upload_request = urllib2.Request(UPLOAD_URL, data, { "Content-Length": len(data), "Content-MD5": upload_md5, "Content-Type": "none", "X-Smug-SessionID": session, "X-Smug-Version": API_VERSION, "X-Smug-ResponseType": "JSON", "X-Smug-AlbumID": album_id, "X-Smug-FileName": os.path.basename(filename) })

        result = safe_geturl(upload_request)
        if result["stat"] == "ok":
            logging.info("Successful")
        else:
            logging.error("There was a problem uploading this object to SmugMug.")

    logging.info("Complete")

    sys.exit(0)
