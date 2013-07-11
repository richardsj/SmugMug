#!/usr/bin/env python

"""
Requirements: Python 2.6 or simplejson from http://pypi.python.org/pypi/simplejson
"""

import sys
import re
import urllib
import urllib2
import urlparse
import hashlib
import os
import logging
import ConfigParser
import time

import tkFileDialog
import tkMessageBox
import Tkinter
import ttk

import threading

try:
    import json
except ImportError:
    import simplejson as json

class WidgetLogger(logging.Handler):
    """A class to enable logging to a window."""
    def __init__(self, widget, *args, **kwargs):
        logging.Handler.__init__(self, *args, **kwargs)
        self.widget = widget

    def emit(self, record):
        self.widget.insert(Tkinter.END, time.strftime("%Y-%m-%d %H:%M:%S ") + record.getMessage())
        self.widget.insert(Tkinter.END, "\n")

class Album:
    """Class to handle an album."""
    def __init__(self):
        self.name = ""

    def ask_name(self):
        """Function to ask for an album name from the user."""
        window = Tkinter.Tk()

        simple_title = Tkinter.Label(window)
        simple_title["text"] = "Album name"
        simple_title.pack()

        input_box = Tkinter.Entry(window)
        input_box.pack()

        button = Tkinter.Button(window, text="Next", command=lambda: self.get_text(window, input_box))
        button.pack()

        input_box.focus_set()

        Tkinter.mainloop()

    def get_text(self, window, input_box):
        """Function to get a clean input string from the user."""
        self.name = input_box.get().strip()
        if self.name == "":
            tkMessageBox.showerror("ERROR", "The album name must be provided.")
        else:
            window.destroy()

class SmugmugAPIHandler:
    """Class to handle requests to the SmugMug API"""
    su_cookie = None
    def __init__(self):
        self.api_version = "1.2.2"
        self.api_url = "https://api.smugmug.com/services/api/json/%s/" % self.api_version
        self.upload_url = "http://upload.smugmug.com/"

    def safe_geturl(self, request):
        """Fetch a URL with retries."""

        class SmugmugError(Exception):
            """Simple Exception definition."""
            pass

        # Try up to five times
        for attempt in range(5):
            try:
                response_obj = urllib2.urlopen(request)
                response = response_obj.read()
                result = json.loads(response)

                # Test for presence of _su cookie and consume it
                meta_info = response_obj.info()
                if meta_info.has_key("set-cookie"):
                    match = re.search(r"(_su=\S+);", meta_info["set-cookie"])
                    if match and match.group(1) != "_su=deleted":
                        self.su_cookie = match.group(1)

                # Code 15 = list empty (which is okay)
                if result["stat"] != "ok" and result["code"] != 15:
                    raise SmugmugError("API call failed")

                return result
            except SmugmugError:
                if attempt < 4:
                    logging.warn("Failed; retrying.")
                else:
                    logging.warn("Failed; giving up.")
                    logging.debug("Request: %s", request.get_full_url())
                    logging.debug("Response was: %s %s", response, "test")

                    return result

    def call(self, method, params):
        """Function to make an API call to SmugMug."""
        paramstrings = [urllib.quote(key) + "=" + urllib.quote(str(params[key])) for key in params]
        paramstrings += ["method=" + method]

        url = urlparse.urljoin(self.api_url, "?" + "&".join(paramstrings))
        request = urllib2.Request(url)

        if self.su_cookie:
            request.add_header("Cookie", self.su_cookie)

        return self.safe_geturl(request)

def parse_config():
    """Simple function to parse the configuation file."""
    config = ConfigParser.ConfigParser()

    config.read(os.path.join(os.path.dirname(sys.argv[0]), "smugmug.cfg"))
    
    return config

class Upload(threading.Thread):
    """Class for uploading photos in a threaded manner."""
    def __init__(self, album_name, photos, progress):
        super(Upload, self).__init__()
        self.album_name = album_name
        self.photos = photos
        self.progress = progress
        self.start()

    def run(self):
        logging.info("Commencing uploads")

        config = parse_config()

        smugmug = SmugmugAPIHandler()

        result = smugmug.call("smugmug.login.withPassword", {"APIKey": config.get("SmugMug", "api key"), "EmailAddress": config.get("SmugMug", "email"), "Password": config.get("SmugMug", "password")})
        try:
            session = result["Login"]["Session"]["id"]
        except KeyError:
            logging.error("Login failed.  Check credentials.")
            return False

        result = smugmug.call("smugmug.albums.get", {"SessionID" : session})
        album_id = None
        hashes = []
        for remote_album in result["Albums"]:
            if remote_album["Title"] == self.album_name and remote_album["Category"]["Name"] == "Other":
                album_id = remote_album["id"]

                album_data = smugmug.call("smugmug.images.get", {"SessionID": session, "AlbumID": album_id, "AlbumKey": remote_album["Key"], "Heavy": "true"})

                # Produce a list of MD5 hashes for existing images online
                if album_data["stat"] == "ok":
                    logging.info("Compiling existing image hashes")
                    hashes = [item["MD5Sum"] for item in album_data["Album"]["Images"]]

                break

        if album_id is None:
            logging.info("""Album, "%s" was not found.  Creating.""", self.album_name)
            # Create the album
            new_album = smugmug.call("smugmug.albums.create", {"SessionID": session, "FamilyEdit": str(config.getboolean("Albums", "family edit")), "FriendEdit": str(config.getboolean("Albums", "friends edit")), "Public": str(config.getboolean("Albums", "public")), "Title": self.album_name})
            album_id = new_album["Album"]["id"]

        for filename in self.photos:
            logging.info("Uploading %s", filename)

            # Open the file and produce an MD5 hash
            data = open(filename, "rb").read()
            upload_md5 = hashlib.md5(data).hexdigest()

            # Check to see if the hash already exists online.
            if upload_md5 in hashes:
                logging.warn("Image already appears to exist.  Skipping")
                self.progress.step()
                continue

            # Upload the image
            upload_request = urllib2.Request(smugmug.upload_url, data, { "Content-Length": len(data), "Content-MD5": upload_md5, "Content-Type": "none", "X-Smug-SessionID": session, "X-Smug-Version": smugmug.api_version, "X-Smug-ResponseType": "JSON", "X-Smug-AlbumID": album_id, "X-Smug-FileName": os.path.basename(filename) })

            result = smugmug.safe_geturl(upload_request)
            if result["stat"] == "ok":
                logging.info("Successful")
            else:
                logging.error("There was a problem uploading this object to SmugMug.")

            self.progress.step()

        logging.info("Complete")

def main():
    """Function for main program loop"""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Get the album name
    album = Album()
    album.ask_name()

    # Get the array of filenames
    Tkinter.Tk().withdraw()
    photolist = tkFileDialog.askopenfilenames()

    # Remove duplicates
    photolist = set(photolist)

    # Display an error if there are no files
    if len(photolist) == 0:
        tkMessageBox.showerror("ERROR", "No photos to upload.")
        sys.exit(1)

    # Initialise Tkinter window
    root = Tkinter.Tk()
    root.protocol("WM_DELETE_WINDOW", root.quit)

    # Create our output Text widget
    text = Tkinter.Text(root)
    text.pack()

    # Use a logger sub-class to write to the output window
    log_window = WidgetLogger(text)
    logger.addHandler(log_window)

    # Attempt to display a progress bar
    progressbar = ttk.Progressbar(root, length=text.winfo_reqwidth(), maximum=len(photolist))
    progressbar.pack()

    # Kick off the uploads in a thread
    Upload(album.name, photolist, progressbar)

    # Do Tkinter window stuff
    root.mainloop()

    sys.exit(0)

if __name__ == "__main__":
    main()
